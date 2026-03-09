import base64
import html
import json
import re
from pathlib import Path

import streamlit as st


@st.cache_data(show_spinner=False)
def load_projects(project_index_file: Path, projects_dir: Path):
    if not project_index_file.exists():
        return []
    with open(project_index_file, "r", encoding="utf-8") as f:
        index_data = json.load(f)
    project_meta = index_data.get("projects", []) if isinstance(index_data, dict) else []
    projects = []
    for meta in project_meta:
        if not meta.get("enabled", True):
            continue
        project_id = meta.get("id")
        if not project_id:
            continue
        project_file = projects_dir / f"{project_id}.json"
        if not project_file.exists():
            continue
        with open(project_file, "r", encoding="utf-8") as pf:
            project = json.load(pf)
        project["category"] = meta.get("category", project.get("category", "未分类"))
        project["display_order"] = meta.get("display_order", 9999)
        projects.append(project)
    projects.sort(key=lambda x: (x.get("display_order", 9999), x.get("title", "")))
    return projects


def get_project_markdown_path(project: dict, project_catalog_dir: Path):
    source = project.get("source", {})
    source_file = source.get("file")
    if source_file:
        candidate = project_catalog_dir / f"{Path(source_file).stem}.md"
        if candidate.exists():
            return candidate
    candidate = project_catalog_dir / f"{project.get('id', '')}.md"
    if candidate.exists():
        return candidate
    return None


def render_markdown_with_local_images(md_path: Path, project_catalog_dir: Path):
    with open(md_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    image_pattern = re.compile(r"^!\[[^\]]*\]\(([^)]+)\)\s*$")
    buffer = []
    for raw in lines:
        line = raw.rstrip("\n")
        match = image_pattern.match(line.strip())
        if match:
            if buffer:
                st.markdown("\n".join(buffer))
                buffer = []
            rel_path = match.group(1)
            img_path = project_catalog_dir / rel_path
            if img_path.exists():
                _, image_col, _ = st.columns([1.2, 4.6, 1.2])
                with image_col:
                    st.image(str(img_path), width="stretch")
            else:
                st.markdown(line)
        else:
            buffer.append(line)
    if buffer:
        st.markdown("\n".join(buffer))


@st.cache_data(show_spinner=False)
def _read_image_base64(image_path: str):
    path = Path(image_path)
    if not path.exists():
        return None
    ext_to_mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }
    mime = ext_to_mime.get(path.suffix.lower())
    if not mime:
        return None
    data = base64.b64encode(path.read_bytes()).decode("utf-8")
    return f"data:{mime};base64,{data}"


def _render_cover_image(cover_path: Path):
    data_uri = _read_image_base64(str(cover_path))
    if data_uri:
        st.markdown(
            f'<div class="project-cover"><img src="{data_uri}" alt="project cover"></div>',
            unsafe_allow_html=True,
        )
        return
    st.markdown('<div class="project-cover project-cover-fallback">暂无封面</div>', unsafe_allow_html=True)


def render_projects_tab(project_catalog_dir: Path, project_index_file: Path, projects_dir: Path):
    col1, col2 = st.columns([5, 1])
    with col1:
        st.title("🧪 项目介绍")
    with col2:
        if st.button("🔄 刷新", key="refresh_projects"):
            load_projects.clear()
            st.rerun()
    st.caption("项目数据来自后端持久化目录，点击卡片查看详情。")
    projects = load_projects(project_index_file, projects_dir)
    if not projects:
        st.info("未找到项目目录数据。请先执行离线解析脚本生成 project_catalog。")
        return
    st.markdown(
        """
<style>
.project-title{font-size:1.1rem;font-weight:700;line-height:1.35;min-height:2.6em;display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;overflow:hidden}
.project-cover{width:100%;height:160px;border-radius:12px;overflow:hidden;background:#f3f5f7;display:flex;align-items:center;justify-content:center}
.project-cover img{width:100%;height:100%;object-fit:contain;background:#f3f5f7}
.project-cover-fallback{color:#7a7a7a;font-size:.9rem}
.project-summary{line-height:1.5;min-height:3.2em;display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;overflow:hidden}
</style>
        """,
        unsafe_allow_html=True,
    )
    cols = st.columns(2)
    for i, project in enumerate(projects):
        with cols[i % 2]:
            with st.container(border=True):
                safe_title = html.escape(project["title"])
                st.markdown(f'<div class="project-title">{safe_title}</div>', unsafe_allow_html=True)
                cover = project.get("cover_image")
                if cover:
                    cover_path = project_catalog_dir / cover
                    if cover_path.exists():
                        _render_cover_image(cover_path)
                    else:
                        st.markdown('<div class="project-cover project-cover-fallback">暂无封面</div>', unsafe_allow_html=True)
                else:
                    st.markdown('<div class="project-cover project-cover-fallback">暂无封面</div>', unsafe_allow_html=True)
                safe_summary = html.escape(project["summary"])
                st.markdown(f'<div class="project-summary">{safe_summary}</div>', unsafe_allow_html=True)
                st.caption(f"分类：{project.get('category', '未分类')}")
                keyword_text = " / ".join(project["keywords"]) if project["keywords"] else "暂无关键词"
                st.caption(f"关键词：{keyword_text}")
                if st.button("查看详情", key=f"open_project_{project['id']}"):
                    st.session_state.selected_project_id = project["id"]
    selected = None
    if st.session_state.selected_project_id:
        selected = next((p for p in projects if p["id"] == st.session_state.selected_project_id), None)
    if not selected:
        return
    st.markdown("---")
    st.subheader(f"📘 {selected['title']}")
    md_path = get_project_markdown_path(selected, project_catalog_dir)
    if md_path:
        render_markdown_with_local_images(md_path, project_catalog_dir)
        return
    detail = selected.get("detail", {})
    if detail.get("background"):
        st.markdown("**项目背景**")
        st.write(detail["background"])
    if detail.get("method"):
        st.markdown("**核心方法**")
        st.write(detail["method"])
    if detail.get("result"):
        st.markdown("**实验结果**")
        st.write(detail["result"])
    highlights = detail.get("highlights", [])
    if highlights:
        st.markdown("**关键亮点**")
        for h in highlights:
            st.write(f"- {h}")
    for section in selected["sections"]:
        with st.expander(f"Slide {section['slide']} · {section['heading']}", expanded=False):
            images = section.get("images", [])
            for img in images:
                img_path = project_catalog_dir / img
                if img_path.exists():
                    st.image(str(img_path), width="stretch")
            if section["details"]:
                for line in section["details"]:
                    st.write(f"- {line}")
            else:
                st.write("该页仅包含标题信息。")
