import json
import logging
import math
import os
import threading
from io import BytesIO
from pathlib import Path

from openai import OpenAI
from pypdf import PdfReader


LOGGER = logging.getLogger(__name__)
if not LOGGER.handlers:
    log_dir = Path(__file__).resolve().parent / "app_data"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_dir / "rag_engine.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)


class QwenEmbeddingFunction:
    def __init__(self, api_key: str, base_url: str, model_name: str):
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model_name = model_name

    def __call__(self, input):
        vectors, _ = self.embed_with_usage(input)
        return vectors

    def _parse_usage(self, usage):
        if usage is None:
            return {"input_tokens": 0, "total_tokens": 0}
        if isinstance(usage, dict):
            input_tokens = int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0)
            total_tokens = int(usage.get("total_tokens", input_tokens) or input_tokens)
            return {"input_tokens": input_tokens, "total_tokens": total_tokens}
        input_tokens = int(getattr(usage, "prompt_tokens", getattr(usage, "input_tokens", 0)) or 0)
        total_tokens = int(getattr(usage, "total_tokens", input_tokens) or input_tokens)
        return {"input_tokens": input_tokens, "total_tokens": total_tokens}

    def embed_with_usage(self, input):
        texts = input if isinstance(input, list) else [input]
        batch_size = 10
        vectors = []
        usage_sum = {"input_tokens": 0, "total_tokens": 0}
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            response = self.client.embeddings.create(model=self.model_name, input=batch)
            vectors.extend([item.embedding for item in response.data])
            usage = self._parse_usage(getattr(response, "usage", None))
            usage_sum["input_tokens"] += usage["input_tokens"]
            usage_sum["total_tokens"] += usage["total_tokens"]
        return vectors, usage_sum


class RAGEngine:
    def __init__(self, api_key: str, base_url: str, embedding_model: str = "text-embedding-v4"):
        project_root = Path(__file__).resolve().parent
        self.api_key = api_key
        self.base_url = base_url
        self.embedding_model = embedding_model
        self.embedding_function = QwenEmbeddingFunction(
            api_key=self.api_key,
            base_url=self.base_url,
            model_name=self.embedding_model,
        )
        self.backend = "memory"
        self.backend_init_error = ""
        self.backend_runtime_error = ""
        self.project_root = project_root
        self.records_file = str(project_root / "vector_store.json")
        self.chroma_path = os.environ.get("RAG_CHROMA_PATH", str(project_root / "chroma_db")).strip() or str(project_root / "chroma_db")
        self.collection_name = "docs"
        self.client = None
        self.collection = None
        self.client_thread_id = None
        self.records = []
        self.embedding_usage_total = {"input_tokens": 0, "total_tokens": 0}
        self.last_embedding_usage = {"input_tokens": 0, "total_tokens": 0}
        preferred_backend = os.environ.get("RAG_BACKEND", "chroma").strip().lower()
        if preferred_backend not in {"auto", "chroma", "memory"}:
            preferred_backend = "chroma"
        if preferred_backend != "memory":
            try:
                import chromadb

                self._connect_chroma()
                self.backend = "chroma"
                LOGGER.info("Initialized RAG backend: chroma")
            except Exception as exc:
                self.backend_init_error = repr(exc)
                LOGGER.exception("Failed to initialize chroma backend, falling back to memory")
                self._load_memory_records()
                if preferred_backend == "chroma":
                    self.backend = "memory"
        else:
            LOGGER.info("Initialized RAG backend: memory")
            self._load_memory_records()

    def _load_memory_records(self):
        if os.path.exists(self.records_file):
            with open(self.records_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
                self.records = json.loads(content) if content else []

    def _append_memory_batch(self, ids, chunks, metadatas, vectors):
        for index, chunk in enumerate(chunks):
            self.records.append(
                {
                    "id": ids[index],
                    "document": chunk,
                    "metadata": metadatas[index],
                    "embedding": vectors[index],
                }
            )

    def _fallback_to_memory(self, reason: str):
        self.backend_runtime_error = reason
        self.backend = "memory"
        LOGGER.error("RAG backend runtime fallback to memory: %s", reason)
        self._load_memory_records()

    def _connect_chroma(self):
        import chromadb

        current_thread_id = threading.get_ident()
        self.client = chromadb.PersistentClient(path=self.chroma_path)
        self.collection = self.client.get_or_create_collection(name=self.collection_name)
        self.client_thread_id = current_thread_id
        LOGGER.info("Connected chroma client on thread=%s path=%s", current_thread_id, self.chroma_path)

    def _ensure_chroma_connection(self):
        if self.backend != "chroma":
            return
        current_thread_id = threading.get_ident()
        if self.client is None or self.collection is None or self.client_thread_id != current_thread_id:
            LOGGER.info(
                "Refreshing chroma connection: previous_thread=%s current_thread=%s",
                self.client_thread_id,
                current_thread_id,
            )
            self._connect_chroma()

    def _iter_text_chunks(self, reader: PdfReader, chunk_size: int, overlap: int):
        carry = ""
        step = max(1, chunk_size - overlap)
        last_page_index = 0
        for page_index, page in enumerate(reader.pages):
            last_page_index = page_index
            extracted = page.extract_text() or ""
            if not extracted.strip():
                continue
            page_text = f"{carry}{extracted}\n"
            start = 0
            while start + chunk_size <= len(page_text):
                yield page_index, page_text[start:start + chunk_size]
                start += step
            carry = page_text[start:]
            if len(carry) > overlap:
                carry = carry[-overlap:]
        if carry.strip():
            yield last_page_index, carry

    def _flush_batch(self, ids, chunks, metadatas):
        if not chunks:
            return {"input_tokens": 0, "total_tokens": 0}

        vectors, usage = self.embedding_function.embed_with_usage(chunks)
        if self.backend == "chroma":
            self._ensure_chroma_connection()
            try:
                LOGGER.info("Chroma upsert begin: thread=%s batch=%s", threading.get_ident(), len(chunks))
                self.collection.upsert(
                    documents=chunks,
                    ids=ids,
                    metadatas=metadatas,
                    embeddings=vectors,
                )
                LOGGER.info("Chroma upsert end: thread=%s batch=%s", threading.get_ident(), len(chunks))
            except Exception as exc:
                self._fallback_to_memory(repr(exc))
                self._append_memory_batch(ids, chunks, metadatas, vectors)
        else:
            self._append_memory_batch(ids, chunks, metadatas, vectors)
        return usage

    def process_file(self, file_content: BytesIO, filename: str) -> str:
        try:
            LOGGER.info("Start processing file: %s", filename)
            reader = PdfReader(file_content)
            chunk_size = 1000
            overlap = 100
            embed_batch_size = 10
            file_usage = {"input_tokens": 0, "total_tokens": 0}
            batch_ids = []
            batch_chunks = []
            batch_metadatas = []
            total_chunks = 0

            for page_index, chunk in self._iter_text_chunks(reader, chunk_size, overlap):
                chunk_text = chunk.strip()
                if not chunk_text:
                    continue
                batch_ids.append(f"{filename}_{total_chunks}")
                batch_chunks.append(chunk_text)
                batch_metadatas.append(
                    {"source": filename, "chunk_index": total_chunks, "page_index": page_index}
                )
                total_chunks += 1

                if len(batch_chunks) >= embed_batch_size:
                    usage = self._flush_batch(batch_ids, batch_chunks, batch_metadatas)
                    file_usage["input_tokens"] += usage["input_tokens"]
                    file_usage["total_tokens"] += usage["total_tokens"]
                    LOGGER.info(
                        "Processed embedding batch for %s: chunk_count=%s",
                        filename,
                        total_chunks,
                    )
                    batch_ids, batch_chunks, batch_metadatas = [], [], []

            if batch_chunks:
                usage = self._flush_batch(batch_ids, batch_chunks, batch_metadatas)
                file_usage["input_tokens"] += usage["input_tokens"]
                file_usage["total_tokens"] += usage["total_tokens"]

            if total_chunks == 0:
                LOGGER.warning("File has no extractable text: %s", filename)
                return f"[ERROR] No extractable text found in {filename}."

            if self.backend != "chroma":
                with open(self.records_file, "w", encoding="utf-8") as f:
                    json.dump(self.records, f, ensure_ascii=False)

            self.last_embedding_usage = file_usage
            self.embedding_usage_total["input_tokens"] += file_usage["input_tokens"]
            self.embedding_usage_total["total_tokens"] += file_usage["total_tokens"]
            LOGGER.info(
                "Finished processing file: %s, total_chunks=%s, tokens=%s",
                filename,
                total_chunks,
                file_usage["total_tokens"],
            )

            return (
                f"Processed {filename}: generated {total_chunks} chunks. "
                f"Embedding tokens this run: input {self.last_embedding_usage['input_tokens']}, "
                f"total {self.last_embedding_usage['total_tokens']}."
            )
        except Exception as exc:
            LOGGER.exception("Failed to process file: %s", filename)
            return f"[ERROR] Failed to process {filename}: {exc}"

    def retrieve(self, query: str, n_results: int = 3) -> list:
        if self.backend == "chroma":
            query_vector, _ = self.embedding_function.embed_with_usage([query])
            self._ensure_chroma_connection()
            try:
                LOGGER.info("Chroma query begin: thread=%s n_results=%s", threading.get_ident(), n_results)
                results = self.collection.query(query_embeddings=query_vector, n_results=n_results)
                LOGGER.info("Chroma query end: thread=%s n_results=%s", threading.get_ident(), n_results)
            except Exception as exc:
                self._fallback_to_memory(repr(exc))
                return self.retrieve(query, n_results)
            retrieved_docs = []
            if results["documents"]:
                for i, doc in enumerate(results["documents"][0]):
                    meta = results["metadatas"][0][i]
                    retrieved_docs.append(
                        {
                            "content": doc,
                            "source": meta.get("source", "unknown"),
                            "score": results["distances"][0][i] if "distances" in results else 0,
                        }
                    )
            return retrieved_docs
        if not self.records:
            return []
        query_vector = self.embedding_function([query])[0]
        scored = []
        qn = math.sqrt(sum(v * v for v in query_vector)) or 1.0
        for item in self.records:
            emb = item["embedding"]
            dn = math.sqrt(sum(v * v for v in emb)) or 1.0
            score = sum(a * b for a, b in zip(query_vector, emb)) / (qn * dn)
            scored.append((score, item))
        scored.sort(key=lambda item: item[0], reverse=True)
        top = scored[:n_results]
        return [
            {
                "content": item["document"],
                "source": item["metadata"].get("source", "unknown"),
                "score": score,
            }
            for score, item in top
        ]

    def clear_db(self):
        try:
            if self.backend == "chroma":
                self._ensure_chroma_connection()
                self.client.delete_collection(self.collection_name)
                self.collection = self.client.get_or_create_collection(name=self.collection_name)
            else:
                self.records = []
                with open(self.records_file, "w", encoding="utf-8") as f:
                    f.write("[]")
            self.last_embedding_usage = {"input_tokens": 0, "total_tokens": 0}
            self.embedding_usage_total = {"input_tokens": 0, "total_tokens": 0}
            return "Knowledge base cleared."
        except Exception as exc:
            LOGGER.exception("Failed to clear knowledge base")
            return f"[ERROR] Failed to clear knowledge base: {exc}"

    def get_embedding_usage(self):
        return {
            "last": self.last_embedding_usage,
            "total": self.embedding_usage_total,
        }
