import requests
from pydantic_settings import BaseSettings


class RAGConfig(BaseSettings):
    """
    Configuration for the RAG pipeline.
    """

    # Qdrant
    qdrant_host: str = "127.0.0.1"
    qdrant_http_port: int = 6333
    qdrant_grpc_port: int = 6334
    qdrant_grpc: bool = True

    # Embeddings
    embedding_model: str = "nomic-embed-text:latest"
    # embedding_model: str = "embeddinggemma:latest"
    # embedding_model: str = "bge-m3:567m"

    # Ollama port
    ollama_url: str = "http://localhost:11434"

    # Segmentation
    chunk_size: int = 4096  # nombre de bytes de code par chunk
    chunk_overlap: int = 128  # taille d'overlap en bytes pour la segmentation
    # doc_chunk_size: int = 512  # nombre de bytes de document par chunk
    # doc_chunk_overlap: int = 64  # taille d'overlap en bytes pour la segmentation
    # Retrieval
    k: int = 8  # nombre de chunks retournés au final
    fetch_k: int = 15  # nombre initial de chunks récupérés avant déduplication/MMR
    min_score: float = 0.2  # filtrage par score
    # max_chunks_per_file: int = 12

    class Config:
        env_prefix = "RAG_"  # charge depuis variables d'environnement

    @property
    def qdrant_http_url(self) -> str:
        """URL HTTP to pass to the client."""
        return f"http://{self.qdrant_host}:{self.qdrant_http_port}"

    @property
    def qdrant_url(self) -> str:
        """URL GRPC to pass to the client."""
        return f"http://{self.qdrant_host}:{self.qdrant_grpc_port}"

    @property
    def embedding_dimensions(self) -> int:
        """dimensions size (embedding_length) of the embedding model"""
        result = requests.post(f"{self.ollama_url}/api/show", json={"model": self.embedding_model})
        result.raise_for_status()
        info = result.json()
        architecture = info.get("model_info", {}).get("general.architecture", "Unknown Architecture")
        dimensions = info.get("model_info", {}).get(f"{architecture}.embedding_length")
        if not dimensions:
            raise ValueError(f"Embedding length not found for {self.embedding_model}")
        return int(dimensions)

    @property
    def collection_name(self) -> str:
        """make the collection name dybnamic/relative to the used embedding model's name"""
        name = self.embedding_model.replace(":", "_").replace("/", "_")
        return f"{name}_chunks" if self.embedding_model else "code_chunks"
