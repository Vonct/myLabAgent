from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.session_store import SessionStore
from services.session_service import SessionService


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MiniprogramSessionService:
    def __init__(self, store: SessionStore, index_path: Path):
        self.store = store
        self.session_service = SessionService(store)
        self.index_path = index_path
        self.index_path.parent.mkdir(parents=True, exist_ok=True)

    def _load_index(self) -> dict[str, dict[str, Any]]:
        if not self.index_path.exists():
            return {}
        with open(self.index_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}

    def _save_index(self, index: dict[str, dict[str, Any]]) -> None:
        with open(self.index_path, 'w', encoding='utf-8') as f:
            json.dump(index, f, ensure_ascii=False, indent=2)

    def ensure_space_session(
        self,
        *,
        space_id: str,
        user_id: str,
        space_name: str = '',
    ) -> tuple[dict[str, Any], bool]:
        index = self._load_index()
        entry = index.get(space_id)
        if entry:
            session_id = str(entry.get('session_id', '')).strip()
            payload = self.store.load_session(session_id) if session_id else None
            if payload is not None:
                participants = entry.get('participant_user_ids', [])
                if not isinstance(participants, list):
                    participants = []
                if user_id and user_id not in participants:
                    participants.append(user_id)
                entry['participant_user_ids'] = participants
                entry['space_name'] = space_name or entry.get('space_name', '')
                entry['updated_at'] = _utc_now()
                index[space_id] = entry
                self._save_index(index)
                return payload, False

        payload = self.store.create_session()
        index[space_id] = {
            'session_id': payload['session_id'],
            'space_id': space_id,
            'space_name': space_name,
            'created_by': user_id,
            'participant_user_ids': [user_id] if user_id else [],
            'created_at': payload.get('created_at', _utc_now()),
            'updated_at': payload.get('updated_at', _utc_now()),
        }
        self._save_index(index)
        return payload, True

    def get_space_entry(self, space_id: str) -> dict[str, Any] | None:
        return self._load_index().get(space_id)

    def get_space_session(self, space_id: str) -> dict[str, Any] | None:
        entry = self.get_space_entry(space_id)
        if not entry:
            return None
        session_id = str(entry.get('session_id', '')).strip()
        if not session_id:
            return None
        return self.store.load_session(session_id)
