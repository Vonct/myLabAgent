import json
import logging
import math
import os
import posixpath
import re
import shutil
import threading
import zipfile
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET

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
        self.chroma_path = (
            os.environ.get("RAG_CHROMA_PATH", str(project_root / "chroma_db")).strip()
            or str(project_root / "chroma_db")
        )
        self.collection_name = "docs"
        self.client = None
        self.collection = None
        self.client_thread_id = None
        self.records = []
        self.embedding_usage_total = {"input_tokens": 0, "total_tokens": 0}
        self.last_embedding_usage = {"input_tokens": 0, "total_tokens": 0}
        self.enable_image_proxy = os.environ.get("RAG_ENABLE_IMAGE_PROXY", "1").strip().lower() not in {
            "0",
            "false",
            "no",
        }
        self.chunk_strategy = os.environ.get("RAG_CHUNK_STRATEGY", "recursive").strip().lower() or "recursive"
        if self.chunk_strategy not in {"fixed", "recursive"}:
            self.chunk_strategy = "recursive"
        self.chunk_size = max(200, int(os.environ.get("RAG_CHUNK_SIZE", "1200")))
        self.chunk_overlap = max(0, int(os.environ.get("RAG_CHUNK_OVERLAP", "200")))
        self.embed_batch_size = max(1, int(os.environ.get("RAG_EMBED_BATCH_SIZE", "10")))
        self.image_context_chars = max(120, int(os.environ.get("RAG_IMAGE_CONTEXT_CHARS", "700")))
        self.image_store_dir = project_root / "app_data" / "rag_images"
        self.image_store_dir.mkdir(parents=True, exist_ok=True)
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

    def _normalize_text(self, text: str) -> str:
        lines = [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
        cleaned_lines: list[str] = []
        previous_blank = False
        for line in lines:
            normalized = " ".join(line.split())
            if not normalized:
                if not previous_blank and cleaned_lines:
                    cleaned_lines.append("")
                previous_blank = True
                continue
            cleaned_lines.append(normalized)
            previous_blank = False
        return "\n".join(cleaned_lines).strip()

    def _safe_source_slug(self, filename: str) -> str:
        slug = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(filename).stem).strip("._")
        return slug or "document"

    def _source_asset_dir(self, filename: str) -> Path:
        suffix = Path(filename).suffix.lower().lstrip(".") or "file"
        return self.image_store_dir / f"{self._safe_source_slug(filename)}_{suffix}"

    def _truncate_context(self, text: str, limit: int | None = None) -> str:
        normalized = self._normalize_text(text)
        effective_limit = limit or self.image_context_chars
        if len(normalized) <= effective_limit:
            return normalized
        return normalized[:effective_limit].rstrip() + "..."

    def _normalize_zip_target(self, base_dir: str, target: str) -> str:
        normalized = posixpath.normpath(posixpath.join(base_dir, target))
        return normalized.lstrip("./")

    def _ensure_bytes(self, payload) -> bytes:
        if payload is None:
            return b""
        if isinstance(payload, (bytes, bytearray)):
            return bytes(payload)
        if hasattr(payload, "read"):
            return payload.read()
        return b""

    def _save_image_asset(self, filename: str, asset_name: str, image_bytes: bytes) -> str:
        if not image_bytes:
            return ""
        asset_dir = self._source_asset_dir(filename)
        asset_dir.mkdir(parents=True, exist_ok=True)
        cleaned_name = re.sub(r"[^A-Za-z0-9._-]+", "_", asset_name).strip("._") or "image.bin"
        asset_path = asset_dir / cleaned_name
        with open(asset_path, "wb") as fw:
            fw.write(image_bytes)
        return str(asset_path)

    def _build_image_proxy_text(
        self,
        *,
        filename: str,
        file_type: str,
        image_index: int,
        context_text: str = "",
        page_index: int | None = None,
        asset_name: str = "",
        anchor_text: str = "",
    ) -> str:
        lines = [
            "[图片代理记录]",
            f"[来源: {filename}]",
            f"[文件类型: {file_type}]",
            f"[图片序号: {image_index + 1}]",
        ]
        if page_index is not None:
            lines.append(f"[页码: {page_index + 1}]")
        if asset_name:
            lines.append(f"[图片文件: {asset_name}]")
        anchor = self._truncate_context(anchor_text, 220)
        if anchor:
            lines.append(f"[图片锚点文本: {anchor}]")
        context = self._truncate_context(context_text)
        if context:
            lines.append(f"[周边上下文]\n{context}")
        else:
            lines.append("[周边上下文]\n当前未提取到图片附近的正文，后续可接 OCR 或视觉摘要增强。")
        return "\n".join(lines)

    def _extract_pdf_page_images(self, page, page_index: int, filename: str, page_text: str) -> list[dict]:
        if not self.enable_image_proxy:
            return []
        try:
            page_images = list(getattr(page, "images", []) or [])
        except Exception:
            LOGGER.exception("Failed to inspect PDF page images: %s page=%s", filename, page_index)
            return []

        segments: list[dict] = []
        for image_index, image_obj in enumerate(page_images):
            image_name = str(getattr(image_obj, "name", "") or f"page_{page_index + 1}_image_{image_index + 1}.bin")
            image_bytes = self._ensure_bytes(getattr(image_obj, "data", None))
            if not image_bytes:
                pil_image = getattr(image_obj, "image", None)
                if pil_image is not None and hasattr(pil_image, "save"):
                    buffer = BytesIO()
                    image_format = str(getattr(pil_image, "format", "") or "PNG").upper()
                    pil_image.save(buffer, format=image_format)
                    image_bytes = buffer.getvalue()
                    if "." not in image_name:
                        image_name = f"{image_name}.{image_format.lower()}"
            asset_path = self._save_image_asset(filename, image_name, image_bytes)
            if not asset_path:
                continue
            segments.append(
                {
                    "text": self._build_image_proxy_text(
                        filename=filename,
                        file_type="pdf",
                        image_index=image_index,
                        page_index=page_index,
                        asset_name=Path(asset_path).name,
                        context_text=page_text,
                    ),
                    "metadata": {
                        "page_index": page_index,
                        "segment_index": page_index,
                        "segment_kind": "image_proxy",
                        "record_type": "image_proxy",
                        "image_index": image_index,
                        "asset_path": asset_path,
                    },
                }
            )
        return segments

    def _extract_pdf_segments(self, file_content: BytesIO, filename: str) -> list[dict]:
        reader = PdfReader(file_content)
        segments: list[dict] = []
        for page_index, page in enumerate(reader.pages):
            extracted = self._normalize_text(page.extract_text() or "")
            if not extracted:
                extracted = ""
            if extracted:
                segments.append(
                    {
                        "text": extracted,
                        "metadata": {
                            "page_index": page_index,
                            "segment_index": page_index,
                            "segment_kind": "page",
                            "record_type": "text",
                        },
                    }
                )
            segments.extend(self._extract_pdf_page_images(page, page_index, filename, extracted))
        return segments

    def _extract_plaintext_segments(self, file_content: BytesIO) -> list[dict]:
        text = file_content.read().decode("utf-8", errors="ignore")
        normalized = self._normalize_text(text)
        if not normalized:
            return []
        return [
            {
                "text": normalized,
                "metadata": {
                    "segment_index": 0,
                    "segment_kind": "document",
                },
            }
        ]

    def _extract_docx_paragraph_text(self, paragraph, namespace: dict[str, str]) -> str:
        parts: list[str] = []
        for node in paragraph.iter():
            tag = node.tag.rsplit("}", 1)[-1]
            if tag == "t" and node.text:
                parts.append(node.text)
            elif tag == "tab":
                parts.append("\t")
            elif tag in {"br", "cr"}:
                parts.append("\n")
        return self._normalize_text("".join(parts))

    def _extract_docx_relationships(self, archive: zipfile.ZipFile) -> dict[str, str]:
        rels_path = "word/_rels/document.xml.rels"
        if rels_path not in archive.namelist():
            return {}
        rels_root = ET.fromstring(archive.read(rels_path))
        rels: dict[str, str] = {}
        for rel in rels_root.findall(".//{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"):
            rel_id = str(rel.attrib.get("Id", "")).strip()
            target = str(rel.attrib.get("Target", "")).strip()
            if rel_id and target:
                rels[rel_id] = self._normalize_zip_target("word", target)
        return rels

    def _extract_docx_segments(self, file_content: BytesIO, filename: str) -> list[dict]:
        file_content.seek(0)
        namespace = {
            "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
            "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
            "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
            "v": "urn:schemas-microsoft-com:vml",
        }
        try:
            with zipfile.ZipFile(file_content) as archive:
                xml_bytes = archive.read("word/document.xml")
                rels = self._extract_docx_relationships(archive)
                root = ET.fromstring(xml_bytes)
                body = root.find(".//w:body", namespace)
                if body is None:
                    return []

                items: list[dict] = []
                paragraphs: list[str] = []
                image_counter = 0
                for child in list(body):
                    tag = child.tag.rsplit("}", 1)[-1]
                    if tag != "p":
                        continue
                    paragraph_text = self._extract_docx_paragraph_text(child, namespace)
                    if paragraph_text:
                        paragraphs.append(paragraph_text)
                        items.append({"type": "paragraph", "text": paragraph_text})

                    embed_ids: list[str] = []
                    for blip in child.findall(".//a:blip", namespace):
                        rel_id = str(blip.attrib.get(f"{{{namespace['r']}}}embed", "")).strip()
                        if rel_id:
                            embed_ids.append(rel_id)
                    for image_data in child.findall(".//v:imagedata", namespace):
                        rel_id = str(image_data.attrib.get(f"{{{namespace['r']}}}id", "")).strip()
                        if rel_id:
                            embed_ids.append(rel_id)

                    for rel_id in embed_ids:
                        items.append(
                            {
                                "type": "image_ref",
                                "rel_id": rel_id,
                                "anchor_text": paragraph_text,
                                "image_index": image_counter,
                            }
                        )
                        image_counter += 1

                segments: list[dict] = []
                normalized = "\n\n".join(paragraphs).strip()
                if normalized:
                    segments.append(
                        {
                            "text": normalized,
                            "metadata": {
                                "segment_index": 0,
                                "segment_kind": "document",
                                "record_type": "text",
                            },
                        }
                    )

                if not self.enable_image_proxy:
                    return segments

                for index, item in enumerate(items):
                    if item.get("type") != "image_ref":
                        continue
                    rel_target = rels.get(str(item.get("rel_id", "")).strip(), "")
                    if not rel_target:
                        continue
                    try:
                        image_bytes = archive.read(rel_target)
                    except KeyError:
                        LOGGER.warning("DOCX image target missing: %s target=%s", filename, rel_target)
                        continue

                    before_text = ""
                    after_text = ""
                    for cursor in range(index - 1, -1, -1):
                        if items[cursor].get("type") == "paragraph":
                            before_text = str(items[cursor].get("text", "")).strip()
                            break
                    for cursor in range(index + 1, len(items)):
                        if items[cursor].get("type") == "paragraph":
                            after_text = str(items[cursor].get("text", "")).strip()
                            break

                    context_parts: list[str] = []
                    for candidate in [item.get("anchor_text", ""), before_text, after_text]:
                        text = self._normalize_text(str(candidate or ""))
                        if text and text not in context_parts:
                            context_parts.append(text)
                    image_name = Path(rel_target).name or f"docx_image_{item.get('image_index', 0) + 1}.bin"
                    asset_path = self._save_image_asset(filename, image_name, image_bytes)
                    if not asset_path:
                        continue
                    image_index = int(item.get("image_index", 0))
                    segments.append(
                        {
                            "text": self._build_image_proxy_text(
                                filename=filename,
                                file_type="docx",
                                image_index=image_index,
                                asset_name=Path(asset_path).name,
                                anchor_text=str(item.get("anchor_text", "") or ""),
                                context_text="\n\n".join(context_parts),
                            ),
                            "metadata": {
                                "segment_index": image_index,
                                "segment_kind": "image_proxy",
                                "record_type": "image_proxy",
                                "image_index": image_index,
                                "asset_path": asset_path,
                            },
                        }
                    )
                return segments
        except KeyError as exc:
            raise ValueError("DOCX 文件缺少 word/document.xml") from exc

    def _extract_document_segments(self, file_content: BytesIO, filename: str) -> list[dict]:
        suffix = Path(filename).suffix.lower()
        file_content.seek(0)
        if suffix == ".pdf":
            return self._extract_pdf_segments(file_content, filename)
        if suffix in {".txt", ".md"}:
            return self._extract_plaintext_segments(file_content)
        if suffix == ".docx":
            return self._extract_docx_segments(file_content, filename)
        raise ValueError(f"Unsupported file type: {suffix or 'unknown'}")

    def _iter_fixed_chunks(self, text: str, chunk_size: int, overlap: int):
        step = max(1, chunk_size - overlap)
        if len(text) <= chunk_size:
            yield text
            return
        start = 0
        while start < len(text):
            chunk = text[start:start + chunk_size].strip()
            if chunk:
                yield chunk
            if start + chunk_size >= len(text):
                break
            start += step

    def _split_with_separator(self, text: str, separator: str) -> list[str]:
        if not separator or separator not in text:
            return [text]
        pieces = text.split(separator)
        results: list[str] = []
        for index, piece in enumerate(pieces):
            candidate = piece + separator if index < len(pieces) - 1 else piece
            candidate = candidate.strip()
            if candidate:
                results.append(candidate)
        return results or [text]

    def _recursive_split(self, text: str, chunk_size: int, separators: list[str]) -> list[str]:
        normalized = text.strip()
        if not normalized:
            return []
        if len(normalized) <= chunk_size:
            return [normalized]
        if not separators:
            return list(self._iter_fixed_chunks(normalized, chunk_size, self.chunk_overlap))

        separator = separators[0]
        pieces = self._split_with_separator(normalized, separator)
        if len(pieces) == 1:
            return self._recursive_split(normalized, chunk_size, separators[1:])

        final_chunks: list[str] = []
        buffer = ""
        for piece in pieces:
            candidate = f"{buffer}{piece}" if buffer else piece
            if len(candidate) <= chunk_size:
                buffer = candidate
                continue
            if buffer:
                final_chunks.extend(self._recursive_split(buffer, chunk_size, separators[1:]))
            buffer = piece

        if buffer:
            final_chunks.extend(self._recursive_split(buffer, chunk_size, separators[1:]))
        return final_chunks

    def _merge_with_overlap(self, pieces: list[str], chunk_size: int, overlap: int) -> list[str]:
        if not pieces:
            return []
        merged: list[str] = []
        current = ""
        for piece in pieces:
            piece = piece.strip()
            if not piece:
                continue
            candidate = f"{current}\n{piece}".strip() if current else piece
            if len(candidate) <= chunk_size:
                current = candidate
                continue
            if current:
                merged.append(current)
                carry = current[-overlap:].strip() if overlap > 0 else ""
                current = f"{carry}\n{piece}".strip() if carry else piece
            else:
                merged.append(piece)
                current = ""
        if current:
            merged.append(current)
        return merged

    def _iter_recursive_chunks(self, text: str, chunk_size: int, overlap: int):
        separators = ["\n\n", "\n", "。", "！", "？", "；", ".", "!", "?", ";", "，", ",", " "]
        pieces = self._recursive_split(text, chunk_size, separators)
        for chunk in self._merge_with_overlap(pieces, chunk_size, overlap):
            chunk_text = chunk.strip()
            if chunk_text:
                yield chunk_text

    def _iter_segment_chunks(self, segment: dict):
        text = str(segment.get("text", "")).strip()
        if not text:
            return
        metadata = dict(segment.get("metadata") or {})
        if self.chunk_strategy == "fixed":
            iterator = self._iter_fixed_chunks(text, self.chunk_size, self.chunk_overlap)
        else:
            iterator = self._iter_recursive_chunks(text, self.chunk_size, self.chunk_overlap)
        for chunk in iterator:
            chunk_text = chunk.strip()
            if chunk_text:
                yield metadata, chunk_text

    def _delete_existing_source(self, filename: str):
        asset_dir = self._source_asset_dir(filename)
        if asset_dir.exists():
            shutil.rmtree(asset_dir, ignore_errors=True)
        if self.backend == "chroma":
            self._ensure_chroma_connection()
            try:
                self.collection.delete(where={"source": filename})
            except Exception:
                LOGGER.exception("Failed to delete existing source from chroma: %s", filename)
        else:
            self.records = [
                item for item in self.records if item.get("metadata", {}).get("source") != filename
            ]

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
            file_content.seek(0)
            segments = self._extract_document_segments(file_content, filename)
            file_usage = {"input_tokens": 0, "total_tokens": 0}
            batch_ids = []
            batch_chunks = []
            batch_metadatas = []
            total_chunks = 0
            file_type = Path(filename).suffix.lower().lstrip(".") or "unknown"
            self._delete_existing_source(filename)

            for segment in segments:
                for segment_metadata, chunk in self._iter_segment_chunks(segment):
                    chunk_text = chunk.strip()
                    if not chunk_text:
                        continue
                    batch_ids.append(f"{filename}_{total_chunks}")
                    batch_chunks.append(chunk_text)
                    metadata = {
                        "source": filename,
                        "file_type": file_type,
                        "chunk_index": total_chunks,
                    }
                    metadata.update(segment_metadata)
                    batch_metadatas.append(metadata)
                    total_chunks += 1

                    if len(batch_chunks) >= self.embed_batch_size:
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
                f"Processed {filename}: generated {total_chunks} chunks with `{self.chunk_strategy}` strategy. "
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
                            "file_type": meta.get("file_type", "unknown"),
                            "page_index": meta.get("page_index"),
                            "segment_kind": meta.get("segment_kind"),
                            "chunk_index": meta.get("chunk_index"),
                            "record_type": meta.get("record_type", "text"),
                            "asset_path": meta.get("asset_path"),
                            "image_index": meta.get("image_index"),
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
                "file_type": item["metadata"].get("file_type", "unknown"),
                "page_index": item["metadata"].get("page_index"),
                "segment_kind": item["metadata"].get("segment_kind"),
                "chunk_index": item["metadata"].get("chunk_index"),
                "record_type": item["metadata"].get("record_type", "text"),
                "asset_path": item["metadata"].get("asset_path"),
                "image_index": item["metadata"].get("image_index"),
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
