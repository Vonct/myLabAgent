from __future__ import annotations

from pathlib import Path

import streamlit as st

from agent_core import LabAgent
from core.permissions import PermissionLevel, PermissionManager
from core.prompt_loader import load_prompt
from core.skill_loader import SkillLoader
from core.tool_registry import ToolRegistry
from rag_engine import RAGEngine


def build_agent(
    llm_api_key: str,
    llm_base_url: str,
    llm_model: str,
    embedding_api_key: str,
    embedding_base_url: str,
    embedding_model: str,
    project_root: Path,
) -> tuple[RAGEngine, LabAgent]:
    rag_engine = RAGEngine(embedding_api_key, embedding_base_url, embedding_model)
    permission_manager = PermissionManager(
        {
            PermissionLevel.READ_ONLY,
            PermissionLevel.NETWORK,
            PermissionLevel.EXEC,
        }
    )
    tool_registry = ToolRegistry(project_root / 'config' / 'tools.json', permission_manager)
    skill_loader = SkillLoader(project_root / '.agent_skills' / 'skills')
    prompt = load_prompt(project_root / 'prompts' / 'lab_agent.md')
    agent = LabAgent(
        api_key=llm_api_key,
        rag_engine=rag_engine,
        base_url=llm_base_url,
        llm_model=llm_model,
        tool_registry=tool_registry,
        system_prompt=prompt,
        skill_loader=skill_loader,
        max_tool_rounds=4,
    )
    return rag_engine, agent


def start_task(session_store, prompt: str) -> str:
    task = session_store.start_task(st.session_state.session_id, prompt)
    st.session_state.task_id = task.task_id
    return task.task_id
