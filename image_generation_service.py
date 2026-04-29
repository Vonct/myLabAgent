from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, request


DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_OPENROUTER_IMAGE_MODEL = "openai/gpt-5.4-image-2"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _date_dir() -> str:
    return datetime.now(timezone.utc).strftime("%Y_%m_%d")


def _normalize_model_name(model: str | None) -> str:
    value = str(model or "").strip() or DEFAULT_OPENROUTER_IMAGE_MODEL
    if value.startswith("https://openrouter.ai/"):
        tail = value.removeprefix("https://openrouter.ai/").strip("/")
        if tail and not tail.startswith("api/"):
            return tail
    return value


def _normalize_base_url(base_url: str | None) -> str:
    value = str(base_url or "").strip() or DEFAULT_OPENROUTER_BASE_URL
    return value.rstrip("/")


def _guess_extension(mime_type: str) -> str:
    guessed = mimetypes.guess_extension(mime_type.split(";", 1)[0].strip())
    if guessed in {".jpe", ".jpeg"}:
        return ".jpg"
    return guessed or ".png"


def _path_to_data_url(path: Path) -> str:
    mime_type, _ = mimetypes.guess_type(str(path))
    mime_type = mime_type or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _safe_filename_part(value: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value).strip("-")
    return safe[:80] or "image"


def _size_from_aspect_ratio(aspect_ratio: str | None) -> str | None:
    normalized = str(aspect_ratio or "").strip()
    mapping = {
        "1:1": "1024x1024",
        "16:9": "1536x1024",
        "9:16": "1024x1536",
    }
    return mapping.get(normalized)


def _aspect_ratio_from_prompt(prompt: str) -> str | None:
    prompt_text = str(prompt or "")
    if re.search(r"(?<!\d)16\s*[:：]\s*9(?!\d)", prompt_text):
        return "16:9"
    if re.search(r"(?<!\d)9\s*[:：]\s*16(?!\d)", prompt_text):
        return "9:16"
    if re.search(r"(?<!\d)1\s*[:：]\s*1(?!\d)", prompt_text):
        return "1:1"
    return None


class ImageGenerationService:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str | None,
        model: str | None,
        output_root: Path,
        request_timeout: float = 180,
        api_mode: str = "responses",
    ):
        self.api_key = api_key
        self.base_url = _normalize_base_url(base_url)
        self.model = _normalize_model_name(model)
        self.output_root = output_root
        self.request_timeout = request_timeout
        self.api_mode = api_mode.strip().lower() or "responses"

    def generate(
        self,
        *,
        prompt: str,
        aspect_ratio: str | None = None,
        size: str | None = None,
        image_size: str | None = None,
        output_format: str | None = None,
    ) -> dict[str, Any]:
        return self._create_image(
            prompt=prompt,
            source_image_path=None,
            aspect_ratio=aspect_ratio,
            size=size,
            image_size=image_size,
            output_format=output_format,
            operation="generate",
        )

    def edit(
        self,
        *,
        source_image_path: Path,
        instruction: str,
        aspect_ratio: str | None = None,
        size: str | None = None,
        image_size: str | None = None,
        output_format: str | None = None,
    ) -> dict[str, Any]:
        prompt = (
            "Edit the provided image according to this instruction. "
            "Preserve the subject identity, composition, and style unless the instruction says otherwise.\n\n"
            f"Instruction: {instruction}"
        )
        return self._create_image(
            prompt=prompt,
            source_image_path=source_image_path,
            aspect_ratio=aspect_ratio,
            size=size,
            image_size=image_size,
            output_format=output_format,
            operation="edit",
        )

    def _create_image(
        self,
        *,
        prompt: str,
        source_image_path: Path | None,
        aspect_ratio: str | None,
        size: str | None,
        image_size: str | None,
        output_format: str | None,
        operation: str,
    ) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError(
                "Missing image API key. Set LABAGENT_IMAGE_API_KEY or OPENROUTER_API_KEY."
            )
        if not prompt.strip():
            raise ValueError("Image prompt must not be empty.")

        effective_aspect_ratio = aspect_ratio or _aspect_ratio_from_prompt(prompt)
        effective_size = (size or "").strip() or _size_from_aspect_ratio(effective_aspect_ratio)
        source_data_url = _path_to_data_url(source_image_path) if source_image_path else None
        if self.api_mode in {"chat", "chat_completions", "completion", "completions"}:
            payload = self._build_chat_completions_payload(
                prompt=prompt,
                source_data_url=source_data_url,
                aspect_ratio=effective_aspect_ratio,
                size=effective_size,
                image_size=image_size,
                output_format=output_format,
            )
            endpoint = f"{self.base_url}/chat/completions"
        else:
            payload = self._build_responses_payload(
                prompt=prompt,
                source_data_url=source_data_url,
                aspect_ratio=effective_aspect_ratio,
                size=effective_size,
                image_size=image_size,
                output_format=output_format,
            )
            endpoint = f"{self.base_url}/responses"

        response_payload = self._post_json(endpoint, payload)
        image_refs = self._extract_image_refs(response_payload)
        if not image_refs:
            return {
                "error": "Image provider returned no image payload.",
                "provider_response_preview": json.dumps(response_payload, ensure_ascii=False)[:2000],
            }

        saved = self._save_image_ref(image_refs[0], output_format=output_format)
        prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:10]
        asset = {
            "type": "generated_image",
            "image_id": saved["image_id"],
            "path": saved.get("path", ""),
            "image_url": saved.get("data_url") or saved.get("remote_url", ""),
            "remote_url": saved.get("remote_url", ""),
            "prompt": prompt,
            "prompt_hash": prompt_hash,
            "operation": operation,
            "source_image_path": str(source_image_path) if source_image_path else "",
            "aspect_ratio": effective_aspect_ratio or "",
            "size": effective_size or "",
            "image_size": image_size or "",
            "output_format": output_format or saved.get("format", ""),
            "model": self.model,
            "provider": "openrouter",
            "api_mode": self.api_mode,
            "created_at": _utc_now(),
        }
        return asset

    def _build_responses_payload(
        self,
        *,
        prompt: str,
        source_data_url: str | None,
        aspect_ratio: str | None,
        size: str | None,
        image_size: str | None,
        output_format: str | None,
    ) -> dict[str, Any]:
        content: list[dict[str, Any]] = [{"type": "input_text", "text": prompt}]
        if source_data_url:
            content.append({"type": "input_image", "image_url": source_data_url})
        payload: dict[str, Any] = {
            "model": self.model,
            "input": [{"role": "user", "content": content}],
            "modalities": ["image", "text"],
            "stream": False,
        }
        image_config: dict[str, Any] = {}
        effective_size = (size or "").strip() or _size_from_aspect_ratio(aspect_ratio)
        if aspect_ratio:
            image_config["aspect_ratio"] = aspect_ratio
        if effective_size:
            image_config["size"] = effective_size
        if image_size:
            image_config["image_size"] = image_size
        if output_format:
            image_config["output_format"] = output_format
        if image_config:
            payload["image_config"] = image_config
        return payload

    def _build_chat_completions_payload(
        self,
        *,
        prompt: str,
        source_data_url: str | None,
        aspect_ratio: str | None,
        size: str | None,
        image_size: str | None,
        output_format: str | None,
    ) -> dict[str, Any]:
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        if source_data_url:
            content.append({"type": "image_url", "image_url": {"url": source_data_url}})
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": content}],
            "modalities": ["image", "text"],
            "stream": False,
        }
        image_config: dict[str, Any] = {}
        effective_size = (size or "").strip() or _size_from_aspect_ratio(aspect_ratio)
        if aspect_ratio:
            image_config["aspect_ratio"] = aspect_ratio
        if effective_size:
            image_config["size"] = effective_size
        if image_size:
            image_config["image_size"] = image_size
        if output_format:
            image_config["output_format"] = output_format
        if image_config:
            payload["image_config"] = image_config
        return payload

    def _post_json(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        referer = os.environ.get("OPENROUTER_HTTP_REFERER", "").strip()
        title = os.environ.get("OPENROUTER_X_TITLE", "myLabAgent").strip()
        if referer:
            headers["HTTP-Referer"] = referer
        if title:
            headers["X-Title"] = title
        req = request.Request(endpoint, data=body, headers=headers, method="POST")
        try:
            with request.urlopen(req, timeout=self.request_timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Image provider HTTP {exc.code}: {detail[:2000]}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"Image provider request failed: {exc}") from exc
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Image provider returned non-JSON response: {raw[:2000]}") from exc

    def _extract_image_refs(self, payload: Any) -> list[str]:
        refs: list[str] = []

        def add_ref(value: Any, *, assume_base64: bool = False) -> None:
            if not isinstance(value, str):
                return
            stripped = value.strip()
            if not stripped:
                return
            if stripped.startswith("data:image/") or stripped.startswith("http://") or stripped.startswith("https://"):
                refs.append(stripped)
                return
            if assume_base64 and len(stripped) > 200:
                refs.append(f"data:image/png;base64,{stripped}")

        def walk(node: Any, parent_type: str = "") -> None:
            if isinstance(node, dict):
                node_type = str(node.get("type", "") or parent_type)
                image_url = node.get("image_url")
                if isinstance(image_url, dict):
                    add_ref(image_url.get("url"))
                else:
                    add_ref(image_url)
                add_ref(node.get("url"))
                add_ref(node.get("b64_json"), assume_base64=True)
                add_ref(node.get("result"), assume_base64=node_type == "image_generation_call")
                for value in node.values():
                    walk(value, node_type)
            elif isinstance(node, list):
                for item in node:
                    walk(item, parent_type)

        walk(payload)
        unique_refs: list[str] = []
        seen: set[str] = set()
        for ref in refs:
            if ref in seen:
                continue
            seen.add(ref)
            unique_refs.append(ref)
        return unique_refs

    def _save_image_ref(self, image_ref: str, *, output_format: str | None) -> dict[str, Any]:
        if image_ref.startswith("data:image/"):
            header, encoded = image_ref.split(",", 1)
            mime = header.removeprefix("data:").split(";base64", 1)[0] or "image/png"
            raw = base64.b64decode(encoded)
            extension = _guess_extension(mime)
            requested_format = (output_format or "").strip().lower().lstrip(".")
            if requested_format:
                extension = f".{_safe_filename_part(requested_format)}"
            image_hash = hashlib.sha256(raw).hexdigest()[:16]
            image_id = f"img_{int(time.time())}_{image_hash}"
            target_dir = self.output_root / _date_dir()
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / f"{image_id}{extension}"
            if not target.exists():
                target.write_bytes(raw)
            return {
                "image_id": image_id,
                "path": str(target),
                "data_url": f"data:{mime};base64,{encoded}",
                "format": extension.lstrip("."),
            }

        image_id = f"img_{int(time.time())}_{hashlib.sha256(image_ref.encode('utf-8')).hexdigest()[:16]}"
        try:
            with request.urlopen(image_ref, timeout=self.request_timeout) as resp:
                raw = resp.read()
                mime = resp.headers.get_content_type() or "image/png"
            extension = _guess_extension(mime)
            target_dir = self.output_root / _date_dir()
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / f"{image_id}{extension}"
            target.write_bytes(raw)
            encoded = base64.b64encode(raw).decode("ascii")
            return {
                "image_id": image_id,
                "path": str(target),
                "remote_url": image_ref,
                "data_url": f"data:{mime};base64,{encoded}",
                "format": extension.lstrip("."),
            }
        except Exception:
            pass
        return {
            "image_id": image_id,
            "remote_url": image_ref,
            "format": "",
        }
