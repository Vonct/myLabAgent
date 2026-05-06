"""Shared config helpers for LangChain / LangGraph demos."""

from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOTENV_PATH = PROJECT_ROOT / ".env"


def load_dotenv_if_exists(path: Path = DOTENV_PATH) -> None:
    """Load simple KEY=VALUE lines from .env without adding a dependency.

    This is intentionally tiny and good enough for local learning demos.
    Existing environment variables win over .env values.
    """
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        if key:
            os.environ.setdefault(key, value)


def env_bool(name: str) -> bool | None:
    value = os.getenv(name)
    if value is None:
        return None
    return value.lower() in {"1", "true", "yes", "on"}

