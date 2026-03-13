from __future__ import annotations

import os
import sys
import time
from contextlib import contextmanager

from rich.align import Align
from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.padding import Padding
from rich.panel import Panel
from rich.rule import Rule
from rich.syntax import Syntax
from rich.text import Text

if os.name == 'nt':
    import msvcrt
else:
    import termios
    import tty


class CliRenderer:
    def __init__(self, console: Console | None = None):
        self.console = console or Console()
        self._answer_started = False

    def _build_bot_mark(self) -> Text:
        return Text.from_markup(
            "[bold bright_white]              __              \n"
            "[bold bright_white]         _.-'  '-._         \n"
            "[bold cyan]      _.-'   .--.   '-._      \n"
            "[bold cyan]    .'      / /\\ \\      '.    \n"
            "[bold bright_white]   /  _..-'/ [cyan]/  \\\\[/cyan] '\\-.._  \\\n"
            "[bold bright_white]  |.-' __ /  [bright_white].--.[/bright_white]  \\\\ __'-.|\n"
            "[bold cyan]  /   .'/  | [bright_white]/ .. \\\\[/bright_white] |  \\\\'.   \\\n"
            "[bold cyan] |   / /   | [bright_white]\\\\_--_//[/bright_white] |   \\\\ \\   |\n"
            "[bold bright_white]  \\\\  \\\\_.-'/_.-.__.-._\\\\'-._//  /\n"
            "[bold bright_white]   '._   _.'   /__\\\\   '._   _.' \n"
            "[bold bright_white]      '-.'    /_/  \\_\\\\    '.-'    \n"
        )

    def _build_logo(self) -> Text:
        return Text.from_markup(
            "[bold cyan]"
            "  _          _      _                    _   \n"
            " | |    __ _| |__  / \\   __ _  ___ _ __ | |_ \n"
            " | |   / _` | '_ \\ / _ \\ / _` |/ _ \\ '_ \\| __|\n"
            " | |__| (_| | |_) / ___ \\ (_| |  __/ | | | |_ \n"
            " |_____\\__,_|_.__/_/   \\_\\__, |\\___|_| |_|\\__|\n"
            "                         |___/                \n"
            "[/bold cyan]"
        )

    def _build_signature(self) -> Text:
        return Text.from_markup("[dim]crafted by[/dim] [italic bright_white]Vonct[/italic bright_white]")

    def _build_meta(self, session_id: str, model_name: str) -> Text:
        return Text.from_markup(
            f"[bold]Session[/bold]  [cyan]{session_id}[/cyan]\n"
            f"[bold]Model[/bold]    [magenta]{model_name}[/magenta]\n"
            "[bold]Mode[/bold]     [green]interactive cli[/green]"
        )

    def _build_banner(self, session_id: str, model_name: str, stage: int) -> Align:
        parts: list[object] = []
        if stage >= 1:
            parts.append(self._build_bot_mark())
        if stage >= 2:
            parts.append(self._build_logo())
        if stage >= 3:
            parts.append(self._build_signature())
        if stage >= 4:
            parts.append(self._build_meta(session_id, model_name))
        body = Group(*parts) if parts else Text("")
        return Align.center(
            Panel(
                Padding(body, (0, 1)),
                title="[bold white]LabAgent[/bold white]",
                subtitle="[dim]local coding runtime[/dim]",
                border_style="bright_blue",
            )
        )

    def _build_model_picker(self, models: list[str], cursor: int, selected: int) -> Panel:
        rows: list[str] = [
            '[bold]Select model[/bold]',
            '[dim]Use Up/Down to move, Space to select, Enter to confirm, Esc to cancel.[/dim]',
            '',
        ]
        for index, model in enumerate(models):
            pointer = '[bright_white]›[/bright_white]' if index == cursor else ' '
            circle = '[blue]●[/blue]' if index == selected else '[dim]○[/dim]'
            style_open = '[bold white]' if index == cursor else ''
            style_close = '[/bold white]' if index == cursor else ''
            rows.append(f'{pointer} {circle} {style_open}{model}{style_close}')
        return Panel('\n'.join(rows), border_style='bright_blue', title='Models')

    @contextmanager
    def _raw_keyboard(self):
        if os.name == 'nt':
            yield
            return
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            yield
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    def _read_key(self) -> str:
        if os.name == 'nt':
            first = msvcrt.getwch()
            if first in ('\x00', '\xe0'):
                second = msvcrt.getwch()
                return {'H': 'up', 'P': 'down'}.get(second, '')
            return {' ': 'space', '\r': 'enter', '\x1b': 'escape'}.get(first, first)

        first = sys.stdin.read(1)
        if first == '\x1b':
            second = sys.stdin.read(1)
            if second != '[':
                return 'escape'
            third = sys.stdin.read(1)
            return {'A': 'up', 'B': 'down'}.get(third, '')
        return {' ': 'space', '\r': 'enter', '\n': 'enter'}.get(first, first)

    def choose_model(self, models: list[str], current_model: str) -> str | None:
        if not models:
            return None
        selected = models.index(current_model) if current_model in models else 0
        cursor = selected
        with self._raw_keyboard():
            with Live(self._build_model_picker(models, cursor, selected), console=self.console, refresh_per_second=20, transient=True) as live:
                while True:
                    key = self._read_key()
                    if key == 'up':
                        cursor = (cursor - 1) % len(models)
                    elif key == 'down':
                        cursor = (cursor + 1) % len(models)
                    elif key == 'space':
                        selected = cursor
                    elif key == 'enter':
                        return models[selected]
                    elif key in {'escape', 'q'}:
                        return None
                    live.update(self._build_model_picker(models, cursor, selected))

    def print_banner(self, session_id: str, model_name: str) -> None:
        with Live(console=self.console, refresh_per_second=30, transient=True) as live:
            for stage, delay in ((1, 0.06), (2, 0.08), (3, 0.07), (4, 0.0)):
                live.update(self._build_banner(session_id, model_name, stage))
                if delay:
                    time.sleep(delay)
        self.console.print(self._build_banner(session_id, model_name, 4))
        self.console.print(Rule(style="dim blue"))
        self.console.print("[dim]输入 `/exit` 退出，输入 `/help` 查看说明，输入 `/models` 切换模型。[/dim]")

    def print_help(self) -> None:
        self.console.print(
            Panel.fit(
                '/exit  退出\n/help  显示帮助\n/session  显示当前 session id\n/models  交互式切换模型',
                title='Commands',
                border_style='green',
            )
        )

    def render_event(self, event: dict) -> None:
        event_type = event.get('type')
        if event_type == 'thought':
            self.console.print(f"[dim]{event.get('content', '')}[/dim]")
            return
        if event_type == 'reasoning':
            self.console.print(Panel(event.get('content', ''), title='Reasoning', border_style='yellow'))
            return
        if event_type == 'tool_exec':
            syntax = Syntax(event.get('input', '{}'), 'json', word_wrap=True)
            self.console.print(Panel(syntax, title=f"Tool: {event.get('tool', '')}", border_style='cyan'))
            return
        if event_type == 'tool_result':
            self.console.print(Panel(event.get('output', ''), title='Tool Result', border_style='cyan'))
            return
        if event_type == 'answer_chunk':
            content = event.get('content', '')
            if not self._answer_started:
                self.console.print('[bold green]Assistant[/bold green]')
                self._answer_started = True
            self.console.print(content, end='')
            return
        if event_type == 'error':
            self.console.print(Panel(event.get('content', ''), title='Error', border_style='red'))
            return
        self.console.print(Text(str(event)))

    def finish_answer(self) -> None:
        if self._answer_started:
            self.console.print()
        self._answer_started = False

    def print_user(self, content: str) -> None:
        self.console.print(f'[bold blue]You[/bold blue]: {content}')

    def print_session_list(self, records: list[dict]) -> None:
        if not records:
            self.console.print('[dim]No sessions found.[/dim]')
            return
        for record in records:
            preview = record.get('preview') or '(empty)'
            self.console.print(
                Panel(
                    f"[cyan]{record.get('session_id', '')}[/cyan]\n{preview}\n"
                    f"messages={record.get('message_count', 0)} updated_at={record.get('updated_at', '')}",
                    border_style='blue',
                )
            )

    def print_markdown(self, content: str) -> None:
        self.console.print(Markdown(content))

    def print_model_switched(self, model_name: str) -> None:
        self.console.print(Panel.fit(f'Model switched to [magenta]{model_name}[/magenta].', border_style='blue'))
