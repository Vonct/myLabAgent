import argparse
import json
import re
import shutil
import zipfile
from collections import Counter
from pathlib import Path
import xml.etree.ElementTree as ET


def parse_pptx_content(pptx_path: Path):
    ns = {
        "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
        "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
        "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    }
    slides = []
    with zipfile.ZipFile(pptx_path, "r") as zf:
        presentation_xml = ET.fromstring(zf.read("ppt/presentation.xml"))
        rels_xml = ET.fromstring(zf.read("ppt/_rels/presentation.xml.rels"))
        rid_to_target = {}
        for rel in rels_xml:
            rid = rel.attrib.get("Id")
            target = rel.attrib.get("Target", "")
            if rid and target:
                rid_to_target[rid] = target
        slide_refs = presentation_xml.findall(".//p:sldId", ns)
        for i, sld in enumerate(slide_refs, start=1):
            rid = sld.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
            target = rid_to_target.get(rid, "")
            if not target:
                continue
            target = target.lstrip("/")
            if target.startswith("slides/"):
                xml_path = f"ppt/{target}"
            elif target.startswith("ppt/"):
                xml_path = target
            else:
                xml_path = f"ppt/{target}"
            if xml_path not in zf.namelist():
                continue
            slide_xml = ET.fromstring(zf.read(xml_path))
            texts = [t.text.strip() for t in slide_xml.findall(".//a:t", ns) if t.text and t.text.strip()]
            rel_xml_path = f"ppt/slides/_rels/{Path(xml_path).name}.rels"
            rel_map = {}
            if rel_xml_path in zf.namelist():
                rels_for_slide = ET.fromstring(zf.read(rel_xml_path))
                for rel in rels_for_slide:
                    rel_id = rel.attrib.get("Id")
                    rel_target = rel.attrib.get("Target", "")
                    rel_type = rel.attrib.get("Type", "")
                    if rel_id and rel_target and rel_type.endswith("/image"):
                        normalized = rel_target.replace("\\", "/")
                        if normalized.startswith("../"):
                            normalized = f"ppt/{normalized[3:]}"
                        elif normalized.startswith("/"):
                            normalized = normalized.lstrip("/")
                        elif not normalized.startswith("ppt/"):
                            normalized = f"ppt/slides/{normalized}"
                        rel_map[rel_id] = normalized
            embeds = []
            for node in slide_xml.findall(".//a:blip", ns):
                rid = node.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed")
                if rid and rid in rel_map:
                    embeds.append(rel_map[rid])
            slide_images = []
            seen = set()
            for e in embeds:
                if e not in seen:
                    seen.add(e)
                    slide_images.append(e)
            if texts or slide_images:
                slides.append({"slide_index": i, "texts": texts, "media_refs": slide_images})
    return slides


def build_project(pptx_path: Path, project_id: str, category: str):
    slides = parse_pptx_content(pptx_path)
    if not slides:
        raise ValueError("PPT 中未提取到可用文本")
    title = slides[0]["texts"][0] if slides[0]["texts"] else pptx_path.stem
    summary = ""
    for slide in slides[1:] if len(slides) > 1 else slides:
        if len(slide["texts"]) > 1:
            summary = slide["texts"][1]
            break
    if not summary:
        summary = slides[0]["texts"][1] if len(slides[0]["texts"]) > 1 else f"{title} 项目介绍"
    sections = []
    corpus = []
    for slide in slides:
        heading = slide["texts"][0] if slide["texts"] else f"Slide {slide['slide_index']}"
        details = slide["texts"][1:] if len(slide["texts"]) > 1 else []
        corpus.extend(slide["texts"])
        sections.append({
            "heading": heading,
            "details": details,
            "slide": slide["slide_index"],
            "media_refs": slide.get("media_refs", [])
        })
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9\-\+]{2,}", " ".join(corpus))
    stop = {"THE", "AND", "FOR", "WITH", "FROM", "THIS", "THAT", "MODEL", "RESULT", "SYSTEM"}
    freq = Counter([t.upper() for t in tokens if t.upper() not in stop])
    keywords = [k for k, _ in freq.most_common(8)]
    detail = {
        "background": sections[1]["details"][0] if len(sections) > 1 and sections[1]["details"] else summary,
        "method": sections[2]["details"][0] if len(sections) > 2 and sections[2]["details"] else "",
        "result": sections[-1]["details"][0] if sections and sections[-1]["details"] else "",
        "highlights": [s["heading"] for s in sections[1:6]]
    }
    return {
        "id": project_id,
        "title": title,
        "summary": summary,
        "category": category,
        "keywords": keywords,
        "source": {
            "file": pptx_path.name,
            "slides": [s["slide_index"] for s in slides]
        },
        "detail": detail,
        "sections": sections
    }


def save_catalog(catalog_dir: Path, project: dict, category: str, display_order: int, pptx_path: Path):
    projects_dir = catalog_dir / "projects"
    media_dir = catalog_dir / "media" / project["id"]
    projects_dir.mkdir(parents=True, exist_ok=True)
    media_dir.mkdir(parents=True, exist_ok=True)
    if media_dir.exists():
        for child in media_dir.iterdir():
            if child.is_file():
                child.unlink()
            elif child.is_dir():
                shutil.rmtree(child)
    media_map = {}
    with zipfile.ZipFile(pptx_path, "r") as zf:
        all_refs = []
        for section in project["sections"]:
            all_refs.extend(section.get("media_refs", []))
        unique_refs = []
        seen = set()
        for ref in all_refs:
            if ref not in seen:
                seen.add(ref)
                unique_refs.append(ref)
        for idx, ref in enumerate(unique_refs, start=1):
            if ref not in zf.namelist():
                continue
            ext = Path(ref).suffix or ".png"
            name = f"img_{idx:03d}{ext}"
            target = media_dir / name
            with open(target, "wb") as out:
                out.write(zf.read(ref))
            media_map[ref] = f"media/{project['id']}/{name}"
    for section in project["sections"]:
        refs = section.pop("media_refs", [])
        section["images"] = [media_map[r] for r in refs if r in media_map]
    cover = None
    for section in project["sections"]:
        if section["images"]:
            cover = section["images"][0]
            break
    project["cover_image"] = cover
    project_file = projects_dir / f"{project['id']}.json"
    with open(project_file, "w", encoding="utf-8") as f:
        json.dump(project, f, ensure_ascii=False, indent=2)
    index_file = catalog_dir / "index.json"
    if index_file.exists():
        with open(index_file, "r", encoding="utf-8") as f:
            index_data = json.load(f)
    else:
        index_data = {"projects": []}
    projects = index_data.get("projects", [])
    projects = [p for p in projects if p.get("id") != project["id"]]
    projects.append({
        "id": project["id"],
        "category": category,
        "display_order": display_order,
        "enabled": True
    })
    projects.sort(key=lambda x: x.get("display_order", 9999))
    index_data["projects"] = projects
    with open(index_file, "w", encoding="utf-8") as f:
        json.dump(index_data, f, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pptx", required=True)
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--category", default="未分类")
    parser.add_argument("--display-order", type=int, default=1)
    args = parser.parse_args()
    pptx_path = Path(args.pptx)
    catalog_dir = Path(args.catalog)
    project = build_project(pptx_path, args.project_id, args.category)
    save_catalog(catalog_dir, project, args.category, args.display_order, pptx_path)
    print(f"saved:{project['id']}")


if __name__ == "__main__":
    main()
