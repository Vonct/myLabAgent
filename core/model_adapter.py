from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from openai import OpenAI


@dataclass
class ModelContentItem:
    type: str
    text: str | None = None
    image_url: Any = None


@dataclass
class ModelOutputItem:
    type: str
    content: list[ModelContentItem] = field(default_factory=list)
    name: str = ''
    arguments: str = '{}'
    call_id: str = ''
    summary: list[ModelContentItem] = field(default_factory=list)


@dataclass
class ModelResponse:
    output: list[ModelOutputItem]
    output_text: str = ''
    usage: Any = None
    id: str = ''
    status: str = 'completed'
    error: Any = None
    raw: Any = None


class ModelAdapter:
    CHAT_COMPLETIONS_MODES = {'chat', 'chat_completion', 'chat_completions', 'completion', 'completions'}
    RESPONSES_MODES = {'response', 'responses'}

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float,
        api_mode: str = 'responses',
    ):
        self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
        self.model = model
        self.api_mode = self._normalize_api_mode(api_mode)

    def _normalize_api_mode(self, api_mode: str) -> str:
        value = str(api_mode or 'responses').strip().lower()
        if value in self.CHAT_COMPLETIONS_MODES:
            return 'chat_completions'
        if value in self.RESPONSES_MODES:
            return 'responses'
        return value

    def _get_value(self, item: Any, key: str, default: Any = None) -> Any:
        if isinstance(item, dict):
            return item.get(key, default)
        return getattr(item, key, default)

    def create(
        self,
        *,
        input_items: list[dict[str, Any]],
        extra_params: dict[str, Any],
        tools: list[dict[str, Any]],
        instructions: str,
        previous_response_id: str | None = None,
    ) -> Any:
        if self.api_mode == 'chat_completions':
            return self._create_chat_completion(
                input_items=input_items,
                extra_params=extra_params,
                tools=tools,
                instructions=instructions,
            )
        if self.api_mode != 'responses':
            raise ValueError(f'Unsupported LLM api_mode: {self.api_mode}')
        return self._create_response(
            input_items=input_items,
            extra_params=extra_params,
            tools=tools,
            instructions=instructions,
            previous_response_id=previous_response_id,
        )

    def _create_response(
        self,
        *,
        input_items: list[dict[str, Any]],
        extra_params: dict[str, Any],
        tools: list[dict[str, Any]],
        instructions: str,
        previous_response_id: str | None,
    ) -> Any:
        request_params: dict[str, Any] = {
            'model': self.model,
            'input': input_items,
            'stream': False,
            'instructions': instructions,
            **extra_params,
        }
        if previous_response_id:
            request_params['previous_response_id'] = previous_response_id
        if tools:
            request_params['tools'] = tools
            request_params['tool_choice'] = 'auto'
        return self.client.responses.create(**request_params)

    def _create_chat_completion(
        self,
        *,
        input_items: list[dict[str, Any]],
        extra_params: dict[str, Any],
        tools: list[dict[str, Any]],
        instructions: str,
    ) -> ModelResponse:
        request_params: dict[str, Any] = {
            'model': self.model,
            'messages': self._build_chat_messages(input_items, instructions),
            'stream': False,
        }
        extra_body = extra_params.get('extra_body')
        if isinstance(extra_body, dict) and extra_body:
            request_params['extra_body'] = extra_body
        chat_tools = self._build_chat_tools(tools)
        if chat_tools:
            request_params['tools'] = chat_tools
            request_params['tool_choice'] = 'auto'

        response = self.client.chat.completions.create(**request_params)
        return self._normalize_chat_response(response)

    def _build_chat_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        chat_tools: list[dict[str, Any]] = []
        for tool in tools:
            if not isinstance(tool, dict) or tool.get('type') != 'function':
                continue
            if 'function' in tool:
                chat_tools.append(tool)
                continue
            name = str(tool.get('name', '') or '').strip()
            if not name:
                continue
            chat_tools.append(
                {
                    'type': 'function',
                    'function': {
                        'name': name,
                        'description': tool.get('description', ''),
                        'parameters': tool.get('parameters', {}),
                    },
                }
            )
        return chat_tools

    def _build_chat_messages(self, input_items: list[dict[str, Any]], instructions: str) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        if instructions:
            messages.append({'role': 'system', 'content': instructions})

        index = 0
        while index < len(input_items):
            item = input_items[index]
            if not isinstance(item, dict):
                index += 1
                continue
            item_type = str(item.get('type', '') or '').strip()
            if item_type == 'function_call':
                tool_calls: list[dict[str, Any]] = []
                while index < len(input_items):
                    maybe_call = input_items[index]
                    if not isinstance(maybe_call, dict) or maybe_call.get('type') != 'function_call':
                        break
                    call_id = str(maybe_call.get('call_id', '') or '').strip()
                    name = str(maybe_call.get('name', '') or '').strip()
                    if call_id and name:
                        tool_calls.append(
                            {
                                'id': call_id,
                                'type': 'function',
                                'function': {
                                    'name': name,
                                    'arguments': str(maybe_call.get('arguments', '{}') or '{}'),
                                },
                            }
                        )
                    index += 1
                if tool_calls:
                    messages.append({'role': 'assistant', 'content': None, 'tool_calls': tool_calls})
                continue
            if item_type == 'function_call_output':
                messages.append(
                    {
                        'role': 'tool',
                        'tool_call_id': str(item.get('call_id', '') or ''),
                        'content': str(item.get('output', '') or ''),
                    }
                )
                index += 1
                continue

            role = str(item.get('role', '') or '').strip()
            if role not in {'user', 'assistant', 'system'}:
                index += 1
                continue
            messages.append(
                {
                    'role': role,
                    'content': self._build_chat_content(item.get('content', ''), role),
                }
            )
            index += 1
        return messages

    def _build_chat_content(self, content: Any, role: str) -> Any:
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return str(content or '')

        text_parts: list[str] = []
        multipart: list[dict[str, Any]] = []
        has_image = False
        for part in content:
            if isinstance(part, str):
                if part:
                    text_parts.append(part)
                    multipart.append({'type': 'text', 'text': part})
                continue
            if not isinstance(part, dict):
                continue
            part_type = str(part.get('type', '') or '').strip()
            if part_type in {'text', 'input_text', 'output_text'}:
                text = part.get('text')
                if text is None:
                    text = part.get('content')
                if text:
                    text_value = str(text)
                    text_parts.append(text_value)
                    multipart.append({'type': 'text', 'text': text_value})
                continue
            if part_type in {'image_url', 'input_image'}:
                image_url = part.get('image_url')
                if isinstance(image_url, dict):
                    image_url = image_url.get('url')
                url = str(image_url or '').strip()
                if url:
                    has_image = True
                    multipart.append({'type': 'image_url', 'image_url': {'url': url}})

        if has_image and role == 'user':
            return multipart
        return ''.join(text_parts)

    def _normalize_chat_response(self, response: Any) -> ModelResponse:
        choices = self._get_value(response, 'choices', None) or []
        if not choices:
            return ModelResponse(output=[], usage=self._get_value(response, 'usage', None), raw=response)

        message = self._get_value(choices[0], 'message', None)
        if message is None:
            return ModelResponse(output=[], usage=self._get_value(response, 'usage', None), raw=response)

        output: list[ModelOutputItem] = []
        final_text = self._extract_message_text(self._get_value(message, 'content', '') or '')
        content_items: list[ModelContentItem] = []
        if final_text:
            content_items.append(ModelContentItem(type='output_text', text=final_text))

        reasoning = (
            self._get_value(message, 'reasoning_content', '')
            or self._get_value(message, 'reasoning', '')
            or ''
        )
        if reasoning:
            output.append(
                ModelOutputItem(
                    type='reasoning',
                    summary=[ModelContentItem(type='summary_text', text=str(reasoning))],
                )
            )

        if content_items:
            output.append(ModelOutputItem(type='message', content=content_items))

        for tool_call in self._get_value(message, 'tool_calls', None) or []:
            function = self._get_value(tool_call, 'function', None)
            name = self._get_value(function, 'name', '') if function is not None else ''
            arguments = self._get_value(function, 'arguments', '{}') if function is not None else '{}'
            call_id = self._get_value(tool_call, 'id', '') or self._get_value(tool_call, 'call_id', '')
            if not name or not call_id:
                continue
            output.append(
                ModelOutputItem(
                    type='function_call',
                    name=str(name),
                    arguments=str(arguments or '{}'),
                    call_id=str(call_id),
                )
            )

        return ModelResponse(
            output=output,
            output_text=final_text,
            usage=self._get_value(response, 'usage', None),
            id='',
            raw=response,
        )

    def _extract_message_text(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return str(content or '')

        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if not isinstance(item, dict):
                continue
            text = item.get('text')
            if text is None:
                text = item.get('content')
            if text:
                parts.append(str(text))
        return ''.join(parts)
