import re
from typing import Dict, List

from langchain_ollama import OllamaEmbeddings
from langchain_qdrant import QdrantVectorStore

from core.rag.config import RAGConfig


class CodeIndexer:
    """
    Segments the source code source in chunks, generates embeddings with Ollama,
    and indexes in qdrant.
    """

    def __init__(self, config: RAGConfig, qdrant_client=None):
        self.config = config
        self.embedder = OllamaEmbeddings(model=self.config.embedding_model)

        self.qdrant_client = qdrant_client

        self.qdrant = QdrantVectorStore(
            client=self.qdrant_client,
            collection_name=self.config.collection_name,
            embedding=self.embedder,
        )

    def segment_code(self, code: str, max_bytes: int, overlap_bytes: int) -> List[str]:
        """
        Code segmenter for Python-like code.

        - Splits code into logical blocks (prologue + top-level def/class blocks).
        - Accumulates blocks until approx max_bytes (UTF-8)
        - Never truncates a line; only splits a block into sub-blocks if the block alone is too large.
        - If a single line is absurdly larger than max_bytes, it is split safely by bytes (rare)
        - overlap_bytes is implemented by reusing the last lines of the previous chunk
        """
        if not code:
            return []

        lines = code.splitlines()
        n = len(lines)

        # 1) find block start indices: 0 + every top-level def/class
        block_starts = [0]
        for i, line in enumerate(lines):
            stripped = line.lstrip()
            indent = len(line) - len(stripped)
            # top-level def/class or async def
            if indent == 0 and re.match(r"^(async\s+def|def|class)\s+", stripped):
                # avoid adding 0 twice
                if i != 0:
                    block_starts.append(i)
        # ensure last sentinel
        block_starts = sorted(set(block_starts))

        # build blocks (list of list[str])
        blocks = []
        for idx, start in enumerate(block_starts):
            end = block_starts[idx + 1] if idx + 1 < len(block_starts) else n
            block_lines = lines[start:end]
            # skip fully-empty blocks
            if any(line.strip() for line in block_lines):
                blocks.append(block_lines)

        chunks: List[str] = []
        current_chunk_lines: List[str] = []
        current_size = 0  # bytes

        def finalize_current_chunk():
            nonlocal current_chunk_lines, current_size, chunks
            if not current_chunk_lines:
                return
            chunks.append("\n".join(current_chunk_lines).rstrip())
            # prepare overlap as last lines to reuse
            if overlap_bytes and chunks:
                overlap_lines = []
                overlap_size = 0
                for line in reversed(current_chunk_lines):
                    lb = len((line + "\n").encode("utf-8"))
                    if overlap_size + lb > overlap_bytes:
                        break
                    overlap_lines.insert(0, line)
                    overlap_size += lb
                current_chunk_lines = list(overlap_lines)
                current_size = sum(
                    len((line + "\n").encode("utf-8")) for line in current_chunk_lines
                )
            else:
                current_chunk_lines = []
                current_size = 0

        # 2) accumulate blocks into chunks
        for block in blocks:
            block_text = "\n".join(block)
            block_size = len(block_text.encode("utf-8"))

            # If block fits:
            if current_size + block_size <= max_bytes:
                # append whole block
                current_chunk_lines.extend(block if current_chunk_lines == [] else [""] + block)
                current_size += block_size + (
                    0 if current_size == 0 else len("\n".encode("utf-8"))
                )
                continue

            # If current chunk empty but block itself > max_bytes => split block by lines/subblocks
            if not current_chunk_lines and block_size > max_bytes:
                # Split block into sub-chunks of lines that respect max_bytes
                sub_current = []
                sub_size = 0
                for line in block:
                    lb = len((line + "\n").encode("utf-8"))
                    # if single line > max_bytes, we must split the line itself (rare)
                    if lb > max_bytes:
                        # flush any accumulated sub_current first
                        if sub_current:
                            chunks.append("\n".join(sub_current).rstrip())
                            # apply overlap for the chunk we just wrote
                            if overlap_bytes:
                                ol = []
                                ol_size = 0
                                for line in reversed(sub_current):
                                    lbytes = len((line + "\n").encode("utf-8"))
                                    if ol_size + lbytes > overlap_bytes:
                                        break
                                    ol.insert(0, line)
                                    ol_size += lbytes
                                sub_current = list(ol)
                                sub_size = sum(
                                    len((line + "\n").encode("utf-8")) for line in sub_current
                                )
                            else:
                                sub_current = []
                                sub_size = 0
                        # split the long line by bytes (best-effort, decode safe)
                        b = (line + "\n").encode("utf-8")
                        start = 0
                        while start < len(b):
                            end = start + max_bytes
                            piece = b[start:end].decode("utf-8", errors="ignore")
                            chunks.append(piece.rstrip())
                            start += (
                                max_bytes - overlap_bytes
                                if (max_bytes - overlap_bytes) > 0
                                else max_bytes
                            )
                        # continue to next line
                        continue

                    # normal case: line fits into max_bytes
                    if sub_size + lb > max_bytes and sub_current:
                        # flush sub_current
                        chunks.append("\n".join(sub_current).rstrip())
                        # overlap for sub_current
                        if overlap_bytes:
                            ol = []
                            ol_size = 0
                            for line in reversed(sub_current):
                                lbytes = len((line + "\n").encode("utf-8"))
                                if ol_size + lbytes > overlap_bytes:
                                    break
                                ol.insert(0, line)
                                ol_size += lbytes
                            sub_current = list(ol)
                            sub_size = sum(
                                len((line + "\n").encode("utf-8")) for line in sub_current
                            )
                        else:
                            sub_current = []
                            sub_size = 0
                    sub_current.append(line)
                    sub_size += lb
                if sub_current:
                    chunks.append("\n".join(sub_current).rstrip())
                    # reset current chunk (overlap already handled per-sub-chunk above)
                    current_chunk_lines = []
                    current_size = 0
                continue

            # If adding block would overflow but current chunk has content -> finalize current chunk first,
            # then re-process this block
            # (the loop will handle it because current_chunk_lines will be reset/overlap applied)
            if current_chunk_lines:
                finalize_current_chunk()
                # Now reprocess this same block: try to append it fresh
                if block_size <= max_bytes:
                    current_chunk_lines.extend(block)
                    current_size = block_size
                    continue
                else:
                    # block still bigger than max_bytes -> split it as above: best to reuse same splitting logic
                    # we'll do a simple splitting by lines similar to above:
                    sub_current = []
                    sub_size = 0
                    for line in block:
                        lb = len((line + "\n").encode("utf-8"))
                        if lb > max_bytes:
                            if sub_current:
                                chunks.append("\n".join(sub_current).rstrip())
                                # handle overlap for sub_current
                                if overlap_bytes:
                                    ol = []
                                    ol_size = 0
                                    for line in reversed(sub_current):
                                        lbytes = len((line + "\n").encode("utf-8"))
                                        if ol_size + lbytes > overlap_bytes:
                                            break
                                        ol.insert(0, line)
                                        ol_size += lbytes
                                    sub_current = list(ol)
                                    sub_size = sum(
                                        len((line + "\n").encode("utf-8")) for line in sub_current
                                    )
                                else:
                                    sub_current = []
                                    sub_size = 0
                            b = (line + "\n").encode("utf-8")
                            start = 0
                            while start < len(b):
                                end = start + max_bytes
                                piece = b[start:end].decode("utf-8", errors="ignore")
                                chunks.append(piece.rstrip())
                                start += (
                                    max_bytes - overlap_bytes
                                    if (max_bytes - overlap_bytes) > 0
                                    else max_bytes
                                )
                            continue
                        if sub_size + lb > max_bytes and sub_current:
                            chunks.append("\n".join(sub_current).rstrip())
                            if overlap_bytes:
                                ol = []
                                ol_size = 0
                                for line in reversed(sub_current):
                                    lbytes = len((line + "\n").encode("utf-8"))
                                    if ol_size + lbytes > overlap_bytes:
                                        break
                                    ol.insert(0, line)
                                    ol_size += lbytes
                                sub_current = list(ol)
                                sub_size = sum(
                                    len((line + "\n").encode("utf-8")) for line in sub_current
                                )
                            else:
                                sub_current = []
                                sub_size = 0
                        sub_current.append(line)
                        sub_size += lb
                    if sub_current:
                        chunks.append("\n".join(sub_current).rstrip())
                        current_chunk_lines = []
                        current_size = 0
                    continue

        # finalize remaining
        if current_chunk_lines:
            chunks.append("\n".join(current_chunk_lines).rstrip())

        return chunks

    def segment_doc(self, text: str, max_bytes: int, overlap_bytes: int) -> list[str]:
        """
        Segment text into chunks of ~max_bytes using UTF-8 encoding,
        without cutting in the middle of characters
        """
        paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
        chunks = []
        current_chunk = ""
        for para in paragraphs:
            # si ajouter le paragraphe dépasse max_bytes
            if len((current_chunk + "\n" + para).encode("utf-8")) > max_bytes:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                    # overlap
                    overlap_chunk = ""
                    if overlap_bytes > 0:
                        # prendre les derniers caractères jusqu'à overlap_bytes
                        encoded = current_chunk.encode("utf-8")
                        overlap_chunk = encoded[-overlap_bytes:].decode("utf-8", errors="ignore")
                    current_chunk = overlap_chunk + "\n" + para
                else:
                    # paragraphe seul trop gros -> split directement
                    start = 0
                    para_bytes = para.encode("utf-8")
                    while start < len(para_bytes):
                        end = start + max_bytes
                        chunk = para_bytes[start:end].decode("utf-8", errors="ignore")
                        chunks.append(chunk.strip())
                        start += max_bytes - overlap_bytes
                    current_chunk = ""
            else:
                current_chunk += ("\n" if current_chunk else "") + para

        if current_chunk:
            chunks.append(current_chunk.strip())

        return chunks


class CodeRetriever:
    """
    Recovers the most relevant chunks via vector similarity
    """

    def __init__(self, config: RAGConfig, qdrant_client=None):
        self.config = config
        self.embedder = OllamaEmbeddings(model=self.config.embedding_model)

        self.qdrant_client = qdrant_client

        self.qdrant = QdrantVectorStore(
            client=self.qdrant_client,
            collection_name=self.config.collection_name,
            embedding=self.embedder,
        )

    def get_relevant_chunks(self, query: str) -> List[Dict]:
        """
        Returns up to k relevant uniques chunks (text+metadata) for the `query`
        """
        results = self.qdrant.max_marginal_relevance_search(
            query, k=self.config.k, fetch_k=self.config.fetch_k
        )
        seen_texts = set()
        per_file_counts = {}
        chunks = []
        for doc, score in results:
            if score < self.config.min_score:
                continue
            path = doc.metadata.get("path", "")
            # max 2 chunks par fichier
            per_file_counts[path] = per_file_counts.get(path, 0)
            if per_file_counts[path] >= 2:
                continue

            text = doc.page_content.strip()
            if text in seen_texts:
                continue
            seen_texts.add(text)

            chunks.append({"text": text, "metadata": doc.metadata})
            per_file_counts[path] += 1
            if len(chunks) >= self.config.k:
                break
        return chunks
