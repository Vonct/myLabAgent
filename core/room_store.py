from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RoomStore:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def create_room(self, name: str) -> dict[str, Any]:
        room_id = uuid4().hex
        payload = {
            'room_id': room_id,
            'name': name.strip() or 'Untitled room',
            'created_at': _utc_now(),
            'updated_at': _utc_now(),
            'messages': [],
            'agent_session_id': '',
            'compacted_summary': '',
        }
        self._write_room(payload)
        return payload

    def load_room(self, room_id: str) -> dict[str, Any] | None:
        path = self._room_path(room_id)
        if not path.exists():
            return None
        with open(path, 'r', encoding='utf-8') as f:
            payload = json.load(f)
        payload.setdefault('messages', [])
        payload.setdefault('agent_session_id', '')
        payload.setdefault('compacted_summary', '')
        return payload

    def list_rooms(self) -> list[dict[str, Any]]:
        rooms: list[dict[str, Any]] = []
        for path in sorted(self.root.glob('*.json'), key=lambda item: item.stat().st_mtime, reverse=True):
            payload = self.load_room(path.stem)
            if payload is None:
                continue
            messages = payload.get('messages', [])
            latest = messages[-1] if isinstance(messages, list) and messages else {}
            rooms.append(
                {
                    'room_id': payload.get('room_id', path.stem),
                    'name': payload.get('name', path.stem),
                    'updated_at': payload.get('updated_at', ''),
                    'message_count': len(messages) if isinstance(messages, list) else 0,
                    'latest': str(latest.get('content', '') or '')[:80] if isinstance(latest, dict) else '',
                }
            )
        return rooms

    def append_message(
        self,
        room_id: str,
        *,
        role: str,
        name: str,
        content: str,
        mentions_bot: bool = False,
    ) -> dict[str, Any]:
        payload = self.load_room(room_id)
        if payload is None:
            payload = self.create_room('Untitled room')
            room_id = payload['room_id']
        message = {
            'message_id': uuid4().hex,
            'role': role,
            'name': name.strip() or ('bot' if role == 'assistant' else 'user'),
            'content': content.strip(),
            'mentions_bot': mentions_bot,
            'created_at': _utc_now(),
        }
        payload.setdefault('messages', []).append(message)
        payload['updated_at'] = _utc_now()
        self._write_room(payload)
        return message

    def ensure_agent_session(self, room_id: str, session_store: Any) -> str:
        payload = self.load_room(room_id)
        if payload is None:
            payload = self.create_room('Untitled room')
        agent_session_id = str(payload.get('agent_session_id', '') or '').strip()
        if agent_session_id and session_store.load_session(agent_session_id) is not None:
            return agent_session_id
        session_payload = session_store.create_session()
        payload['agent_session_id'] = session_payload['session_id']
        payload['updated_at'] = _utc_now()
        self._write_room(payload)
        return payload['agent_session_id']

    def _write_room(self, payload: dict[str, Any]) -> None:
        payload.setdefault('messages', [])
        payload.setdefault('agent_session_id', '')
        payload.setdefault('compacted_summary', '')
        path = self._room_path(payload['room_id'])
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def _room_path(self, room_id: str) -> Path:
        return self.root / f'{room_id}.json'
