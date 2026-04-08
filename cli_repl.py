from __future__ import annotations

import shlex
from io import BytesIO
from pathlib import Path
from typing import Any, Callable

from cli_render import CliRenderer
from services.session_service import SessionService


class CliRepl:
    def __init__(
        self,
        *,
        agent,
        session_store,
        session_service: SessionService,
        session_id: str,
        renderer: CliRenderer,
        reasoning_mode: bool = False,
        supports_thinking: bool = True,
        model_options: list[str] | None = None,
        on_model_switch: Callable[[str], tuple[Any, bool]] | None = None,
    ):
        self.agent = agent
        self.session_store = session_store
        self.session_service = session_service
        self.session_id = session_id
        self.renderer = renderer
        self.reasoning_mode = reasoning_mode
        self.supports_thinking = supports_thinking
        self.model_options = model_options or []
        self.on_model_switch = on_model_switch

    def _handle_add2lib_command(self, user_text: str) -> None:
        try:
            parts = shlex.split(user_text)
        except ValueError as exc:
            self.renderer.print_markdown(f'`/add2lib` 参数解析失败：{exc}')
            return

        if len(parts) < 2:
            self.renderer.print_markdown('用法：`/add2lib <pdf路径>`')
            return

        raw_path = parts[1]
        file_path = Path(raw_path).expanduser()
        if not file_path.is_absolute():
            file_path = Path.cwd() / file_path
        file_path = file_path.resolve()

        if not file_path.exists():
            self.renderer.print_markdown(f'文件不存在：`{file_path}`')
            return
        if not file_path.is_file():
            self.renderer.print_markdown(f'目标不是文件：`{file_path}`')
            return
        if file_path.suffix.lower() != '.pdf':
            self.renderer.print_markdown('当前 `/add2lib` 与 web 端保持一致，只支持 `PDF` 文件。')
            return

        rag_engine = getattr(self.agent, 'rag', None)
        if rag_engine is None:
            self.renderer.print_markdown('当前 runtime 未初始化知识库引擎。')
            return

        self.renderer.print_markdown(f'正在入库：`{file_path}`')
        try:
            with open(file_path, 'rb') as f:
                result = rag_engine.process_file(BytesIO(f.read()), file_path.name)
        except Exception as exc:
            self.renderer.print_markdown(f'读取文件失败：`{exc}`')
            return

        usage = rag_engine.get_embedding_usage()
        backend = getattr(rag_engine, 'backend', 'unknown')
        backend_runtime_error = getattr(rag_engine, 'backend_runtime_error', '')
        lines = [
            result,
            f'RAG backend: `{backend}`',
            (
                f"Embedding tokens: 本次输入 {usage['last']['input_tokens']}，"
                f"本次总计 {usage['last']['total_tokens']}；"
                f"累计输入 {usage['total']['input_tokens']}，累计总计 {usage['total']['total_tokens']}"
            ),
        ]
        if backend_runtime_error:
            lines.append(f'RAG runtime fallback: `{backend_runtime_error}`')
        self.renderer.print_markdown('\n\n'.join(lines))

    def _handle_models_command(self) -> None:
        if not self.model_options:
            self.renderer.print_markdown('No models found in `vip_config.json` for the current profile.')
            return
        selected_model = self.renderer.choose_model(self.model_options, getattr(self.agent, 'llm_model', self.model_options[0]))
        if not selected_model:
            self.renderer.print_markdown('Model switch canceled.')
            return
        if selected_model == getattr(self.agent, 'llm_model', ''):
            self.renderer.print_markdown(f'Current model remains `{selected_model}`.')
            return
        if self.on_model_switch is None:
            self.renderer.print_markdown('Model switching is unavailable in the current runtime.')
            return
        self.agent, self.supports_thinking = self.on_model_switch(selected_model)
        self.renderer.set_session_context(self.session_id, selected_model, mode_label='interactive cli')
        self.renderer.print_model_switched(selected_model)

    def _handle_skills_command(self) -> None:
        skill_loader = getattr(self.agent, 'skill_loader', None)
        skills = skill_loader.all() if skill_loader is not None else []
        self.renderer.print_skills(skills)

    def run(self) -> int:
        self.renderer.set_session_context(
            self.session_id,
            getattr(self.agent, 'llm_model', 'unknown'),
            mode_label='interactive cli',
        )
        self.renderer.print_banner(self.session_id, getattr(self.agent, 'llm_model', 'unknown'))
        while True:
            try:
                user_text = self.renderer.read_prompt('labagent> ').strip()
            except (EOFError, KeyboardInterrupt):
                self.renderer.finish_answer()
                return 0

            if not user_text:
                continue
            if user_text in {'/exit', '/quit'}:
                return 0
            if user_text == '/help':
                self.renderer.print_help()
                continue
            if user_text == '/session':
                self.renderer.print_markdown(f'Current session: `{self.session_id}`')
                continue
            if user_text == '/models':
                self._handle_models_command()
                continue
            if user_text == '/skills':
                self._handle_skills_command()
                continue
            if user_text.startswith('/add2lib'):
                self._handle_add2lib_command(user_text)
                continue

            self.renderer.print_user(user_text)
            self.session_service.append_user_message(self.session_id, user_text)
            messages = self.session_service.get_messages(self.session_id)
            task = self.session_store.start_task(self.session_id, user_text)
            self.renderer.begin_turn(user_text, task.task_id, mode_label='interactive cli')

            final_chunks: list[str] = []
            persisted_assistant_text = ''
            errored = False
            for event in self.agent.chat(
                messages=messages,
                reasoning_mode=self.reasoning_mode,
                supports_thinking=self.supports_thinking,
                session_store=self.session_store,
                session_id=self.session_id,
                task_id=task.task_id,
            ):
                self.renderer.render_event(event)
                if event.get('type') == 'answer_chunk':
                    final_chunks.append(str(event.get('content', '')))
                elif event.get('type') == 'final_message':
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
                elif event.get('type') == 'error':
                    errored = True

            final_text = ''.join(final_chunks).strip()
            text_to_persist = persisted_assistant_text or final_text
            if text_to_persist:
                self.session_service.append_assistant_message(self.session_id, text_to_persist)
            task_status = 'failed' if errored else 'completed'
            self.session_store.finish_task(
                self.session_id,
                task.task_id,
                text_to_persist,
                status=task_status,
            )
            task_record = self.session_store.get_task(self.session_id, task.task_id) or {}
            self.session_service.append_memory_card(
                self.session_id,
                task_id=task.task_id,
                prompt=user_text,
                answer=text_to_persist,
                tool_events=task_record.get('tool_events', []),
                has_image=False,
                status=task_status,
            )
            self.renderer.finish_turn(status=task_status, memory_saved=True)
