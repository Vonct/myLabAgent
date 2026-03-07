import argparse
import json
from pathlib import Path


def build_markdown(project: dict) -> str:
    lines = []
    lines.append(f"# {project.get('title', '项目介绍')}")
    lines.append("")
    lines.append(f"**分类**: {project.get('category', '未分类')}")
    lines.append("")
    lines.append(f"**摘要**: {project.get('summary', '')}")
    lines.append("")
    kws = project.get("keywords", [])
    if kws:
        lines.append(f"**关键词**: {', '.join(kws)}")
        lines.append("")
    cover = project.get("cover_image")
    if cover:
        lines.append("## 封面图")
        lines.append("")
        lines.append(f"![cover]({cover})")
        lines.append("")
    detail = project.get("detail", {})
    if detail:
        lines.append("## 项目详情")
        lines.append("")
        if detail.get("background"):
            lines.append(f"- 背景：{detail['background']}")
        if detail.get("method"):
            lines.append(f"- 方法：{detail['method']}")
        if detail.get("result"):
            lines.append(f"- 结果：{detail['result']}")
        lines.append("")
    lines.append("## 幻灯片内容")
    lines.append("")
    for section in project.get("sections", []):
        lines.append(f"### Slide {section.get('slide')} - {section.get('heading', '')}")
        lines.append("")
        for img in section.get("images", []):
            lines.append(f"![slide-{section.get('slide')} image]({img})")
            lines.append("")
        for item in section.get("details", []):
            lines.append(f"- {item}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-json", required=True)
    parser.add_argument("--output-md", required=True)
    args = parser.parse_args()
    project_json = Path(args.project_json)
    output_md = Path(args.output_md)
    with open(project_json, "r", encoding="utf-8") as f:
        project = json.load(f)
    md = build_markdown(project)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    with open(output_md, "w", encoding="utf-8") as f:
        f.write(md)
    print(str(output_md))


if __name__ == "__main__":
    main()
