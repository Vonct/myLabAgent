from __future__ import annotations

from pathlib import Path

from agent_core import LabAgent
from core.permissions import PermissionLevel, PermissionManager
from core.prompt_loader import load_prompt
from core.skill_loader import SkillLoader
from core.tool_registry import ToolRegistry
from rag_engine import RAGEngine


def _resolve_allowed_permissions(permission_mode: str) -> set[PermissionLevel]:
    normalized = permission_mode.strip().lower()
    modes = {
        'read-only': {PermissionLevel.READ_ONLY},
        'workspace-write': {
            PermissionLevel.READ_ONLY,
            PermissionLevel.NETWORK,
            PermissionLevel.EXEC,
            PermissionLevel.FILE_WRITE,
        },
        'full-access': {
            PermissionLevel.READ_ONLY,
            PermissionLevel.NETWORK,
            PermissionLevel.EXEC,
            PermissionLevel.FILE_WRITE,
        },
    }
    return modes.get(normalized, modes['workspace-write'])


def build_agent_runtime(
    *,
    llm_api_key: str,
    llm_base_url: str,
    llm_model: str,
    llm_extra_body_for_thinking: dict | None,
    embedding_api_key: str,
    embedding_base_url: str,
    embedding_model: str,
    project_root: Path,
    permission_mode: str = 'workspace-write',
    max_tool_rounds: int = 4,
) -> tuple[RAGEngine, LabAgent]:
    rag_engine = RAGEngine(embedding_api_key, embedding_base_url, embedding_model)
    permission_manager = PermissionManager(_resolve_allowed_permissions(permission_mode))
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
        max_tool_rounds=max_tool_rounds,
        project_root=project_root,
        extra_body_for_thinking=llm_extra_body_for_thinking,
    )
    return rag_engine, agent
