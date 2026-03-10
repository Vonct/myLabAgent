from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from core.permissions import PermissionLevel, PermissionManager

ToolExecutor = Callable[[dict[str, Any]], str]


@dataclass
class RegisteredTool:
    name: str
    schema: dict[str, Any]
    executor: ToolExecutor
    permission: PermissionLevel
    description: str


class ToolRegistry:
    def __init__(self, definitions_path: Path, permission_manager: PermissionManager):
        self.definitions_path = definitions_path
        self.permission_manager = permission_manager
        self._definitions = self._load_definitions(definitions_path)
        self._tools: dict[str, RegisteredTool] = {}

    def _load_definitions(self, path: Path) -> dict[str, Any]:
        with open(path, 'r', encoding='utf-8-sig') as f:
            return json.load(f)

    def register(
        self,
        name: str,
        executor: ToolExecutor,
        permission: PermissionLevel,
        *,
        description_override: str | None = None,
    ) -> None:
        definition = self._definitions.get(name)
        '''
        definition = {
            "description": "从知识库中检索与用户问题相关的文档片段。",
            "parameters": {
                "type": "object",
                "properties": {
                "query": {
                    "type": "string",
                    "description": "用于检索的关键词或问题。"
                }
                },
                "required": ["query"]
            }
        }
        '''
        if not definition:
            raise KeyError(f'Tool definition not found for `{name}`')
        description = description_override or definition['description']
        function_schema = {
            'type': 'function',
            'function': {
                'name': name,
                'description': description,
                'parameters': definition['parameters'],
            },
        }
        self._tools[name] = RegisteredTool(
            name=name,
            schema=function_schema,
            executor=executor,
            permission=permission,
            description=description,
        )

    def get_openai_schemas(self) -> list[dict[str, Any]]:
        return [tool.schema for tool in self._tools.values()]

    def execute(self, name: str, args: dict[str, Any]) -> str:
        tool = self._tools.get(name)
        if tool is None:
            return json.dumps({'error': f'Unknown tool: {name}'}, ensure_ascii=False)

        permission = self.permission_manager.check(tool.permission)
        if not permission.allowed:
            return json.dumps({'error': permission.reason}, ensure_ascii=False)

        return tool.executor(args)

    def describe(self, name: str) -> RegisteredTool | None:
        return self._tools.get(name)
