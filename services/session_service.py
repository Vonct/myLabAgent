from __future__ import annotations

from pathlib import Path
from typing import Any

from core.session_store import SessionStore


class SessionService:
    def __init__(self, store: SessionStore):
        self.store = store

    def create_or_resume_session(self, session_id: str | None = None) -> dict[str, Any]:
        if session_id:
            payload = self.store.load_session(session_id)
            if payload is not None:
                return payload
        return self.store.create_session()

    def get_messages(self, session_id: str) -> list[dict[str, Any]]:
        payload = self.store.load_session(session_id) or {}
        messages = payload.get('messages', [])
        return messages if isinstance(messages, list) else []

    def append_user_message(self, session_id: str, content: str) -> None:
        self.store.append_message(session_id, {'role': 'user', 'content': content})

    def append_assistant_message(self, session_id: str, content: str) -> None:
        self.store.append_message(session_id, {'role': 'assistant', 'content': content})

    def append_tool_message(
        self,
        session_id: str,
        *,
        tool_name: str,
        content: str,
        tool_call_id: str | None = None,
    ) -> None:
        message: dict[str, Any] = {'role': 'tool', 'name': tool_name, 'content': content}
        if tool_call_id:
            message['tool_call_id'] = tool_call_id
        self.store.append_message(session_id, message)

    def list_sessions(self, limit: int = 20) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for path in sorted(self.store.root.glob('*.json'), key=lambda item: item.stat().st_mtime, reverse=True):
            payload = self.store.load_session(path.stem)
            if payload is None:
                continue
            messages = payload.get('messages', [])
            preview = ''
            for message in messages:
                if message.get('role') == 'user' and str(message.get('content', '')).strip():
                    preview = str(message.get('content', '')).strip()
                    break
            records.append(
                {
                    'session_id': payload.get('session_id', path.stem),
                    'updated_at': payload.get('updated_at', ''),
                    'created_at': payload.get('created_at', ''),
                    'message_count': len(messages) if isinstance(messages, list) else 0,
                    'preview': preview[:80],
                    'path': str(Path(path)),
                }
            )
            if len(records) >= limit:
                break
        return records
