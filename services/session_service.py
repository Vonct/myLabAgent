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

    def append_memory_card(
        self,
        session_id: str,
        *,
        task_id: str,
        prompt: str,
        answer: str,
        tool_events: list[dict[str, Any]] | None = None,
        has_image: bool = False,
        status: str = 'completed',
    ) -> None:
        tools = []
        for event in tool_events or []:
            name = str(event.get('tool', '')).strip()
            if name and name not in tools:
                tools.append(name)

        prompt_preview = prompt.strip().replace('\n', ' ')
        if len(prompt_preview) > 140:
            prompt_preview = prompt_preview[:140].rstrip() + '...'
        answer_preview = answer.strip().replace('\n', ' ')
        if len(answer_preview) > 220:
            answer_preview = answer_preview[:220].rstrip() + '...'

        summary_parts = [
            f"Q: {prompt_preview or '(empty)'}",
            f"A: {answer_preview or '(empty)'}",
        ]
        if tools:
            summary_parts.append(f"Tools: {', '.join(tools)}")
        if has_image:
            summary_parts.append("Input included image")

        memory = {
            'task_id': task_id,
            'status': status,
            'prompt': prompt,
            'answer': answer,
            'has_image': has_image,
            'tool_names': tools,
            'summary': ' | '.join(summary_parts),
        }
        self.store.append_memory(session_id, memory)

    def list_sessions(self, limit: int = 20) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for path in self.store.list_session_paths():
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
