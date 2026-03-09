from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
        }
        self._write_session(payload)
        return payload

    def load_session(self, session_id: str) -> dict[str, Any] | None:
        path = self.root / f"{session_id}.json"
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def append_message(self, session_id: str, message: dict[str, Any]) -> None:
        payload = self.load_session(session_id)
        if payload is None:
            return
        payload["messages"].append(message)
        payload["updated_at"] = _utc_now()
        self._write_session(payload)

    def start_task(self, session_id: str, prompt: str) -> TaskRecord:
        payload = self.load_session(session_id)
        if payload is None:
            payload = self.create_session()
        task = TaskRecord(task_id=uuid4().hex, prompt=prompt)
        payload["tasks"].append(task.__dict__)
        payload["updated_at"] = _utc_now()
        self._write_session(payload)
        return task

    def append_tool_event(self, session_id: str, task_id: str, event: dict[str, Any]) -> None:
        payload = self.load_session(session_id)
        if payload is None:
            return
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
        for task in payload["tasks"]:
            if task["task_id"] == task_id:
                task["status"] = status
                task["result"] = result
                task["updated_at"] = _utc_now()
                break
        payload["updated_at"] = _utc_now()
        self._write_session(payload)

    def _write_session(self, payload: dict[str, Any]) -> None:
        path = self.root / f"{payload['session_id']}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
