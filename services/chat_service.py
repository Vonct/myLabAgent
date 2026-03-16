from __future__ import annotations

import streamlit as st

from services.agent_factory import build_agent_runtime


def build_agent(
    llm_api_key: str,
    llm_base_url: str,
    llm_model: str,
    embedding_api_key: str,
    embedding_base_url: str,
    embedding_model: str,
    project_root,
):
    return build_agent_runtime(
        llm_api_key=llm_api_key,
        llm_base_url=llm_base_url,
        llm_model=llm_model,
        embedding_api_key=embedding_api_key,
        embedding_base_url=embedding_base_url,
        embedding_model=embedding_model,
        project_root=project_root,
        permission_mode='workspace-write',
        max_tool_rounds=4,
    )


def start_task(session_store, prompt: str) -> str:
    task = session_store.start_task(st.session_state.session_id, prompt)
    st.session_state.task_id = task.task_id
    return task.task_id
