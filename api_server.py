from __future__ import annotations

import argparse
import logging
import os
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from cli import MODEL_CAPABILITIES, PROJECT_ROOT, SESSION_STORE, _build_agent_from_config, _resolve_runtime_config
from core.canonical_message import extract_image_urls_from_content, extract_text_from_content
from core.session_store import SessionStore
from core.prompt_loader import load_prompt
from services.miniprogram_session_service import MiniprogramSessionService
from services.session_service import SessionService

MINIPROGRAM_SESSION_STORE = SessionStore(PROJECT_ROOT / 'app_data' / 'miniprogram_sessions')
MINIPROGRAM_INDEX_PATH = PROJECT_ROOT / 'app_data' / 'miniprogram_sessions' / 'space_session_index.json'
API_SERVER_PROMPT_PATH = PROJECT_ROOT / 'prompts' / 'TinyUni_agents.md'
DEFAULT_PROMPT_PATH = PROJECT_ROOT / 'prompts' / 'lab_agent.md'
logger = logging.getLogger(__name__)


@dataclass
class ApiRuntime:
    agent: Any
    supports_thinking: bool
    session_service: SessionService
    miniprogram_session_service: MiniprogramSessionService
    public_base_url: str
    api_token: str
    prompt_path: str


class CreateSessionResponse(BaseModel):
    session_id: str
    created_at: str
    updated_at: str


class SessionDetailResponse(BaseModel):
    session_id: str
    created_at: str
    updated_at: str
    messages: list[dict[str, Any]]
    tasks: list[dict[str, Any]]
    memories: list[dict[str, Any]]


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str | None = None
    reasoning_mode: bool = False
    debug_events: bool = False


class ChatResponse(BaseModel):
    session_id: str
    task_id: str
    status: str
    final_text: str
    images: list[str] = []
    thinking_text: str = ""
    tool_names: list[str]
    event_count: int
    events: list[dict[str, Any]] | None = None


class MiniprogramEnsureSessionRequest(BaseModel):
    user_id: str = Field(min_length=1)
    space_id: str = Field(min_length=1)
    space_name: str = ''


class MiniprogramEnsureSessionResponse(BaseModel):
    session_id: str
    space_id: str
    space_name: str = ''
    created: bool


class MiniprogramHistoryResponse(BaseModel):
    session_id: str
    space_id: str
    space_name: str = ''
    messages: list[dict[str, Any]]
    tasks: list[dict[str, Any]]
    memories: list[dict[str, Any]]


class MiniprogramChatRequest(BaseModel):
    user_id: str = Field(min_length=1)
    space_id: str = Field(min_length=1)
    space_name: str = ''
    message: str = Field(min_length=1)
    reasoning_mode: bool = False
    debug_events: bool = False


class MiniprogramChatResponse(BaseModel):
    session_id: str
    space_id: str
    space_name: str = ''
    task_id: str
    status: str
    final_text: str
    images: list[str] = []
    thinking_text: str = ''
    tool_names: list[str]
    event_count: int
    events: list[dict[str, Any]] | None = None


def _build_runtime_args() -> argparse.Namespace:
    return argparse.Namespace(
        model='doubao-seed-2-0-lite-260215',
        base_url=None,
        api_key=None,
        embedding_model=None,
        embedding_base_url=None,
        embedding_api_key=None,
        profile=None,
        sandbox='workspace-write',
        reasoning=False,
        max_tool_rounds=4,
    )


def _create_runtime() -> ApiRuntime:
    config = _resolve_runtime_config(_build_runtime_args())
    agent = _build_agent_from_config(config)
    prompt_path = API_SERVER_PROMPT_PATH if API_SERVER_PROMPT_PATH.exists() else DEFAULT_PROMPT_PATH
    agent.system_prompt = load_prompt(prompt_path).replace('当前 LLM 模型名称', agent.llm_model)
    return ApiRuntime(
        agent=agent,
        supports_thinking=bool(config['supports_thinking']),
        session_service=SessionService(SESSION_STORE),
        miniprogram_session_service=MiniprogramSessionService(MINIPROGRAM_SESSION_STORE, MINIPROGRAM_INDEX_PATH),
        public_base_url=os.environ.get('LABAGENT_PUBLIC_BASE_URL', '').strip(),
        api_token=os.environ.get('LABAGENT_API_TOKEN', '').strip(),
        prompt_path=str(prompt_path),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.runtime = _create_runtime()
    yield


app = FastAPI(
    title='LabAgent API',
    version='0.1.0',
    description='Minimal FastAPI wrapper for the existing myLabAgent runtime.',
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)


def _runtime() -> ApiRuntime:
    return app.state.runtime


def _normalize_participant_name(user_id: str) -> str:
    normalized = re.sub(r'[^a-zA-Z0-9_]+', '_', user_id).strip('_')
    if not normalized:
        normalized = 'room_user'
    if not normalized[0].isalpha():
        normalized = f'user_{normalized}'
    return normalized[:64]


def _ensure_session(session_id: str | None) -> dict[str, Any]:
    runtime = _runtime()
    return runtime.session_service.create_or_resume_session(session_id)


def _require_api_token(x_api_key: str | None = None, authorization: str | None = None) -> None:
    runtime = _runtime()
    expected = runtime.api_token
    if not expected:
        return
    provided = (x_api_key or '').strip()
    if not provided and authorization:
        scheme, _, token = authorization.strip().partition(' ')
        if scheme.lower() == 'bearer':
            provided = token.strip()
    if provided != expected:
        raise HTTPException(status_code=401, detail='Invalid API token.')


@app.get('/health')
def health() -> dict[str, Any]:
    runtime = _runtime()
    return {
        'ok': True,
        'model': getattr(runtime.agent, 'llm_model', 'unknown'),
        'supports_thinking': runtime.supports_thinking,
        'known_models': sorted(MODEL_CAPABILITIES.keys()),
        'public_base_url': runtime.public_base_url,
        'api_token_configured': bool(runtime.api_token),
        'prompt_path': runtime.prompt_path,
    }


@app.post('/sessions', response_model=CreateSessionResponse)
def create_session() -> CreateSessionResponse:
    payload = _ensure_session(None)
    return CreateSessionResponse(
        session_id=payload['session_id'],
        created_at=payload['created_at'],
        updated_at=payload['updated_at'],
    )


@app.get('/sessions')
def list_sessions(limit: int = 20) -> dict[str, Any]:
    runtime = _runtime()
    return {'sessions': runtime.session_service.list_sessions(limit=limit)}


@app.get('/sessions/{session_id}', response_model=SessionDetailResponse)
def get_session(session_id: str) -> SessionDetailResponse:
    payload = SESSION_STORE.load_session(session_id)
    if payload is None:
        raise HTTPException(status_code=404, detail=f'Session not found: {session_id}')
    session_service = _runtime().session_service
    return SessionDetailResponse(
        session_id=payload['session_id'],
        created_at=payload.get('created_at', ''),
        updated_at=payload.get('updated_at', ''),
        messages=session_service.get_messages(session_id),
        tasks=payload.get('tasks', []),
        memories=payload.get('memories', []),
    )


@app.post('/chat', response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    runtime = _runtime()
    session_payload = _ensure_session(req.session_id)
    session_id = session_payload['session_id']
    session_service = runtime.session_service

    prompt = req.message.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail='Message must not be empty.')

    session_service.append_user_message(session_id, prompt)
    messages = session_service.get_messages(session_id)
    task = SESSION_STORE.start_task(session_id, prompt)

    final_chunks: list[str] = []
    persisted_assistant_content = None
    thinking_parts: list[str] = []
    tool_names: list[str] = []
    event_log: list[dict[str, Any]] = []
    errored = False

    for event in runtime.agent.chat(
        messages=messages,
        reasoning_mode=req.reasoning_mode,
        supports_thinking=runtime.supports_thinking,
        session_store=SESSION_STORE,
        session_id=session_id,
        task_id=task.task_id,
    ):
        event_type = str(event.get('type', ''))
        if req.debug_events:
            event_log.append(event)
        if event_type == 'answer_chunk':
            final_chunks.append(str(event.get('content', '')))
        elif event_type == 'reasoning':
            content = str(event.get('content', '')).strip()
            if content:
                thinking_parts.append(content)
        elif event_type == 'tool_exec':
            tool_name = str(event.get('tool', '')).strip()
            if tool_name and tool_name not in tool_names:
                tool_names.append(tool_name)
        elif event_type == 'final_message':
            persisted_assistant_content = event.get('content')
        elif event_type == 'error':
            errored = True
            detail = str(event.get('content', 'Agent execution failed.')).strip() or 'Agent execution failed.'
            logger.error('chat failed session_id=%s task_id=%s detail=%s', session_id, task.task_id, detail)
            SESSION_STORE.finish_task(session_id, task.task_id, detail, status='failed')
            raise HTTPException(status_code=500, detail=detail)

    final_text = (extract_text_from_content(persisted_assistant_content) or ''.join(final_chunks)).strip()
    final_images = extract_image_urls_from_content(persisted_assistant_content) if persisted_assistant_content is not None else []
    task_status = 'failed' if errored else 'completed'

    if persisted_assistant_content is not None:
        session_service.append_assistant_message(session_id, persisted_assistant_content)
    elif final_text:
        session_service.append_assistant_message(session_id, final_text)
    SESSION_STORE.finish_task(session_id, task.task_id, final_text, status=task_status)
    task_record = SESSION_STORE.get_task(session_id, task.task_id) or {}
    session_service.append_memory_card(
        session_id,
        task_id=task.task_id,
        prompt=prompt,
        answer=final_text,
        tool_events=task_record.get('tool_events', []),
        has_image=False,
        status=task_status,
    )
    runtime.agent.record_long_term_memory(
        prompt=prompt,
        answer=final_text,
        tool_events=task_record.get('tool_events', []),
        session_id=session_id,
        task_id=task.task_id,
        status=task_status,
    )

    return ChatResponse(
        session_id=session_id,
        task_id=task.task_id,
        status=task_status,
        final_text=final_text,
        images=final_images,
        thinking_text='\n\n'.join(part for part in thinking_parts if part).strip(),
        tool_names=tool_names,
        event_count=len(event_log) if req.debug_events else 0,
        events=event_log if req.debug_events else None,
    )


@app.post('/miniprogram/session/ensure', response_model=MiniprogramEnsureSessionResponse)
def ensure_miniprogram_session(
    req: MiniprogramEnsureSessionRequest,
    x_api_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> MiniprogramEnsureSessionResponse:
    _require_api_token(x_api_key=x_api_key, authorization=authorization)
    runtime = _runtime()
    payload, created = runtime.miniprogram_session_service.ensure_space_session(
        space_id=req.space_id.strip(),
        user_id=req.user_id.strip(),
        space_name=req.space_name.strip(),
    )
    return MiniprogramEnsureSessionResponse(
        session_id=payload['session_id'],
        space_id=req.space_id.strip(),
        space_name=req.space_name.strip(),
        created=created,
    )


@app.get('/miniprogram/session/history', response_model=MiniprogramHistoryResponse)
def get_miniprogram_history(
    space_id: str,
    user_id: str,
    space_name: str = '',
    x_api_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> MiniprogramHistoryResponse:
    _require_api_token(x_api_key=x_api_key, authorization=authorization)
    runtime = _runtime()
    payload, _ = runtime.miniprogram_session_service.ensure_space_session(
        space_id=space_id.strip(),
        user_id=user_id.strip(),
        space_name=space_name.strip(),
    )
    entry = runtime.miniprogram_session_service.get_space_entry(space_id.strip()) or {}
    return MiniprogramHistoryResponse(
        session_id=payload['session_id'],
        space_id=space_id.strip(),
        space_name=str(entry.get('space_name', '') or space_name),
        messages=runtime.miniprogram_session_service.session_service.get_messages(payload['session_id']),
        tasks=payload.get('tasks', []),
        memories=payload.get('memories', []),
    )


@app.post('/miniprogram/chat', response_model=MiniprogramChatResponse)
def miniprogram_chat(
    req: MiniprogramChatRequest,
    x_api_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> MiniprogramChatResponse:
    _require_api_token(x_api_key=x_api_key, authorization=authorization)
    runtime = _runtime()
    space_id = req.space_id.strip()
    user_id = req.user_id.strip()
    space_name = req.space_name.strip()
    prompt = req.message.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail='Message must not be empty.')

    session_payload, _ = runtime.miniprogram_session_service.ensure_space_session(
        space_id=space_id,
        user_id=user_id,
        space_name=space_name,
    )
    session_id = session_payload['session_id']
    session_service = runtime.miniprogram_session_service.session_service
    participant_name = _normalize_participant_name(user_id)

    session_service.append_user_message_with_name(session_id, prompt, participant_name)
    messages = session_service.get_messages(session_id)
    task_prompt = f'[{user_id}] {prompt}'
    task = MINIPROGRAM_SESSION_STORE.start_task(session_id, task_prompt)

    final_chunks: list[str] = []
    persisted_assistant_content = None
    thinking_parts: list[str] = []
    tool_names: list[str] = []
    event_log: list[dict[str, Any]] = []

    for event in runtime.agent.chat(
        messages=messages,
        reasoning_mode=req.reasoning_mode,
        supports_thinking=runtime.supports_thinking,
        session_store=MINIPROGRAM_SESSION_STORE,
        session_id=session_id,
        task_id=task.task_id,
    ):
        event_type = str(event.get('type', ''))
        if req.debug_events:
            event_log.append(event)
        if event_type == 'answer_chunk':
            final_chunks.append(str(event.get('content', '')))
        elif event_type == 'reasoning':
            content = str(event.get('content', '')).strip()
            if content:
                thinking_parts.append(content)
        elif event_type == 'tool_exec':
            tool_name = str(event.get('tool', '')).strip()
            if tool_name and tool_name not in tool_names:
                tool_names.append(tool_name)
        elif event_type == 'final_message':
            persisted_assistant_content = event.get('content')
        elif event_type == 'error':
            detail = str(event.get('content', 'Agent execution failed.')).strip() or 'Agent execution failed.'
            logger.error(
                'miniprogram chat failed space_id=%s session_id=%s task_id=%s user_id=%s detail=%s',
                space_id,
                session_id,
                task.task_id,
                user_id,
                detail,
            )
            MINIPROGRAM_SESSION_STORE.finish_task(session_id, task.task_id, detail, status='failed')
            raise HTTPException(status_code=500, detail=detail)

    final_text = (extract_text_from_content(persisted_assistant_content) or ''.join(final_chunks)).strip()
    final_images = extract_image_urls_from_content(persisted_assistant_content) if persisted_assistant_content is not None else []
    if persisted_assistant_content is not None:
        session_service.append_assistant_message(session_id, persisted_assistant_content)
    elif final_text:
        session_service.append_assistant_message(session_id, final_text)
    MINIPROGRAM_SESSION_STORE.finish_task(session_id, task.task_id, final_text, status='completed')
    task_record = MINIPROGRAM_SESSION_STORE.get_task(session_id, task.task_id) or {}
    session_service.append_memory_card(
        session_id,
        task_id=task.task_id,
        prompt=task_prompt,
        answer=final_text,
        tool_events=task_record.get('tool_events', []),
        has_image=False,
        status='completed',
    )
    runtime.agent.record_long_term_memory(
        prompt=task_prompt,
        answer=final_text,
        tool_events=task_record.get('tool_events', []),
        session_id=session_id,
        task_id=task.task_id,
        status='completed',
    )

    entry = runtime.miniprogram_session_service.get_space_entry(space_id) or {}
    return MiniprogramChatResponse(
        session_id=session_id,
        space_id=space_id,
        space_name=str(entry.get('space_name', '') or space_name),
        task_id=task.task_id,
        status='completed',
        final_text=final_text,
        images=final_images,
        thinking_text='\n\n'.join(part for part in thinking_parts if part).strip(),
        tool_names=tool_names,
        event_count=len(event_log) if req.debug_events else 0,
        events=event_log if req.debug_events else None,
    )


if __name__ == '__main__':
    import uvicorn

    uvicorn.run(
        'api_server:app',
        host=os.environ.get('LABAGENT_API_HOST', '0.0.0.0').strip() or '0.0.0.0',
        port=int(os.environ.get('LABAGENT_API_PORT', '8000')),
        reload=False,
    )
