from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Generator

from openai import OpenAI

from amap_mcp_adapter import AMapMCPAdapter, DEFAULT_AMAP_MCP_COMMAND
from core.permissions import PermissionLevel
from core.skill_loader import SkillLoader
from core.tool_registry import ToolRegistry
from rag_engine import RAGEngine


class LabAgent:
    def __init__(
        self,
        api_key: str,
        rag_engine: RAGEngine,
        base_url: str,
        llm_model: str = 'qwen3.5-plus',
        tool_registry: ToolRegistry | None = None,
        system_prompt: str = '',
        skill_loader: SkillLoader | None = None,
        max_tool_rounds: int = 4,
    ):
        request_timeout = float(os.environ.get('LABCHAT_REQUEST_TIMEOUT', '180'))
        self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=request_timeout)
        self.llm_model = llm_model
        self.rag = rag_engine
        self.request_timeout = request_timeout
        self.weather_adapter = AMapMCPAdapter(
            mode=os.environ.get('AMAP_MCP_MODE', 'mcp'),
            mcp_command=os.environ.get('AMAP_MCP_COMMAND', DEFAULT_AMAP_MCP_COMMAND),
            mcp_tool_name=os.environ.get('AMAP_MCP_TOOL_NAME', 'maps_weather'),
        )
        self.system_prompt = system_prompt.replace('当前 LLM 模型名称', self.llm_model)
        self.tool_registry = tool_registry
        self.skill_loader = skill_loader
        self.max_tool_rounds = max(1, int(max_tool_rounds))
        if self.tool_registry is not None:
            self.tool_registry.register('retrieve_document', self._run_retrieve_document, PermissionLevel.READ_ONLY)
            self.tool_registry.register('recognize_handwritten_digit', self._run_digit_inference, PermissionLevel.EXEC)
            self.tool_registry.register('get_amap_weather', self._run_weather_query, PermissionLevel.NETWORK)
            self.tool_registry.register(
                'load_skill',
                self._run_load_skill,
                PermissionLevel.READ_ONLY,
                description_override=self.skill_loader.build_tool_description() if self.skill_loader else None,
            )
        self.tools = self.tool_registry.get_openai_schemas() if self.tool_registry else []
        self.response_tools = self._build_response_tools(self.tools)

    def _build_response_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        response_tools: list[dict[str, Any]] = []
        for tool in tools:
            if tool.get('type') != 'function':
                continue
            function_def = tool.get('function') or {}
            name = function_def.get('name')
            if not name:
                continue
            response_tools.append(
                {
                    'type': 'function',
                    'name': name,
                    'description': function_def.get('description', ''),
                    'parameters': function_def.get('parameters', {}),
                }
            )
        return response_tools

    def _create_response(
        self,
        input_items: list[dict[str, Any]],
        extra_params: dict[str, Any],
        previous_response_id: str | None = None,
    ):
        request_params: dict[str, Any] = {
            'model': self.llm_model,
            'input': input_items,
            'stream': False,
            'instructions': self.system_prompt,
            **extra_params,
        }
        if previous_response_id:
            request_params['previous_response_id'] = previous_response_id
        if self.response_tools:
            request_params['tools'] = self.response_tools
            request_params['tool_choice'] = 'auto'
        return self.client.responses.create(**request_params)

    def _get_response_id(self, response: Any) -> str:
        response_id = getattr(response, 'id', None)
        if response_id is None and isinstance(response, dict):
            response_id = response.get('id')
        return str(response_id or '')

    def _parse_usage(self, usage: Any) -> dict[str, int]:
        if usage is None:
            return {'input_tokens': 0, 'output_tokens': 0, 'total_tokens': 0}
        if isinstance(usage, dict):
            input_tokens = int(usage.get('input_tokens', usage.get('prompt_tokens', 0)))
            output_tokens = int(usage.get('output_tokens', usage.get('completion_tokens', 0)))
            total_tokens = int(usage.get('total_tokens', input_tokens + output_tokens))
            return {
                'input_tokens': input_tokens,
                'output_tokens': output_tokens,
                'total_tokens': total_tokens,
            }
        input_tokens = int(getattr(usage, 'input_tokens', getattr(usage, 'prompt_tokens', 0)) or 0)
        output_tokens = int(getattr(usage, 'output_tokens', getattr(usage, 'completion_tokens', 0)) or 0)
        total_tokens = int(getattr(usage, 'total_tokens', input_tokens + output_tokens) or (input_tokens + output_tokens))
        return {
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
            'total_tokens': total_tokens,
        }

    def _merge_usage(self, first: dict[str, int], second: dict[str, int]) -> dict[str, int]:
        return {
            'input_tokens': first['input_tokens'] + second['input_tokens'],
            'output_tokens': first['output_tokens'] + second['output_tokens'],
            'total_tokens': first['total_tokens'] + second['total_tokens'],
        }

    def _usage_suffix(self, usage: dict[str, int]) -> str:
        return (
            '\n\n---\n'
            f"Token 消耗：输入 {usage['input_tokens']}，输出 {usage['output_tokens']}，总计 {usage['total_tokens']}"
        )


    def _normalize_content_item(self, item: Any) -> dict[str, Any] | None:
        if isinstance(item, str):
            return {'type': 'text', 'text': item}
        if isinstance(item, dict):
            return item

        item_type = getattr(item, 'type', None)
        if item_type == 'image_url':
            image_url = getattr(item, 'image_url', None)
            if image_url is not None:
                url = getattr(image_url, 'url', None)
                if url:
                    return {'type': 'image_url', 'image_url': {'url': url}}

        text = getattr(item, 'text', None)
        if text is not None:
            return {'type': item_type or 'text', 'text': text}
        content = getattr(item, 'content', None)
        if content is not None:
            return {'type': item_type or 'text', 'content': content}
        return None

    def _extract_content_payload(self, message: Any) -> tuple[str, list[str], list[dict[str, Any]], str]:
        content = getattr(message, 'content', None)
        reasoning = getattr(message, 'reasoning_content', '') or getattr(message, 'reasoning', '')

        final_content = ''
        image_urls: list[str] = []
        normalized_content: list[dict[str, Any]] = []
        if isinstance(content, str):
            final_content = content
            normalized_content = [{'type': 'text', 'text': content}]
        elif isinstance(content, list):
            parts = []
            for item in content:
                normalized_item = self._normalize_content_item(item)
                if not normalized_item:
                    continue
                normalized_content.append(normalized_item)
                if normalized_item.get('type') == 'image_url':
                    image_url = normalized_item.get('image_url') or {}
                    url = image_url.get('url')
                    if url:
                        image_urls.append(url)
                    continue
                text = normalized_item.get('text') or normalized_item.get('content') or ''
                if text:
                    parts.append(text)
            final_content = ''.join(parts)
        elif content is not None:
            final_content = str(content)
            normalized_content = [{'type': 'text', 'text': final_content}]

        return final_content, image_urls, normalized_content, str(reasoning) if reasoning else ''

    def _normalize_input_content(self, content: Any) -> Any:
        if isinstance(content, list):
            normalized_items: list[dict[str, Any]] = []
            for item in content:
                normalized_item = self._normalize_content_item(item)
                if normalized_item:
                    normalized_items.append(normalized_item)
            return normalized_items
        return content

    def _prepare_messages_for_responses(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        response_input: list[dict[str, Any]] = []
        for message in messages:
            role = message.get('role')
            if not role or role in {'system', 'tool'}:
                continue

            input_item = {
                'role': role,
                'content': self._normalize_input_content(message.get('content')),
            }
            if message.get('name'):
                input_item['name'] = message['name']

            response_input.append(input_item)
        return response_input

    def _get_response_output_items(self, response: Any) -> list[Any]:
        output = getattr(response, 'output', None)
        if output is None and isinstance(response, dict):
            output = response.get('output')
        return list(output or [])

    def _extract_response_tool_calls(self, response: Any) -> list[dict[str, Any]]:
        tool_calls: list[dict[str, Any]] = []
        for item in self._get_response_output_items(response):
            item_type = getattr(item, 'type', None)
            if item_type is None and isinstance(item, dict):
                item_type = item.get('type')
            if item_type != 'function_call':
                continue
            name = getattr(item, 'name', None) if not isinstance(item, dict) else item.get('name')
            arguments = getattr(item, 'arguments', None) if not isinstance(item, dict) else item.get('arguments')
            call_id = getattr(item, 'call_id', None) if not isinstance(item, dict) else item.get('call_id')
            if not name or not call_id:
                continue
            tool_calls.append(
                {
                    'name': name,
                    'arguments': arguments or '{}',
                    'call_id': call_id,
                }
            )
        return tool_calls

    def _raise_for_failed_response(self, response: Any) -> None:
        status = getattr(response, 'status', None)
        if status != 'failed':
            return
        error = getattr(response, 'error', None)
        message = getattr(error, 'message', None) if error is not None else None
        raise RuntimeError(str(message or 'Responses API 调用失败。'))

    def _extract_reasoning_text(self, response: Any) -> str:
        reasoning_parts: list[str] = []
        for item in self._get_response_output_items(response):
            item_type = getattr(item, 'type', None)
            if item_type is None and isinstance(item, dict):
                item_type = item.get('type')
            if item_type != 'reasoning':
                continue

            summary = getattr(item, 'summary', None) if not isinstance(item, dict) else item.get('summary')
            if isinstance(summary, list):
                for summary_item in summary:
                    text = getattr(summary_item, 'text', None) if not isinstance(summary_item, dict) else summary_item.get('text')
                    if text:
                        reasoning_parts.append(str(text))
        return '\n'.join(part for part in reasoning_parts if part).strip()

    def _extract_response_payload(self, response: Any) -> tuple[str, list[str], list[dict[str, Any]], str]:
        final_text = str(getattr(response, 'output_text', '') or '')
        final_images: list[str] = []
        final_content: list[dict[str, Any]] = []

        for item in self._get_response_output_items(response):
            item_type = getattr(item, 'type', None)
            if item_type is None and isinstance(item, dict):
                item_type = item.get('type')
            if item_type != 'message':
                continue

            content_items = getattr(item, 'content', None) if not isinstance(item, dict) else item.get('content')
            for content_item in content_items or []:
                content_type = getattr(content_item, 'type', None)
                if content_type is None and isinstance(content_item, dict):
                    content_type = content_item.get('type')

                if content_type == 'output_text':
                    text = getattr(content_item, 'text', None) if not isinstance(content_item, dict) else content_item.get('text')
                    if text:
                        if not final_text:
                            final_text = str(text)
                        final_content.append({'type': 'text', 'text': str(text)})
                elif content_type == 'input_text':
                    text = getattr(content_item, 'text', None) if not isinstance(content_item, dict) else content_item.get('text')
                    if text:
                        if not final_text:
                            final_text = str(text)
                        final_content.append({'type': 'text', 'text': str(text)})
                elif content_type == 'image_url':
                    image_url = getattr(content_item, 'image_url', None) if not isinstance(content_item, dict) else content_item.get('image_url')
                    url = getattr(image_url, 'url', None) if image_url is not None and not isinstance(image_url, dict) else (image_url or {}).get('url')
                    if url:
                        final_images.append(str(url))
                        final_content.append({'type': 'image_url', 'image_url': {'url': str(url)}})

        if not final_content and final_text:
            final_content = [{'type': 'text', 'text': final_text}]

        return final_text, final_images, final_content, self._extract_reasoning_text(response)

    def _resolve_infer_pythons(self, base_dir: Path) -> list[Path]:
        candidates = [Path(sys.executable)]
        for candidate in [
            base_dir / '.venv' / 'Scripts' / 'python.exe',
            base_dir / '.venv' / 'bin' / 'python',
        ]:
            if candidate.exists():
                candidates.append(candidate)

        seen = set()
        unique_candidates: list[Path] = []
        for candidate in candidates:
            candidate_str = str(candidate.resolve()) if candidate.exists() else str(candidate)
            if candidate_str in seen:
                continue
            seen.add(candidate_str)
            unique_candidates.append(candidate)
        return unique_candidates

    def _run_retrieve_document(self, args: dict[str, Any]) -> str:
        query = str(args.get('query', '')).strip()
        docs = self.rag.retrieve(query)
        if not docs:
            return '未检索到相关文档片段。'
        max_docs = max(1, int(os.environ.get('RAG_MAX_RETURN_DOCS', '4')))
        max_chars_per_doc = max(200, int(os.environ.get('RAG_MAX_DOC_CHARS', '1500')))
        rendered_docs = []
        for doc in docs[:max_docs]:
            content = doc['content']
            if len(content) > max_chars_per_doc:
                content = content[:max_chars_per_doc].rstrip() + '...'
            rendered_docs.append(f"[来源: {doc['source']}]\n{content}")
        return '\n\n'.join(rendered_docs)

    def _run_digit_inference(self, args: dict[str, Any]) -> str:
        image_path = args.get('image_path')
        invert = bool(args.get('invert', False))
        normalize = bool(args.get('normalize', True))
        device = str(args.get('device', 'auto'))
        model_path = args.get('model_path')
        base_dir = Path(__file__).parent
        service_script = base_dir / 'digit_infer_service.py'

        infer_content = None
        for infer_python in self._resolve_infer_pythons(base_dir):
            cmd = [
                str(infer_python),
                str(service_script),
                str(image_path),
                '--device',
                device,
            ]
            if invert:
                cmd.append('--invert')
            if not normalize:
                cmd.append('--no-normalize')
            if model_path:
                cmd.extend(['--model-path', model_path])

            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                cwd=str(base_dir),
            )
            if proc.returncode != 0:
                continue

            output_text = proc.stdout.strip()
            try:
                json.loads(output_text)
                infer_content = output_text
                break
            except json.JSONDecodeError:
                continue

        if infer_content is None:
            infer_content = json.dumps(
                {'error': '请检查 Python 环境是否已安装手写数字识别所需依赖。'},
                ensure_ascii=False,
            )
        return infer_content

    def _run_weather_query(self, args: dict[str, Any]) -> str:
        city = str(args.get('city', '')).strip()
        try:
            weather_result = self.weather_adapter.get_weather(city)
            return json.dumps(weather_result, ensure_ascii=False)
        except Exception as e:
            return json.dumps({'error': f'天气工具调用失败: {e}'}, ensure_ascii=False)

    def _run_load_skill(self, args: dict[str, Any]) -> str:
        if self.skill_loader is None:
            return json.dumps({'error': 'Skill loader unavailable'}, ensure_ascii=False)
        name = str(args.get('name', '')).strip()
        return self.skill_loader.render_skill_content(name)

    def chat(
        self,
        messages: list[dict[str, Any]],
        reasoning_mode: bool = False,
        supports_thinking: bool = True,
        session_store=None,
        session_id: str | None = None,
        task_id: str | None = None,
    ) -> Generator[dict[str, Any], None, None]:
        conversation_items = self._prepare_messages_for_responses(messages)
        try:
            extra_params: dict[str, Any] = {}
            if reasoning_mode and supports_thinking:
                extra_params['extra_body'] = {'enable_thinking': True}

            response = self._create_response(conversation_items, extra_params)
            self._raise_for_failed_response(response)
            previous_response_id = self._get_response_id(response)
            total_usage = self._parse_usage(getattr(response, 'usage', None))
            current_tool_calls = self._extract_response_tool_calls(response)
            tool_round = 0

            while current_tool_calls and tool_round < self.max_tool_rounds:
                tool_round += 1
                if tool_round == 1:
                    thought = '正在分析问题并准备调用工具...'
                else:
                    thought = f'正在继续执行第 {tool_round} 轮工具调用...'
                yield {'type': 'thought', 'content': thought}

                tool_outputs: list[dict[str, Any]] = []

                for tool_call in current_tool_calls:
                    func_name = tool_call['name']
                    args = json.loads(tool_call['arguments'])
                    yield {'type': 'tool_exec', 'tool': func_name, 'input': json.dumps(args, ensure_ascii=False)}
                    tool_output = (
                        self.tool_registry.execute(func_name, args)
                        if self.tool_registry
                        else json.dumps({'error': 'Tool registry unavailable'}, ensure_ascii=False)
                    )
                    yield {'type': 'tool_result', 'output': tool_output}
                    if session_store and session_id and task_id:
                        session_store.append_tool_event(
                            session_id,
                            task_id,
                            {
                                'tool': func_name,
                                'args': args,
                                'tool_round': tool_round,
                                'output_preview': tool_output[:400],
                            },
                        )
                    tool_outputs.append(
                        {
                            'type': 'function_call_output',
                            'call_id': tool_call['call_id'],
                            'output': tool_output,
                        }
                    )
                # Prefer server-side continuation via previous_response_id.
                # Fallback to local transcript replay if response id is unavailable.
                if previous_response_id:
                    response = self._create_response(
                        tool_outputs,
                        extra_params,
                        previous_response_id=previous_response_id,
                    )
                else:
                    for tool_call in current_tool_calls:
                        conversation_items.append(
                            {
                                'type': 'function_call',
                                'name': tool_call['name'],
                                'arguments': tool_call['arguments'],
                                'call_id': tool_call['call_id'],
                            }
                        )
                    conversation_items.extend(tool_outputs)
                    response = self._create_response(conversation_items, extra_params)
                self._raise_for_failed_response(response)
                previous_response_id = self._get_response_id(response)
                total_usage = self._merge_usage(total_usage, self._parse_usage(getattr(response, 'usage', None)))
                current_tool_calls = self._extract_response_tool_calls(response)

            final_text, final_images, final_content, final_reasoning = self._extract_response_payload(response)

            if current_tool_calls and tool_round >= self.max_tool_rounds:
                limit_note = (
                    f'已达到当前代理的最大工具轮数限制（{self.max_tool_rounds} 轮）。'
                    ' 如果任务仍未完成，请继续细化提示，或提高工具轮数上限。'
                )
                final_text = f'{limit_note}\n\n{final_text}'.strip()
                if final_content and final_content[0].get('type') == 'text':
                    original = final_content[0].get('text') or final_content[0].get('content') or ''
                    final_content[0]['text'] = f'{limit_note}\n\n{original}'.strip()
                else:
                    final_content.insert(0, {'type': 'text', 'text': limit_note})

            if final_reasoning:
                yield {'type': 'reasoning', 'content': final_reasoning}

            usage_suffix = self._usage_suffix(total_usage)
            text_for_display = final_text
            if text_for_display:
                text_for_display += usage_suffix
            elif not final_images:
                text_for_display = '模型本轮没有返回可见文本，请重试或切换模型。' + usage_suffix
                final_content = [{'type': 'text', 'text': text_for_display}]

            if text_for_display:
                for i in range(0, len(text_for_display), 40):
                    yield {'type': 'answer_chunk', 'content': text_for_display[i:i + 40]}

            yield {
                'type': 'final_message',
                'content': final_content if final_content else [{'type': 'text', 'text': text_for_display}],
                'display_content': text_for_display,
                'images': final_images,
            }
        except Exception as e:
            if 'timed out' in str(e).lower():
                message = (
                    f'LLM request timed out (timeout={int(self.request_timeout)}s). '
                    'Retry later or narrow the question.'
                )
            else:
                message = str(e)
            yield {'type': 'error', 'content': message}
