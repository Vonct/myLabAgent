from __future__ import annotations

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
        self.renderer.print_model_switched(selected_model)

    def run(self) -> int:
        self.renderer.print_banner(self.session_id, getattr(self.agent, 'llm_model', 'unknown'))
        while True:
            try:
                user_text = input('labagent> ').strip()
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

            self.renderer.print_user(user_text)
            self.session_service.append_user_message(self.session_id, user_text)
            messages = self.session_service.get_messages(self.session_id)
            task = self.session_store.start_task(self.session_id, user_text)

            final_chunks: list[str] = []
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
                elif event.get('type') == 'error':
                    errored = True

            self.renderer.finish_answer()
            final_text = ''.join(final_chunks).strip()
            if final_text:
                self.session_service.append_assistant_message(self.session_id, final_text)
            self.session_store.finish_task(
                self.session_id,
                task.task_id,
                final_text,
                status='failed' if errored else 'completed',
            )
