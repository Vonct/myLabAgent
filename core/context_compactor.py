from __future__ import annotations

import json
import os
from typing import Any

from core.canonical_message import extract_message_text


DEFAULT_AUTO_COMPACT_TOKENS = 50000
DEFAULT_KEEP_RECENT_MESSAGES = 8
DEFAULT_COMPACT_INPUT_CHARS = 80000


def _env_int(name: str, default: int, minimum: int) -> int:
    try:
        return max(minimum, int(os.environ.get(name, str(default))))
    except ValueError:
        return default


def _is_auto_compact_enabled() -> bool:
    value = os.environ.get('LABAGENT_AUTO_COMPACT_ENABLED', '1').strip().lower()
    return value not in {'0', 'false', 'off', 'no'}


def estimate_text_tokens(text: str) -> int:
    if not text:
        return 0
    try:
        import tiktoken

        encoding = tiktoken.get_encoding('cl100k_base')
        return len(encoding.encode(text))
    except Exception:
        return max(1, len(text) // 4)


def estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    total = 0
    for message in messages:
        if not isinstance(message, dict):
            continue
        total += 4
        total += estimate_text_tokens(str(message.get('role', '') or ''))
        total += estimate_text_tokens(str(message.get('name', '') or ''))
        total += estimate_text_tokens(extract_message_text(message))
    return total


def build_compact_summary_message(summary: str) -> dict[str, Any]:
    content = (
        '[Compacted conversation summary]\n'
        'The earlier part of this session was compressed to preserve context window. '
        'Use it as continuity context; recent raw messages follow.\n\n'
        f'{summary.strip()}'
    )
    return {'role': 'user', 'content': content}


def _render_messages_for_summary(messages: list[dict[str, Any]], max_chars: int) -> str:
    lines: list[str] = []
    for index, message in enumerate(messages, start=1):
        if not isinstance(message, dict):
            continue
        role = str(message.get('role', '') or 'unknown').strip()
        name = str(message.get('name', '') or '').strip()
        label = f'{role}:{name}' if name else role
        text = extract_message_text(message)
        if not text:
            text = '(non-text or image-only message)'
        lines.append(f'[{index}] {label}: {text}')
    rendered = '\n'.join(lines)
    if len(rendered) > max_chars:
        rendered = rendered[-max_chars:].lstrip()
    return rendered


def _summarize_messages(
    agent: Any,
    *,
    existing_summary: str,
    messages_to_compact: list[dict[str, Any]],
) -> str:
    max_chars = _env_int('LABAGENT_COMPACT_INPUT_CHARS', DEFAULT_COMPACT_INPUT_CHARS, 4000)
    rendered_messages = _render_messages_for_summary(messages_to_compact, max_chars)
    existing_block = existing_summary.strip() or '(none)'
    compact_input = (
        'Existing compacted summary:\n'
        f'{existing_block}\n\n'
        'Raw messages to merge into the compact summary:\n'
        f'{rendered_messages}'
    )
    instructions = (
        'You compact a long agent conversation for future continuity. '
        'Return a concise but useful Chinese summary unless the conversation is mostly English. '
        'Preserve user goals, decisions, constraints, preferences, file paths, tool outcomes, unresolved tasks, '
        'and important assistant conclusions. Do not include secrets. Do not invent facts. '
        'Write plain text only, no JSON.'
    )
    response = agent._create_response(
        [{'role': 'user', 'content': compact_input}],
        {},
        tools_override=[],
        instructions_override=instructions,
    )
    agent._raise_for_failed_response(response)
    summary, _, _, _ = agent._extract_response_payload(response)
    return summary.strip()


def maybe_auto_compact_messages(
    agent: Any,
    *,
    messages: list[dict[str, Any]],
    session_store: Any,
    session_id: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not _is_auto_compact_enabled() or not session_store or not session_id:
        return messages, []

    compaction = session_store.get_context_compaction(session_id)
    compacted_summary = str(compaction.get('summary', '') or '').strip()
    compacted_until = int(compaction.get('until_message_count', 0) or 0)
    compacted_until = max(0, min(compacted_until, len(messages)))

    active_messages = messages
    if compacted_summary:
        active_messages = [build_compact_summary_message(compacted_summary)] + messages[compacted_until:]

    threshold = _env_int('LABAGENT_AUTO_COMPACT_TOKENS', DEFAULT_AUTO_COMPACT_TOKENS, 2000)
    if estimate_messages_tokens(active_messages) <= threshold:
        return active_messages, []

    keep_recent = _env_int('LABAGENT_COMPACT_KEEP_RECENT_MESSAGES', DEFAULT_KEEP_RECENT_MESSAGES, 2)
    cutoff = max(0, len(messages) - keep_recent)
    if cutoff <= compacted_until:
        return active_messages, []

    archive_path = session_store.archive_messages(
        session_id,
        messages[:cutoff],
        reason='auto_compact',
    )
    summary = _summarize_messages(
        agent,
        existing_summary=compacted_summary,
        messages_to_compact=messages[compacted_until:cutoff],
    )
    if not summary:
        return active_messages, []

    session_store.save_context_compaction(
        session_id,
        summary=summary,
        until_message_count=cutoff,
        archive_path=archive_path,
    )
    compacted_messages = [build_compact_summary_message(summary)] + messages[cutoff:]
    events = [
        {
            'type': 'thought',
            'content': f'会话上下文超过 {threshold} tokens，已自动压缩早期 {cutoff} 条消息。',
        }
    ]
    return compacted_messages, events
