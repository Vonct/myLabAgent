import hashlib
import html
import json
import shutil
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import streamlit as st


def _document_id(path: Path) -> str:
    return hashlib.sha1(str(path.resolve()).encode("utf-8")).hexdigest()[:16]


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {"_metadata_error": f"{path.name} 解析失败"}


def _normalize_tags(value) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


@st.cache_data(show_spinner=False)
def discover_documents(source_dirs: tuple[str, ...]):
    documents = []
    seen_paths = set()
    for raw_dir in source_dirs:
        root = Path(raw_dir).expanduser()
        if not root.exists() or not root.is_dir():
            continue
        for pdf_path in sorted(root.rglob("*.pdf")):
            resolved_path = pdf_path.resolve()
            if resolved_path in seen_paths:
                continue
            seen_paths.add(resolved_path)
            stat = pdf_path.stat()
            metadata_path = pdf_path.with_suffix(".json")
            metadata = _read_json(metadata_path)
            title = str(metadata.get("title") or metadata.get("name") or pdf_path.stem)
            description = str(metadata.get("description") or metadata.get("summary") or "")
            tags = _normalize_tags(metadata.get("tags") or metadata.get("keywords"))
            updated_at = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
            documents.append(
                {
                    "id": _document_id(pdf_path),
                    "title": title,
                    "description": description,
                    "tags": tags,
                    "category": str(metadata.get("category") or "未分类"),
                    "pdf_path": str(pdf_path),
                    "metadata_path": str(metadata_path) if metadata_path.exists() else "",
                    "metadata": metadata,
                    "updated_at": updated_at,
                    "size": stat.st_size,
                    "source_dir": str(root),
                }
            )
    documents.sort(key=lambda item: (item["category"], item["title"]))
    return documents


def _static_pdf_url(pdf_path: str, document_id: str, updated_at: str, size: int):
    source = Path(pdf_path)
    if not source.exists():
        return ""
    static_dir = Path(__file__).resolve().parents[1] / "static" / "documents"
    static_dir.mkdir(parents=True, exist_ok=True)
    target_name = f"{document_id}{source.suffix.lower()}"
    target = static_dir / target_name
    if not target.exists() or target.stat().st_size != size:
        shutil.copy2(source, target)
    return f"/app/static/documents/{quote(target_name)}"


@st.cache_data(show_spinner=False)
def _pdf_page_count(pdf_path: str, updated_at: str, size: int) -> int:
    try:
        import pypdfium2 as pdfium
    except ImportError:
        return 0
    pdf = pdfium.PdfDocument(pdf_path)
    return len(pdf)


@st.cache_data(show_spinner=False)
def _render_pdf_page_png(pdf_path: str, updated_at: str, size: int, page_index: int, zoom: float) -> bytes:
    import pypdfium2 as pdfium
    from io import BytesIO

    pdf = pdfium.PdfDocument(pdf_path)
    page = pdf[page_index]
    bitmap = page.render(scale=zoom)
    image = bitmap.to_pil()
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _render_pdf(document: dict):
    pdf_url = _static_pdf_url(
        document["pdf_path"],
        document["id"],
        document["updated_at"],
        document["size"],
    )
    if not pdf_url:
        st.error("PDF 文件不存在或无法读取。")
        return
    page_count = _pdf_page_count(document["pdf_path"], document["updated_at"], document["size"])
    if page_count <= 0:
        safe_url = html.escape(pdf_url, quote=True)
        st.warning("当前环境缺少 pypdfium2，无法生成在线预览。可以先下载或新窗口打开 PDF。")
        st.markdown(f"[新窗口打开 PDF]({safe_url})")
        return

    page_key = f"document_page_{document['id']}"
    if page_key not in st.session_state:
        st.session_state[page_key] = 1
    st.session_state[page_key] = min(max(int(st.session_state[page_key]), 1), page_count)
    current_page = st.session_state[page_key]

    page_png = _render_pdf_page_png(
        document["pdf_path"],
        document["updated_at"],
        document["size"],
        current_page - 1,
        1.8,
    )
    st.image(page_png, width="stretch")
    st.caption(f"第 {current_page} / {page_count} 页")

    control_cols = st.columns([1, 1, 2, 5])
    with control_cols[0]:
        if st.button("上一页", key=f"prev_{document['id']}", disabled=current_page <= 1):
            st.session_state[page_key] = current_page - 1
            st.rerun()
    with control_cols[1]:
        if st.button("下一页", key=f"next_{document['id']}", disabled=current_page >= page_count):
            st.session_state[page_key] = current_page + 1
            st.rerun()
    with control_cols[2]:
        st.number_input(
            "页码",
            min_value=1,
            max_value=page_count,
            step=1,
            key=page_key,
        )
    with control_cols[3]:
        safe_url = html.escape(pdf_url, quote=True)
        st.markdown(
            f'<div style="padding-top:2.1rem;"><a href="{safe_url}" target="_blank">新窗口打开原始 PDF</a></div>',
            unsafe_allow_html=True,
        )


def render_doc_reader_tab(source_dirs: list[Path]):
    col_title, col_action = st.columns([5, 1])
    with col_title:
        st.title("文档阅读")
    with col_action:
        if st.button("刷新", key="refresh_documents"):
            discover_documents.clear()
            st.rerun()

    st.caption("扫描配置目录中的 PDF，并自动读取同名 JSON 作为描述信息。")
    source_dir_strings = tuple(str(path) for path in source_dirs)
    documents = discover_documents(source_dir_strings)
    if not documents:
        st.info("未找到 PDF 文档。可以把 PDF 放入 document_catalog，或在 app.py 中追加文档目录。")
        return

    all_tags = sorted({tag for doc in documents for tag in doc["tags"]})
    left_col, right_col = st.columns([1.2, 3.8])

    with left_col:
        query = st.text_input("搜索", key="document_search_query", placeholder="标题、描述、标签")
        tag_filter = st.selectbox("标签", ["全部"] + all_tags, key="document_tag_filter")

        filtered = []
        query_text = query.strip().lower()
        for doc in documents:
            haystack = " ".join(
                [
                    doc["title"],
                    doc["description"],
                    doc["category"],
                    " ".join(doc["tags"]),
                    Path(doc["pdf_path"]).name,
                ]
            ).lower()
            if query_text and query_text not in haystack:
                continue
            if tag_filter != "全部" and tag_filter not in doc["tags"]:
                continue
            filtered.append(doc)

        if not filtered:
            st.warning("没有匹配的文档。")
            return

        selected_id = st.session_state.get("selected_document_id")
        selected_index = next((i for i, doc in enumerate(filtered) if doc["id"] == selected_id), 0)
        docs_by_id = {doc["id"]: doc for doc in filtered}
        selected_doc_id = st.radio(
            "文档",
            [doc["id"] for doc in filtered],
            index=selected_index,
            format_func=lambda doc_id: docs_by_id[doc_id]["title"],
            key="document_selector",
        )
        selected_doc = docs_by_id[selected_doc_id]
        st.session_state.selected_document_id = selected_doc["id"]

        st.markdown("---")
        st.caption(f"共 {len(filtered)} / {len(documents)} 篇")
        st.caption(f"目录：{selected_doc['source_dir']}")

    with right_col:
        st.subheader(selected_doc["title"])
        meta_cols = st.columns(3)
        meta_cols[0].caption(f"分类：{selected_doc['category']}")
        meta_cols[1].caption(f"大小：{_format_size(selected_doc['size'])}")
        meta_cols[2].caption(f"更新：{selected_doc['updated_at']}")

        if selected_doc["tags"]:
            st.caption("标签：" + " / ".join(selected_doc["tags"]))
        if selected_doc["description"]:
            st.write(selected_doc["description"])
        elif not selected_doc["metadata_path"]:
            st.info("当前文档还没有同名 JSON 描述，页面已使用文件名作为标题。")

        if selected_doc["metadata"].get("_metadata_error"):
            st.warning(selected_doc["metadata"]["_metadata_error"])

        st.download_button(
            "下载 PDF",
            data=Path(selected_doc["pdf_path"]).read_bytes(),
            file_name=Path(selected_doc["pdf_path"]).name,
            mime="application/pdf",
            key=f"download_{selected_doc['id']}",
        )

        _render_pdf(selected_doc)
