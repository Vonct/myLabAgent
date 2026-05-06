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
            "generated_images": [],
            "compacted_summary": "",
            "compacted_until_message_count": 0,
            "compactions": [],
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
        payload.setdefault("generated_images", [])
        payload.setdefault("compacted_summary", "")
        payload.setdefault("compacted_until_message_count", 0)
        payload.setdefault("compactions", [])
        payload["messages"].append(message)
        payload["updated_at"] = _utc_now()
        self._write_session(payload)

    def start_task(self, session_id: str, prompt: str) -> TaskRecord:
        payload = self.load_session(session_id)
        if payload is None:
            payload = self.create_session()
        payload.setdefault("memories", [])
        payload.setdefault("generated_images", [])
        payload.setdefault("compacted_summary", "")
        payload.setdefault("compacted_until_message_count", 0)
        payload.setdefault("compactions", [])
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
        payload.setdefault("generated_images", [])
        payload.setdefault("compacted_summary", "")
        payload.setdefault("compacted_until_message_count", 0)
        payload.setdefault("compactions", [])
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
        payload.setdefault("generated_images", [])
        payload.setdefault("compacted_summary", "")
        payload.setdefault("compacted_until_message_count", 0)
        payload.setdefault("compactions", [])
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
        payload.setdefault("generated_images", [])
        payload.setdefault("compacted_summary", "")
        payload.setdefault("compacted_until_message_count", 0)
        payload.setdefault("compactions", [])
        payload["memories"].append(memory)
        payload["updated_at"] = _utc_now()
        self._write_session(payload)

    def append_generated_image(self, session_id: str, image_asset: dict[str, Any]) -> None:
        payload = self.load_session(session_id)
        if payload is None:
            return
        payload.setdefault("memories", [])
        payload.setdefault("generated_images", [])
        payload.setdefault("compacted_summary", "")
        payload.setdefault("compacted_until_message_count", 0)
        payload.setdefault("compactions", [])
        stored_asset = {
            key: value
            for key, value in image_asset.items()
            if key not in {"image_url", "data_url"}
        }
        stored_asset.setdefault("created_at", _utc_now())
        payload["generated_images"].append(stored_asset)
        payload["updated_at"] = _utc_now()
        self._write_session(payload)

    def get_latest_generated_image(self, session_id: str) -> dict[str, Any] | None:
        payload = self.load_session(session_id)
        if payload is None:
            return None
        images = payload.get("generated_images", [])
        if not isinstance(images, list) or not images:
            return None
        for image_asset in reversed(images):
            if isinstance(image_asset, dict):
                return image_asset
        return None

    def get_context_compaction(self, session_id: str) -> dict[str, Any]:
        payload = self.load_session(session_id) or {}
        return {
            "summary": str(payload.get("compacted_summary", "") or ""),
            "until_message_count": int(payload.get("compacted_until_message_count", 0) or 0),
            "compactions": payload.get("compactions", []) if isinstance(payload.get("compactions", []), list) else [],
        }

    def archive_messages(self, session_id: str, messages: list[dict[str, Any]], *, reason: str) -> str:
        archive_dir = self.root.parent / "transcripts" / session_id
        archive_dir.mkdir(parents=True, exist_ok=True)
        stamp = _utc_now().replace(":", "").replace("+", "_").replace(".", "_")
        archive_path = archive_dir / f"{reason}_{stamp}.jsonl"
        with open(archive_path, "w", encoding="utf-8") as f:
            for message in messages:
                f.write(json.dumps(message, ensure_ascii=False) + "\n")
        return str(archive_path)

    def save_context_compaction(
        self,
        session_id: str,
        *,
        summary: str,
        until_message_count: int,
        archive_path: str,
    ) -> None:
        payload = self.load_session(session_id)
        if payload is None:
            return
        payload.setdefault("memories", [])
        payload.setdefault("generated_images", [])
        payload.setdefault("compactions", [])
        payload["compacted_summary"] = summary
        payload["compacted_until_message_count"] = max(0, int(until_message_count))
        payload["compactions"].append(
            {
                "created_at": _utc_now(),
                "until_message_count": payload["compacted_until_message_count"],
                "archive_path": archive_path,
            }
        )
        payload["updated_at"] = _utc_now()
        self._write_session(payload)

    def _write_session(self, payload: dict[str, Any]) -> None:
        payload.setdefault("memories", [])
        payload.setdefault("generated_images", [])
        payload.setdefault("compacted_summary", "")
        payload.setdefault("compacted_until_message_count", 0)
        payload.setdefault("compactions", [])
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
