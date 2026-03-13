from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SkillInfo:
    name: str
    description: str
    location: Path
    content: str

    @property
    def directory(self) -> Path:
        return self.location.parent


class SkillLoader:
    """Discovers lightweight prompt skills from a local skills directory."""

    def __init__(self, root: Path):
        self.root = root
        self._skills = self._discover() # e.g. {'skill_name': SkillInfo}

    def _discover(self) -> dict[str, SkillInfo]:
        skills: dict[str, SkillInfo] = {}
        if not self.root.exists():
            return skills

        for skill_file in sorted(self.root.glob('*/SKILL.md')):
            parsed = self._parse_skill(skill_file) # SkillInfo
            if parsed is None:
                continue
            skills[parsed.name] = parsed
        return skills

    def _parse_skill(self, skill_file: Path) -> SkillInfo | None:
        raw = skill_file.read_text(encoding='utf-8')
        frontmatter, content = self._split_frontmatter(raw)
        if frontmatter is None:
            return None

        name = frontmatter.get('name', '').strip()
        description = frontmatter.get('description', '').strip()
        if not name or not description:
            return None

        return SkillInfo(
            name=name,
            description=description,
            location=skill_file,
            content=content.strip(),
        )

    def _split_frontmatter(self, raw: str) -> tuple[dict[str, str] | None, str]:
        if not raw.startswith('---'):
            return None, raw

        parts = raw.split('---', 2)
        if len(parts) < 3:
            return None, raw

        _, header, body = parts
        data: dict[str, str] = {}
        for line in header.splitlines():
            line = line.strip()
            if not line or ':' not in line:
                continue
            key, value = line.split(':', 1)
            data[key.strip()] = value.strip().strip('"').strip("'")
        return data, body.lstrip('\r\n')

    def all(self) -> list[SkillInfo]:
        return list(self._skills.values())

    def get(self, name: str) -> SkillInfo | None:
        return self._skills.get(name)

    def build_tool_description(self) -> str:
        skills = self.all()
        if not skills:
            return 'Load a specialized local skill when the task matches a reusable workflow. No skills are currently available.'

        lines = [
            'Load a specialized local skill when the task matches a reusable workflow.',
            '',
            'Use this tool only when one of the available skills is clearly relevant.',
            'The tool loads the full SKILL.md content on demand instead of injecting every skill into the prompt upfront.',
            '',
            '<available_skills>',
        ]
        for skill in skills:
            lines.extend(
                [
                    '  <skill>',
                    f'    <name>{skill.name}</name>',
                    f'    <description>{skill.description}</description>',
                    f'    <location>{skill.location}</location>',
                    '  </skill>',
                ]
            )
        lines.append('</available_skills>')
        return '\n'.join(lines)

    # 返回skill正文
    def render_skill_content(self, name: str) -> str:
        skill = self.get(name)
        if skill is None:
            available = ', '.join(item.name for item in self.all()) or 'none'
            return f'{{"error": "Skill `{name}` not found. Available skills: {available}"}}'

        files: list[str] = []
        for path in sorted(skill.directory.rglob('*')):
            if path.is_dir() or path.name == 'SKILL.md':
                continue
            files.append(str(path))
            if len(files) >= 10:
                break

        file_block = '\n'.join(f'<file>{item}</file>' for item in files)
        return '\n'.join(
            [
                f'<skill_content name="{skill.name}">',
                f'# Skill: {skill.name}',
                '',
                skill.content,
                '',
                f'Base directory: {skill.directory}',
                'Relative paths mentioned by this skill are relative to the base directory above.',
                'Bundled files are listed as references only and are not executed automatically.',
                '',
                '<skill_files>',
                file_block,
                '</skill_files>',
                '</skill_content>',
            ]
        )
