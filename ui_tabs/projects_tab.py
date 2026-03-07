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
    cols = st.columns(2)
    for i, project in enumerate(projects):
        with cols[i % 2]:
            with st.container(border=True):
                st.subheader(project["title"])
                cover = project.get("cover_image")
                if cover:
                    cover_path = project_catalog_dir / cover
                    if cover_path.exists():
                        st.image(str(cover_path), width="stretch")
                st.write(project["summary"])
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
