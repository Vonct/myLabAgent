from __future__ import annotations

import argparse
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from cli import MODEL_CAPABILITIES, SESSION_STORE, _build_agent_from_config, _resolve_runtime_config
from services.session_service import SessionService


@dataclass
class ApiRuntime:
    agent: Any
    supports_thinking: bool
    session_service: SessionService


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
    thinking_text: str = ""
    tool_names: list[str]
    event_count: int
    events: list[dict[str, Any]] | None = None


def _build_runtime_args() -> argparse.Namespace:
    return argparse.Namespace(
        model=None,
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
    return ApiRuntime(
        agent=agent,
        supports_thinking=bool(config['supports_thinking']),
        session_service=SessionService(SESSION_STORE),
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


def _ensure_session(session_id: str | None) -> dict[str, Any]:
    runtime = _runtime()
    return runtime.session_service.create_or_resume_session(session_id)


@app.get('/health')
def health() -> dict[str, Any]:
    runtime = _runtime()
    return {
        'ok': True,
        'model': getattr(runtime.agent, 'llm_model', 'unknown'),
        'supports_thinking': runtime.supports_thinking,
        'known_models': sorted(MODEL_CAPABILITIES.keys()),
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
    return SessionDetailResponse(
        session_id=payload['session_id'],
        created_at=payload.get('created_at', ''),
        updated_at=payload.get('updated_at', ''),
        messages=payload.get('messages', []),
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
    persisted_assistant_text = ''
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
            content = event.get('content')
            if isinstance(content, list):
                text_parts: list[str] = []
                for item in content:
                    if not isinstance(item, dict):
                        continue
                    text = item.get('text')
                    if text is None:
                        text = item.get('content')
                    if isinstance(text, str) and text:
                        text_parts.append(text)
                persisted_assistant_text = ''.join(text_parts).strip()
        elif event_type == 'error':
            errored = True
            detail = str(event.get('content', 'Agent execution failed.')).strip() or 'Agent execution failed.'
            SESSION_STORE.finish_task(session_id, task.task_id, detail, status='failed')
            raise HTTPException(status_code=500, detail=detail)

    final_text = (persisted_assistant_text or ''.join(final_chunks)).strip()
    task_status = 'failed' if errored else 'completed'

    if final_text:
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

    return ChatResponse(
        session_id=session_id,
        task_id=task.task_id,
        status=task_status,
        final_text=final_text,
        thinking_text='\n\n'.join(part for part in thinking_parts if part).strip(),
        tool_names=tool_names,
        event_count=len(event_log) if req.debug_events else 0,
        events=event_log if req.debug_events else None,
    )


if __name__ == '__main__':
    import uvicorn

    uvicorn.run('api_server:app', host='127.0.0.1', port=8000, reload=False)
