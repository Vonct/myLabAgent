from __future__ import annotations

from typing import Any


def build_text_part(text: str) -> dict[str, Any]:
    return {'type': 'text', 'text': str(text)}


def build_image_part(image_url: str) -> dict[str, Any]:
    return {'type': 'image_url', 'image_url': {'url': str(image_url)}}


def normalize_content(content: Any) -> Any:
    if isinstance(content, str):
        return content

    if not isinstance(content, list):
        return str(content or '')

    normalized_parts: list[dict[str, Any]] = []
    for item in content:
        if isinstance(item, str):
            if item:
                normalized_parts.append(build_text_part(item))
            continue
        if not isinstance(item, dict):
            continue

        item_type = str(item.get('type', '') or '').strip()
        if item_type == 'image_url':
            image_url = item.get('image_url') or {}
            if not isinstance(image_url, dict):
                continue
            url = str(image_url.get('url', '') or '').strip()
            if url:
                normalized_parts.append(build_image_part(url))
            continue

        text = item.get('text')
        if text is None:
            text = item.get('content')
        if text is not None and str(text):
            normalized_parts.append(build_text_part(str(text)))

    return normalized_parts


def build_user_message(
    text: str,
    *,
    image_url: str | None = None,
    name: str | None = None,
) -> dict[str, Any]:
    stripped_text = text.strip()
    if image_url:
        parts = [build_image_part(image_url)]
        if stripped_text:
            parts.append(build_text_part(stripped_text))
        content: Any = parts
    else:
        content = stripped_text

    message: dict[str, Any] = {
        'role': 'user',
        'content': normalize_content(content),
    }
    if name:
        message['name'] = str(name)
    return message


def build_assistant_message(content: Any) -> dict[str, Any]:
    return {
        'role': 'assistant',
        'content': normalize_content(content),
    }


def canonicalize_message(message: dict[str, Any]) -> dict[str, Any]:
    role = str(message.get('role', '') or '').strip()
    canonical: dict[str, Any] = {
        'role': role,
        'content': normalize_content(message.get('content', '')),
    }

    name = str(message.get('name', '') or '').strip()
    if name:
        canonical['name'] = name

    return canonical


def extract_text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return str(content or '').strip()

    text_parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get('type', '') or '').strip()
        if item_type == 'image_url':
            continue
        text = item.get('text')
        if text is None:
            text = item.get('content')
        if text:
            text_parts.append(str(text))
    return ''.join(text_parts).strip()


def extract_image_urls_from_content(content: Any) -> list[str]:
    if not isinstance(content, list):
        return []

    urls: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if str(item.get('type', '') or '').strip() != 'image_url':
            continue
        image_url = item.get('image_url') or {}
        if not isinstance(image_url, dict):
            continue
        url = str(image_url.get('url', '') or '').strip()
        if url:
            urls.append(url)
    return urls


def extract_message_text(message: dict[str, Any]) -> str:
    return extract_text_from_content(message.get('content', ''))


def extract_message_image_urls(message: dict[str, Any]) -> list[str]:
    return extract_image_urls_from_content(message.get('content', ''))
