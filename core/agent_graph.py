from __future__ import annotations

import json
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph


class AgentGraphState(TypedDict):
    messages: list[dict[str, Any]]
    input_items: list[dict[str, Any]]
    extra_params: dict[str, Any]
    previous_response_id: str
    response: Any
    tool_calls: list[dict[str, Any]]
    tool_round: int
    total_usage: dict[str, int]
    tool_image_urls: list[str]
    final_text: str
    final_images: list[str]
    final_content: list[dict[str, Any]]
    final_reasoning: str
    events: list[dict[str, Any]]
    session_store: Any
    session_id: str | None
    task_id: str | None


def build_agent_graph(agent: Any):
    def prepare_context(state: AgentGraphState) -> dict[str, Any]:
        conversation_items = agent._prepare_messages_for_responses(state['messages'])
        context_items: list[dict[str, Any]] = []

        long_term_memory_context = agent._build_long_term_memory_context(state['messages'])
        if long_term_memory_context:
            context_items.append({'role': 'user', 'content': long_term_memory_context})

        session_store = state.get('session_store')
        session_id = state.get('session_id')
        if agent._is_memory_injection_enabled() and session_store and session_id:
            memory_context = agent._build_memory_context(session_store, session_id, state['messages'])
            if memory_context:
                context_items.append({'role': 'user', 'content': memory_context})

        if context_items:
            conversation_items = context_items + conversation_items
        return {'input_items': conversation_items, 'events': []}

    def call_model(state: AgentGraphState) -> dict[str, Any]:
        response = agent._create_response(
            state['input_items'],
            state['extra_params'],
            previous_response_id=state.get('previous_response_id') or None,
        )
        agent._raise_for_failed_response(response)
        usage = agent._parse_usage(getattr(response, 'usage', None))
        return {
            'response': response,
            'previous_response_id': agent._get_response_id(response),
            'tool_calls': agent._extract_response_tool_calls(response),
            'total_usage': agent._merge_usage(state['total_usage'], usage),
            'events': [],
        }

    def execute_tools(state: AgentGraphState) -> dict[str, Any]:
        tool_round = state['tool_round'] + 1
        events: list[dict[str, Any]] = []
        if tool_round == 1:
            events.append({'type': 'thought', 'content': '正在分析问题并准备调用工具...'})
        else:
            events.append({'type': 'thought', 'content': f'正在继续执行第 {tool_round} 轮工具调用...'})

        session_store = state.get('session_store')
        session_id = state.get('session_id')
        task_id = state.get('task_id')
        tool_outputs: list[dict[str, Any]] = []
        tool_image_urls = list(state['tool_image_urls'])

        for tool_call in state['tool_calls']:
            func_name = tool_call['name']
            args = json.loads(tool_call['arguments'])
            display_args = dict(args)
            if func_name == 'edit_image' and session_store and session_id:
                latest_image = session_store.get_latest_generated_image(session_id)
                if latest_image:
                    args['_latest_generated_image'] = latest_image

            events.append({'type': 'tool_exec', 'tool': func_name, 'input': json.dumps(display_args, ensure_ascii=False)})
            tool_output = (
                agent.tool_registry.execute(func_name, args)
                if agent.tool_registry
                else json.dumps({'error': 'Tool registry unavailable'}, ensure_ascii=False)
            )
            events.append({'type': 'tool_result', 'output': tool_output})

            generated_image_asset = agent._extract_generated_image_asset(tool_output)
            if generated_image_asset:
                image_url = str(generated_image_asset.get('image_url', '') or '').strip()
                if image_url:
                    tool_image_urls.append(image_url)
                if session_store and session_id:
                    session_store.append_generated_image(session_id, generated_image_asset)

            if session_store and session_id and task_id:
                session_store.append_tool_event(
                    session_id,
                    task_id,
                    {
                        'tool': func_name,
                        'args': display_args,
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

        if state.get('previous_response_id'):
            next_input_items = tool_outputs
        else:
            next_input_items = list(state['input_items'])
            for tool_call in state['tool_calls']:
                next_input_items.append(
                    {
                        'type': 'function_call',
                        'name': tool_call['name'],
                        'arguments': tool_call['arguments'],
                        'call_id': tool_call['call_id'],
                    }
                )
            next_input_items.extend(tool_outputs)

        return {
            'input_items': next_input_items,
            'tool_round': tool_round,
            'tool_image_urls': tool_image_urls,
            'events': events,
        }

    def finalize(state: AgentGraphState) -> dict[str, Any]:
        final_text, final_images, final_content, final_reasoning = agent._extract_response_payload(state['response'])
        for image_url in state['tool_image_urls']:
            if image_url in final_images:
                continue
            final_images.append(image_url)
            final_content.append({'type': 'image_url', 'image_url': {'url': image_url}})

        if state['tool_calls'] and state['tool_round'] >= agent.max_tool_rounds:
            limit_note = (
                f'已达到当前代理的最大工具轮数限制（{agent.max_tool_rounds} 轮）。'
                ' 如果任务仍未完成，请继续细化提示，或提高工具轮数上限。'
            )
            final_text = f'{limit_note}\n\n{final_text}'.strip()
            if final_content and final_content[0].get('type') == 'text':
                original = final_content[0].get('text') or final_content[0].get('content') or ''
                final_content[0]['text'] = f'{limit_note}\n\n{original}'.strip()
            else:
                final_content.insert(0, {'type': 'text', 'text': limit_note})

        events: list[dict[str, Any]] = []
        if final_reasoning:
            events.append({'type': 'reasoning', 'content': final_reasoning})

        usage_suffix = agent._usage_suffix(state['total_usage'])
        text_for_display = final_text
        if text_for_display:
            text_for_display += usage_suffix
        elif not final_images:
            text_for_display = '模型本轮没有返回可见文本，请重试或切换模型。' + usage_suffix
            final_content = [{'type': 'text', 'text': text_for_display}]

        if text_for_display:
            for index in range(0, len(text_for_display), 40):
                events.append({'type': 'answer_chunk', 'content': text_for_display[index:index + 40]})

        events.append(
            {
                'type': 'final_message',
                'content': final_content if final_content else [{'type': 'text', 'text': text_for_display}],
                'display_content': text_for_display,
                'images': final_images,
            }
        )

        return {
            'final_text': final_text,
            'final_images': final_images,
            'final_content': final_content,
            'final_reasoning': final_reasoning,
            'events': events,
        }

    def route_after_model(state: AgentGraphState) -> Literal['tools', 'finalize']:
        if state['tool_calls'] and state['tool_round'] < agent.max_tool_rounds:
            return 'tools'
        return 'finalize'

    graph = StateGraph(AgentGraphState)
    graph.add_node('prepare_context', prepare_context)
    graph.add_node('call_model', call_model)
    graph.add_node('tools', execute_tools)
    graph.add_node('finalize', finalize)
    graph.add_edge(START, 'prepare_context')
    graph.add_edge('prepare_context', 'call_model')
    graph.add_conditional_edges('call_model', route_after_model, {'tools': 'tools', 'finalize': 'finalize'})
    graph.add_edge('tools', 'call_model')
    graph.add_edge('finalize', END)
    return graph.compile()
