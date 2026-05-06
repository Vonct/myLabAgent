from __future__ import annotations

import hashlib
import json
from pathlib import Path

import streamlit as st

from core.session_store import SessionStore


def load_vip_config(file_path: Path) -> dict[str, dict]:
    if not file_path.exists():
        return {}
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    users = data.get("users", []) if isinstance(data, dict) else []
    return {u.get("username"): u for u in users if u.get("username")}


def verify_vip_user(user: dict, password: str) -> bool:
    if not user:
        return False
    plain = user.get("password_plain")
    if plain is not None:
        return password == plain
    expected_hash = user.get("password_sha256")
    if not expected_hash:
        return False
    pwd_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
    return pwd_hash == expected_hash


def init_session_state(session_store: SessionStore) -> None:
    defaults = {
        "messages": [],
        "rag_engine": None,
        "agent": None,
        "current_runtime_signature": None,
        "vip_authenticated": False,
        "vip_username": "",
        "vip_profile": None,
        "applied_config": None,
        "selected_project_id": None,
        "pending_chat_image_path": None,
        "pending_chat_image_name": "",
        "auth_mode": "手动输入",
        "reasoning_mode": False,
        "uploader_key": 0,
        "task_id": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

    if "session_id" not in st.session_state:
        session_payload = session_store.create_session()
        st.session_state.session_id = session_payload["session_id"]


def resolve_model_base_url(model_name: str, preset_base_urls: dict, default_base_url: str) -> str:
    return preset_base_urls.get(model_name, default_base_url)


def to_bool(value, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def resolve_llm_capabilities(model_name: str, model_capabilities: dict, config: dict | None = None) -> dict[str, bool]:
    base = model_capabilities.get(
        model_name,
        {"supports_image_input": False, "supports_thinking": False},
    )
    if not isinstance(config, dict):
        return {
            "supports_image_input": bool(base.get("supports_image_input", False)),
            "supports_thinking": bool(base.get("supports_thinking", False)),
        }
    return {
        "supports_image_input": to_bool(
            config.get("supports_image_input"),
            bool(base.get("supports_image_input", False)),
        ),
        "supports_thinking": to_bool(
            config.get("supports_thinking"),
            bool(base.get("supports_thinking", False)),
        ),
    }


def normalize_model_pool(raw_pool, model_capabilities: dict | None = None) -> dict:
    normalized = {}
    if not isinstance(raw_pool, dict):
        return normalized
    for model_name, model_config in raw_pool.items():
        if isinstance(model_config, dict):
            item = {
                "api_key": model_config.get("api_key", ""),
                "base_url": model_config.get("base_url", ""),
            }
            extra_body_for_thinking = model_config.get("extra_body_forThinking")
            if isinstance(extra_body_for_thinking, dict):
                item["extra_body_forThinking"] = dict(extra_body_for_thinking)
            if model_capabilities is not None:
                item["api_mode"] = model_config.get("api_mode", "responses")
                item.update(resolve_llm_capabilities(model_name, model_capabilities, model_config))
            normalized[model_name] = item
        elif isinstance(model_config, str):
            item = {"api_key": model_config, "base_url": ""}
            if model_capabilities is not None:
                item["api_mode"] = "responses"
                item.update(resolve_llm_capabilities(model_name, model_capabilities))
            normalized[model_name] = item
    return normalized


def resolve_vip_model_pools(
    profile: dict,
    model_capabilities: dict,
    preset_llm_base_urls: dict,
    default_llm_base_url: str,
    preset_embedding_base_urls: dict,
    default_embedding_base_url: str,
) -> tuple[dict, dict]:
    llm_pool = normalize_model_pool(profile.get("llm_models"), model_capabilities)
    embedding_pool = normalize_model_pool(profile.get("embedding_models"))
    if not llm_pool:
        legacy_llm_keys = profile.get("llm_api_keys_by_model", {})
        if isinstance(legacy_llm_keys, dict):
            for model_name, api_key in legacy_llm_keys.items():
                llm_pool[model_name] = {
                    "api_key": api_key,
                    "base_url": resolve_model_base_url(model_name, preset_llm_base_urls, default_llm_base_url),
                    "api_mode": "responses",
                    **resolve_llm_capabilities(model_name, model_capabilities),
                }
    if not llm_pool and profile.get("llm_model") and profile.get("api_key"):
        model_name = profile.get("llm_model")
        llm_pool[model_name] = {
            "api_key": profile.get("api_key", ""),
            "base_url": profile.get("base_url", resolve_model_base_url(model_name, preset_llm_base_urls, default_llm_base_url)),
            "api_mode": profile.get("api_mode", "responses"),
            **resolve_llm_capabilities(model_name, model_capabilities, profile),
        }
    if not embedding_pool:
        legacy_embedding_keys = profile.get("embedding_api_keys_by_model", {})
        if isinstance(legacy_embedding_keys, dict):
            for model_name, api_key in legacy_embedding_keys.items():
                embedding_pool[model_name] = {
                    "api_key": api_key,
                    "base_url": resolve_model_base_url(model_name, preset_embedding_base_urls, default_embedding_base_url),
                }
    if not embedding_pool and profile.get("embedding_model") and profile.get("api_key"):
        model_name = profile.get("embedding_model")
        embedding_pool[model_name] = {
            "api_key": profile.get("api_key", ""),
            "base_url": profile.get("base_url", resolve_model_base_url(model_name, preset_embedding_base_urls, default_embedding_base_url)),
        }
    return llm_pool, embedding_pool
