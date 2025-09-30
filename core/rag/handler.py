import uuid
from pathlib import Path
from typing import Dict, List

from langchain_ollama import OllamaEmbeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.http.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)
from qdrant_client.models import MatchAny

from core.rag.config import RAGConfig
from core.rag.file_loader import SUPPORTED, extract_text


class RAGHandler:
    """
    Orchestrator of the RAG pipeline : indexing, refreshment, retrieval, prompt building.
    """

    def __init__(self, config: RAGConfig, session_id: int, ctx_parser=None):
        self.config = config
        self.session_id = session_id
        self._ctx_parser = ctx_parser

        # Embeddings
        self.embedder = OllamaEmbeddings(model=self.config.embedding_model)
        print(
            f"Embedding model for vectorization : {self.embedder} with {self.config.embedding_dimensions} dimensions"
        )
        # Connexion à Qdrant
        self.qdrant_client = QdrantClient(
            host=self.config.qdrant_host,
            grpc_port=self.config.qdrant_grpc_port,
            prefer_grpc=self.config.qdrant_grpc,
            timeout=10.0,
        )

        # créer la collection si elle n'existe pas
        try:
            self.qdrant_client.get_collection(self.config.collection_name)
        except Exception:
            ("no collection gotten, try to recreate one")
            self.qdrant_client.recreate_collection(
                collection_name=self.config.collection_name,
                vectors_config=VectorParams(
                    size=self.config.embedding_dimensions,  # 768 ou 1536 selon modèle...
                    distance=Distance.COSINE,
                ),
            )

        # Vectorstore wrapper LangChain
        self.vstore = QdrantVectorStore(
            client=self.qdrant_client,
            collection_name=self.config.collection_name,
            embedding=self.embedder,
        )

        # indexer, retriever & prompter
        from core.prompt_manager import RAGPromptManager
        from core.rag.indexer import CodeIndexer, CodeRetriever

        # Indexer / Retriever
        self.indexer = CodeIndexer(self.config, qdrant_client=self.qdrant_client)
        self.retriever = CodeRetriever(self.config, qdrant_client=self.qdrant_client)
        self.prompter = RAGPromptManager(self.config)

    def debug_list_paths_in_qdrant(self):
        points, _ = self.vstore.client.scroll(
            collection_name=self.vstore.collection_name,
            with_payload=True,
            limit=1000,
        )
        all_paths = {p.payload.get("path", "<no-path>") for p in points}
        # print("debug : Paths indexés dans Qdrant :")
        for p in sorted(all_paths):
            print("   -", p)

    def index_files(self, files: List[Path]) -> int:
        """
        Indexes each file according to its type :
        - for .doc, .docx, .ppt, .pptx, .pdf, .rtf -> extraction via core.rag.file_loader.extract_text()
        - For any other suffix (code .py, .txt, etc.) -> segmentation via CodeIndexer
        - reads/chunks each file
        - calculate embedding via self.embedder.embed_documents
        - builds PointStruct(id, vector, payload) where payload contains path, chunk_index, session_id and text
        - upserte via self.qdrant_client.upsert()
        Then :
        1) Generation of Embeddings
        2) building of PointStruct
        3) upsert in Qdrant
        Returns the total number of indexed chunks.
        """
        texts: List[str] = []
        metadatas: List[Dict] = []

        for f in files:
            ext = f.suffix.lower()
            if ext in SUPPORTED:
                # ─── Traitement DOCUMENT avec file_loader
                try:
                    full_text = extract_text(f)
                    segments = self.indexer.segment_doc(
                        text=full_text,
                        max_bytes=self.config.chunk_size,
                        overlap_bytes=self.config.chunk_overlap,
                    )
                except Exception as e:
                    print(f"RAGHandler.index_files - Extraction error for document {f}: {e}")
                    continue
            else:
                # ─── Traitement CODE / TEXTE normal
                try:
                    full_text = f.read_text(encoding="utf-8", errors="ignore")
                    segments = self.indexer.segment_code(
                        code=full_text,
                        max_bytes=self.config.chunk_size,
                        overlap_bytes=self.config.chunk_overlap,
                    )
                except Exception as e:
                    print(f"RAGHandler.index_files - Impossible to read {f}: {e}")
                    continue

            norm_path = str(f).replace("\\", "/")
            for idx, chunk in enumerate(segments):
                texts.append(chunk)
                metadatas.append(
                    {
                        "path": norm_path,
                        "chunk_index": idx,
                        "session_id": self.session_id,
                        "text": chunk,
                    }
                )

        # Si rien à indexer, on sort
        if not texts:
            print("RAGHandler.index_files : No text to index.")
            return 0

        # Génération des embeddings pour TOUS les chunks
        embeddings = self.embedder.embed_documents(texts)

        total = 0
        batch_size = 128
        for start in range(0, len(embeddings), batch_size):
            batch_emb = embeddings[start: start + batch_size]
            batch_meta = metadatas[start: start + batch_size]
            points: List[PointStruct] = []
            for vec, md in zip(batch_emb, batch_meta):
                points.append(
                    PointStruct(
                        id=str(uuid.uuid4()),  # ID toujours unique
                        vector=vec,
                        payload=md,
                    )
                )
            self.qdrant_client.upsert(
                collection_name=self.config.collection_name,
                points=points,
                wait=True,  # attendre commit avant de continuer
            )
            total += len(points)

        return total

    def refresh_files(self, files: List[Path]) -> int:
        """
        For each file, purges existing chunks (par session_id+path)
        and re-index.
        """
        # 1) Supprimer anciens
        for fpath in files:
            self.qdrant_client.delete(
                collection_name=self.config.collection_name,
                points_selector=Filter(
                    must=[
                        FieldCondition(key="session_id", match=MatchValue(value=self.session_id)),
                        FieldCondition(
                            key="path", match=MatchValue(value=str(fpath).replace("\\", "/"))
                        ),
                    ]
                ),
            )
        # 2) Ré-indexer
        return self.index_files(files)

    def get_chunks(
        self,
        query: str,
        k: int = None,
        allowed_paths: List[str] | None = None,
    ) -> List[Dict]:
        """
        Recover the k best chunks via search gRPC :
         - embed_query
         - QdrantClient.search(...) with filter if necessary
         - Returns Dict List{text, metadata}
        """

        k_ = k or self.config.k
        query_vector = self.embedder.embed_query(query)

        grpc_filter = None
        if allowed_paths:
            norm = [p.replace("\\", "/") for p in allowed_paths]
            grpc_filter = Filter(must=[FieldCondition(key="path", match=MatchAny(any=norm))])
            # print(f"debug : [RAGHandler] filter on paths={norm}")

        hits = self.qdrant_client.search(
            collection_name=self.config.collection_name,
            query_vector=query_vector,
            limit=k_,
            with_payload=True,
            query_filter=grpc_filter,
        )
        # print(f"debug : [RAGHandler] found {len(hits)} chunks via gRPC search")

        results = []
        for h in hits:
            txt = h.payload.get("text", "")
            # path = h.payload.get("path", "<no-path>")
            # print(f"Chunk | path={path} | len(text)={len(txt)}")
            results.append({"text": txt, "metadata": h.payload})

        return results

    def build_rag_prompt(
        self, query: str, current_system_prompt: str, allowed_paths: list[str] | None = None
    ) -> str:
        """
        Build the complete RAG prompt to send to the LLM.
        """
        if self.session_id is None:
            raise RuntimeError("RAGHandler not initialized: missing session_id!")

        # récupère les chunks...
        chunks = self.get_chunks(query, k=self.config.k, allowed_paths=allowed_paths)
        if not chunks:
            raise RuntimeError(
                f"No chunk found in Rag for paths={allowed_paths}\n"
                "First press 'Context vectorization' button before sending your request"
            )

        # et construit le prompt
        return self.prompter.build_rag_prompt(current_system_prompt, query, chunks)

    def purge_collection(self):
        """purge collection to reindex files"""
        # print("debug : Suppression et recréation de la collection Qdrant...")
        try:
            self.qdrant_client.delete_collection(self.config.collection_name)
        except Exception as e:
            print(f"purge_collection: collection inexistante ou déjà supprimée ({e})")

        import time

        time.sleep(0.5)
        # après un pti délai pour éviter la concurrence entre delete et create
        self.qdrant_client.recreate_collection(
            collection_name=self.config.collection_name,
            vectors_config=VectorParams(
                size=self.config.embedding_dimensions,
                distance=Distance.COSINE,
            ),
        )
        # print("debug : Collection purgée et recréée.")
