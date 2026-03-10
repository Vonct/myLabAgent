from __future__ import annotations

from pathlib import Path


def load_prompt(path: Path) -> str:
    with open(path, "r", encoding="utf-8-sig") as f:
        return f.read().strip()
