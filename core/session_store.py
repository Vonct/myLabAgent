from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _date_dir_from_created_at(created_at: str) -> str:
    dt = _parse_iso_datetime(created_at) or datetime.now(timezone.utc)
    return dt.strftime("%Y_%m_%d")


@dataclass
class TaskRecord:
    task_id: str
    prompt: str
    status: str = "running"
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)
    tool_events: list[dict[str, Any]] = field(default_factory=list)
    result: str = ""


class SessionStore:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def create_session(self) -> dict[str, Any]:
        session_id = uuid4().hex
        payload = {
            "session_id": session_id,
            "created_at": _utc_now(),
            "updated_at": _utc_now(),
            "messages": [],
            "tasks": [],
            "memories": [],
        }
        self._write_session(payload)
        return payload

    def load_session(self, session_id: str) -> dict[str, Any] | None:
        path = self._resolve_session_path(session_id)
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def append_message(self, session_id: str, message: dict[str, Any]) -> None:
        payload = self.load_session(session_id)
        if payload is None:
            return
        payload.setdefault("memories", [])
        payload["messages"].append(message)
        payload["updated_at"] = _utc_now()
        self._write_session(payload)

    def start_task(self, session_id: str, prompt: str) -> TaskRecord:
        payload = self.load_session(session_id)
        if payload is None:
            payload = self.create_session()
        payload.setdefault("memories", [])
        task = TaskRecord(task_id=uuid4().hex, prompt=prompt)
        payload["tasks"].append(task.__dict__)
        payload["updated_at"] = _utc_now()
        self._write_session(payload)
        return task

    def append_tool_event(self, session_id: str, task_id: str, event: dict[str, Any]) -> None:
        payload = self.load_session(session_id)
        if payload is None:
            return
        payload.setdefault("memories", [])
        for task in payload["tasks"]:
            if task["task_id"] == task_id:
                task["tool_events"].append(event)
                task["updated_at"] = _utc_now()
                break
        payload["updated_at"] = _utc_now()
        self._write_session(payload)

    def finish_task(self, session_id: str, task_id: str, result: str, status: str = "completed") -> None:
        payload = self.load_session(session_id)
        if payload is None:
            return
        payload.setdefault("memories", [])
        for task in payload["tasks"]:
            if task["task_id"] == task_id:
                task["status"] = status
                task["result"] = result
                task["updated_at"] = _utc_now()
                break
        payload["updated_at"] = _utc_now()
        self._write_session(payload)

    def get_task(self, session_id: str, task_id: str) -> dict[str, Any] | None:
        payload = self.load_session(session_id)
        if payload is None:
            return None
        for task in payload.get("tasks", []):
            if task.get("task_id") == task_id:
                return task
        return None

    def append_memory(self, session_id: str, memory: dict[str, Any]) -> None:
        payload = self.load_session(session_id)
        if payload is None:
            return
        payload.setdefault("memories", [])
        payload["memories"].append(memory)
        payload["updated_at"] = _utc_now()
        self._write_session(payload)

    def _write_session(self, payload: dict[str, Any]) -> None:
        payload.setdefault("memories", [])
        path = self._resolve_session_path(
            payload["session_id"],
            created_at=payload.get("created_at", ""),
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def _resolve_session_path(self, session_id: str, created_at: str | None = None) -> Path:
        legacy = self.root / f"{session_id}.json"
        if legacy.exists():
            return legacy
        for path in self.root.glob(f"**/{session_id}.json"):
            if path.is_file():
                return path
        date_dir = _date_dir_from_created_at(created_at or "")
        return self.root / date_dir / f"{session_id}.json"

    def list_session_paths(self) -> list[Path]:
        return sorted(
            [path for path in self.root.glob("**/*.json") if path.is_file()],
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )

    def migrate_sessions_by_created_date(self) -> int:
        moved = 0
        for path in self.root.glob("*.json"):
            if not path.is_file():
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
            except Exception:
                continue
            session_id = str(payload.get("session_id", "")).strip() or path.stem
            target = self.root / _date_dir_from_created_at(str(payload.get("created_at", ""))) / f"{session_id}.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.resolve() == path.resolve():
                continue
            if target.exists():
                path.unlink()
            else:
                path.rename(target)
            moved += 1
        return moved
