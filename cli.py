from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from cli_render import CliRenderer
from cli_repl import CliRepl
from core.session_store import SessionStore
from services.agent_factory import build_agent_runtime
from services.session_service import SessionService

PROJECT_ROOT = Path(__file__).resolve().parent
VIP_CONFIG_PATH = PROJECT_ROOT / 'vip_config.json'
SESSION_STORE = SessionStore(PROJECT_ROOT / 'app_data' / 'sessions')
MODEL_CAPABILITIES = {
    'qwen3.5-plus': {'supports_thinking': True},
    'MiniMax-M2.5': {'supports_thinking': False},
    'kimi-k2.5': {'supports_thinking': True},
}
PRESET_LLM_BASE_URLS = {
    'qwen3.5-plus': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    'MiniMax-M2.5': 'https://api.minimaxi.com/v1',
    'kimi-k2.5': 'https://api.moonshot.cn/v1',
}
PRESET_EMBEDDING_BASE_URLS = {
    'text-embedding-v4': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
}


def _load_vip_profiles() -> dict[str, dict[str, Any]]:
    if not VIP_CONFIG_PATH.exists():
        return {}
    with open(VIP_CONFIG_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
    users = data.get('users', []) if isinstance(data, dict) else []
    return {item.get('username'): item for item in users if item.get('username')}


def _pick_profile(profile_name: str | None) -> dict[str, Any] | None:
    profiles = _load_vip_profiles()
    if not profiles:
        return None
    if profile_name and profile_name in profiles:
        return profiles[profile_name]
    if profile_name:
        raise ValueError(f'VIP profile `{profile_name}` not found in {VIP_CONFIG_PATH}')
    first_key = next(iter(profiles.keys()), None)
    return profiles.get(first_key) if first_key else None


def _resolve_runtime_config(args, *, llm_model_override: str | None = None) -> dict[str, Any]:
    profile = _pick_profile(getattr(args, 'profile', None))
    llm_model = llm_model_override or args.model or os.environ.get('LABAGENT_MODEL') or 'qwen3.5-plus'
    embedding_model = args.embedding_model or os.environ.get('LABAGENT_EMBEDDING_MODEL') or 'text-embedding-v4'

    profile_llm_pool = (profile or {}).get('llm_models') or {}
    profile_llm = profile_llm_pool.get(llm_model, {})
    profile_embedding_pool = (profile or {}).get('embedding_models') or {}
    profile_embedding = profile_embedding_pool.get(embedding_model, {})

    llm_api_key = args.api_key or os.environ.get('LABAGENT_API_KEY') or os.environ.get('OPENAI_API_KEY') or profile_llm.get('api_key', '')
    llm_base_url = args.base_url or os.environ.get('LABAGENT_BASE_URL') or profile_llm.get('base_url') or PRESET_LLM_BASE_URLS.get(llm_model, PRESET_LLM_BASE_URLS['qwen3.5-plus'])
    embedding_api_key = (
        args.embedding_api_key
        or os.environ.get('LABAGENT_EMBEDDING_API_KEY')
        or profile_embedding.get('api_key', '')
        or llm_api_key
    )
    embedding_base_url = (
        args.embedding_base_url
        or os.environ.get('LABAGENT_EMBEDDING_BASE_URL')
        or profile_embedding.get('base_url')
        or PRESET_EMBEDDING_BASE_URLS.get(embedding_model, PRESET_EMBEDDING_BASE_URLS['text-embedding-v4'])
    )

    if not llm_api_key:
        raise ValueError('Missing LLM API key. Pass --api-key, set LABAGENT_API_KEY/OPENAI_API_KEY, or configure vip_config.json.')

    supports_thinking = bool(profile_llm.get('supports_thinking', MODEL_CAPABILITIES.get(llm_model, {}).get('supports_thinking', False)))
    available_models = list(profile_llm_pool.keys()) if profile_llm_pool else []
    return {
        'llm_api_key': llm_api_key,
        'llm_base_url': llm_base_url,
        'llm_model': llm_model,
        'embedding_api_key': embedding_api_key,
        'embedding_base_url': embedding_base_url,
        'embedding_model': embedding_model,
        'project_root': PROJECT_ROOT,
        'permission_mode': args.sandbox,
        'max_tool_rounds': args.max_tool_rounds,
        'supports_thinking': supports_thinking,
        'profile': profile,
        'available_models': available_models,
    }


def _build_common_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--model', default=None)
    parser.add_argument('--base-url', default=None)
    parser.add_argument('--api-key', default=None)
    parser.add_argument('--embedding-model', default=None)
    parser.add_argument('--embedding-base-url', default=None)
    parser.add_argument('--embedding-api-key', default=None)
    parser.add_argument('--profile', default=None, help='Optional vip_config profile username')
    parser.add_argument('--sandbox', default='workspace-write', choices=['read-only', 'workspace-write', 'full-access'])
    parser.add_argument('--reasoning', action='store_true')
    parser.add_argument('--max-tool-rounds', type=int, default=4)
    return parser


def _build_agent_from_config(config: dict[str, Any]):
    _, agent = build_agent_runtime(**{k: config[k] for k in ['llm_api_key', 'llm_base_url', 'llm_model', 'embedding_api_key', 'embedding_base_url', 'embedding_model', 'project_root', 'permission_mode', 'max_tool_rounds']})
    return agent


def _run_chat(args) -> int:
    config = _resolve_runtime_config(args)
    agent = _build_agent_from_config(config)
    session_service = SessionService(SESSION_STORE)
    session_payload = session_service.create_or_resume_session(args.session_id)
    renderer = CliRenderer()

    def switch_model(model_name: str) -> tuple[Any, bool]:
        updated_config = _resolve_runtime_config(args, llm_model_override=model_name)
        updated_agent = _build_agent_from_config(updated_config)
        return updated_agent, bool(updated_config['supports_thinking'])

    repl = CliRepl(
        agent=agent,
        session_store=SESSION_STORE,
        session_service=session_service,
        session_id=session_payload['session_id'],
        renderer=renderer,
        reasoning_mode=args.reasoning,
        supports_thinking=config['supports_thinking'],
        model_options=config['available_models'],
        on_model_switch=switch_model,
    )
    return repl.run()


def _run_ask(args) -> int:
    config = _resolve_runtime_config(args)
    agent = _build_agent_from_config(config)
    session_service = SessionService(SESSION_STORE)
    session_payload = session_service.create_or_resume_session(args.session_id)
    session_id = session_payload['session_id']
    renderer = CliRenderer()
    prompt = args.prompt.strip()
    renderer.print_user(prompt)
    session_service.append_user_message(session_id, prompt)
    messages = session_service.get_messages(session_id)
    task = SESSION_STORE.start_task(session_id, prompt)

    final_chunks: list[str] = []
    errored = False
    for event in agent.chat(
        messages=messages,
        reasoning_mode=args.reasoning,
        supports_thinking=config['supports_thinking'],
        session_store=SESSION_STORE,
        session_id=session_id,
        task_id=task.task_id,
    ):
        renderer.render_event(event)
        if event.get('type') == 'answer_chunk':
            final_chunks.append(str(event.get('content', '')))
        elif event.get('type') == 'error':
            errored = True
    renderer.finish_answer()

    final_text = ''.join(final_chunks).strip()
    if final_text:
        session_service.append_assistant_message(session_id, final_text)
    SESSION_STORE.finish_task(session_id, task.task_id, final_text, status='failed' if errored else 'completed')
    return 1 if errored else 0


def _run_session_list(args) -> int:
    session_service = SessionService(SESSION_STORE)
    renderer = CliRenderer()
    renderer.print_session_list(session_service.list_sessions(limit=args.limit))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='labagent')
    subparsers = parser.add_subparsers(dest='command', required=True)

    chat_parser = subparsers.add_parser('chat', parents=[_build_common_parser()])
    chat_parser.add_argument('--session-id', default=None)
    chat_parser.set_defaults(handler=_run_chat)

    ask_parser = subparsers.add_parser('ask', parents=[_build_common_parser()])
    ask_parser.add_argument('prompt')
    ask_parser.add_argument('--session-id', default=None)
    ask_parser.set_defaults(handler=_run_ask)

    resume_parser = subparsers.add_parser('resume', parents=[_build_common_parser()])
    resume_parser.add_argument('session_id')
    resume_parser.set_defaults(handler=_run_chat)

    session_list_parser = subparsers.add_parser('session-list')
    session_list_parser.add_argument('--limit', type=int, default=20)
    session_list_parser.set_defaults(handler=_run_session_list)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if getattr(args, 'command', '') == 'resume':
        args.session_id = args.session_id
        args.command = 'chat'
    return args.handler(args)


if __name__ == '__main__':
    raise SystemExit(main())
