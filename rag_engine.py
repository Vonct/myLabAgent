from openai import OpenAI
from pypdf import PdfReader
from io import BytesIO
import json
import os
import math


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
            response = self.client.embeddings.create(
                model=self.model_name,
                input=batch
            )
            vectors.extend([item.embedding for item in response.data])
            usage = self._parse_usage(getattr(response, "usage", None))
            usage_sum["input_tokens"] += usage["input_tokens"]
            usage_sum["total_tokens"] += usage["total_tokens"]
        return vectors, usage_sum

class RAGEngine:
    def __init__(self, api_key: str, base_url: str, embedding_model: str = "text-embedding-v4"):
        self.api_key = api_key
        self.base_url = base_url
        self.embedding_model = embedding_model
        self.embedding_function = QwenEmbeddingFunction(
            api_key=self.api_key,
            base_url=self.base_url,
            model_name=self.embedding_model
        )
        self.backend = "memory"
        self.records_file = "./vector_store.json"
        self.records = []
        self.embedding_usage_total = {"input_tokens": 0, "total_tokens": 0}
        self.last_embedding_usage = {"input_tokens": 0, "total_tokens": 0}
        try:
            import chromadb
            self.client = chromadb.PersistentClient(path="./chroma_db")
            try:
                self.collection = self.client.get_collection(
                    name="docs",
                    embedding_function=self.embedding_function
                )
            except Exception:
                self.collection = self.client.create_collection(
                    name="docs",
                    embedding_function=self.embedding_function
                )
            self.backend = "chroma"
        except Exception:
            if os.path.exists(self.records_file):
                with open(self.records_file, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    self.records = json.loads(content) if content else []

    def process_file(self, file_content: BytesIO, filename: str) -> str:
        """
        处理上传的文件：读取 -> 分块 -> 向量化 -> 存储
        返回：处理结果信息
        """
        try:
            # 1. 文本提取
            reader = PdfReader(file_content)
            text = ""
            for page in reader.pages:
                text += page.extract_text() + "\n"
            
            if not text.strip():
                return f"⚠️ 文件 {filename} 内容为空或无法解析。"

            # 2. 文本分块 (简单的按字符数切分，重叠部分用于保持上下文)
            chunk_size = 1000
            overlap = 100
            chunks = []
            for i in range(0, len(text), chunk_size - overlap):
                chunks.append(text[i:i + chunk_size])

            # 3. 生成 ID 和元数据
            ids = [f"{filename}_{i}" for i in range(len(chunks))]
            metadatas = [{"source": filename, "chunk_index": i} for i in range(len(chunks))]

            if self.backend == "chroma":
                _, usage = self.embedding_function.embed_with_usage(chunks)
                self.last_embedding_usage = usage
                self.embedding_usage_total["input_tokens"] += usage["input_tokens"]
                self.embedding_usage_total["total_tokens"] += usage["total_tokens"]
                self.collection.add(
                    documents=chunks,
                    ids=ids,
                    metadatas=metadatas
                )
            else:
                vectors, usage = self.embedding_function.embed_with_usage(chunks)
                self.last_embedding_usage = usage
                self.embedding_usage_total["input_tokens"] += usage["input_tokens"]
                self.embedding_usage_total["total_tokens"] += usage["total_tokens"]
                for i, chunk in enumerate(chunks):
                    self.records.append({
                        "id": ids[i],
                        "document": chunk,
                        "metadata": metadatas[i],
                        "embedding": vectors[i]
                    })
                with open(self.records_file, "w", encoding="utf-8") as f:
                    json.dump(self.records, f, ensure_ascii=False)
            
            return (
                f"✅ 成功处理文件: {filename}，生成 {len(chunks)} 个文本块并完成向量化。"
                f"（本次Embedding Tokens: 输入 {self.last_embedding_usage['input_tokens']}，总计 {self.last_embedding_usage['total_tokens']}）"
            )
        
        except Exception as e:
            return f"❌ 处理文件 {filename} 时发生错误: {str(e)}"

    def retrieve(self, query: str, n_results: int = 3) -> list:
        if self.backend == "chroma":
            results = self.collection.query(
                query_texts=[query],
                n_results=n_results
            )
            retrieved_docs = []
            if results["documents"]:
                for i, doc in enumerate(results["documents"][0]):
                    meta = results["metadatas"][0][i]
                    retrieved_docs.append({
                        "content": doc,
                        "source": meta.get("source", "unknown"),
                        "score": results["distances"][0][i] if "distances" in results else 0
                    })
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
        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:n_results]
        return [
            {
                "content": it["document"],
                "source": it["metadata"].get("source", "unknown"),
                "score": score
            }
            for score, it in top
        ]

    def clear_db(self):
        try:
            if self.backend == "chroma":
                self.client.delete_collection("docs")
                self.collection = self.client.create_collection(
                    name="docs",
                    embedding_function=self.embedding_function
                )
            else:
                self.records = []
                with open(self.records_file, "w", encoding="utf-8") as f:
                    f.write("[]")
            self.last_embedding_usage = {"input_tokens": 0, "total_tokens": 0}
            self.embedding_usage_total = {"input_tokens": 0, "total_tokens": 0}
            return "数据库已清空。"
        except Exception as e:
            return f"清空数据库失败: {str(e)}"

    def get_embedding_usage(self):
        return {
            "last": self.last_embedding_usage,
            "total": self.embedding_usage_total
        }
