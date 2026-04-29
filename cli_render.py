from __future__ import annotations

import os
import sys
import time
from collections import deque
from contextlib import contextmanager

from rich.align import Align
from rich.columns import Columns
from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.markdown import Markdown
from rich.padding import Padding
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

try:
    from prompt_toolkit import PromptSession
except Exception:  # pragma: no cover - optional dependency fallback
    PromptSession = None

if os.name == 'nt':
    import msvcrt
else:
    import termios
    import tty


class CliRenderer:
    def __init__(self, console: Console | None = None):
        self.console = console or Console()
        self._prompt_session = PromptSession() if PromptSession is not None else None
        self._live: Live | None = None
        self._session_id = ''
        self._model_name = 'unknown'
        self._mode_label = 'interactive cli'
        self._reset_turn_state()

    def _reset_turn_state(self) -> None:
        self._turn_prompt = ''
        self._task_id = ''
        self._answer_buffer = ''
        self._reasoning_buffer = ''
        self._thought = 'Idle'
        self._active_tool = ''
        self._tool_count = 0
        self._turn_status = 'idle'
        self._memory_saved = False
        self._turn_started_at: float | None = None
        self._recent_events: deque[tuple[str, str]] = deque(maxlen=8)

    def _truncate_tool_result(self, output: object) -> str:
        text = str(output or '').strip()
        if len(text) <= 420:
            return text or '(empty)'
        return text[:420].rstrip() + '...'

    def _shorten(self, content: object, limit: int) -> str:
        text = str(content or '').strip().replace('\n', ' ')
        if len(text) <= limit:
            return text
        return text[:limit].rstrip() + '...'

    def _supports_pixel_art(self) -> bool:
        encoding = (getattr(sys.stdout, 'encoding', '') or '').lower()
        if 'utf-8' in encoding or 'utf8' in encoding:
            return True
        return bool(os.environ.get('WT_SESSION'))

    def _build_echo_logo_ascii(self) -> Text:
        return Text.from_markup(
            "[bright_cyan]            ___  ___            \n"
            "[bright_cyan]         .-########-.         \n"
            "[cyan]               .-####/====\\####-.       \n"
            "[cyan]            /#####/  /\\  \\#####\\      \n"
            "[bright_white]     /#####|  /--\\  |#####\\     \n"
            "[bright_white]    |######| | /\\ | |######|    \n"
            "[bright_white]    |######| | [][]| |######|    \n"
            "[bright_white]    |######| | \\//| |######|    \n"
            "[bright_cyan]     \\#####|  \\__/  |#####/     \n"
            "[bright_cyan]      \\#####\\______/#####/      \n"
            "[cyan]        '-####______####-'        \n"
            "[dark_orange]            --  --            \n"
        )

    def _build_echo_logo_pixel(self) -> Text:
        return Text.from_markup(
            "[bright_cyan]                  ▄▄▄▄▄▄▄▄▄                  \n"
            "[bright_cyan]              ▄███████████████▄              \n"
            "[cyan]        ▄███████▀▀▀       ▀▀▀███████▄        \n"
            "[cyan]  ▄▄▄▄█████▀                      ▀█████▄▄▄▄  \n"
            "[bright_white]      ▄████▀    ▄▄          ▄▄    ▀████▄      \n"
            "[bright_white]     ████▀    ▄████▄      ▄████▄    ▀████     \n"
            "[bright_white]    ████     ████████    ████████     ████    \n"
            "[bright_white]    ████     ███  ▀██    ██▀  ███     ████    \n"
            "[bright_white]    ████     ███▄▄▄██    ██▄▄▄███     ████    \n"
            "[bright_cyan]     ▀████▄    ▀████▀  ▄▄  ▀████▀    ▄████▀     \n"
            "[bright_cyan]      ▀████▄         ████         ▄████▀      \n"
            "[cyan]       ▄▄▄▄██████▄▄               ▄▄██████▀       \n"
            "[cyan]          ▀████████▄▄▄▄▄▄▄▄████████▀          \n"
            "[dark_orange]                    ▀▀  ▀▀                    \n"
        )

    def _build_echo_logo_pixel2(self) -> Text:
        return Text.from_markup(
            "[bright_cyan]                ▄▄▄▄▄▄▄                \n"
            "[bright_cyan]             ▄███████████▄             \n"
            "[bright_cyan]           ▄███████████████▄           \n"
            "[cyan]        ▄███████▀▀   ▀▀███████▄        \n"
            "[cyan]        ▄█████▀         ▀█████▄        \n"
            "[bright_white]        ████     ▄   ▄     ████        \n"
            "[bright_white]        ████    ██   ██    ████        \n"
            "[bright_white]        ████     ▀   ▀     ████        \n"
            "[bright_white]        ████               ████        \n"
            "[cyan]          ▀████▄       ▄████▀          \n"
            "[cyan]            ▀████▄▄▄▄▄████▀            \n"
            "[bright_cyan]             ▀███████████▀             \n"
            "[bright_cyan]                 ▀███▀                 \n"
            "\n"
        )

    def _build_echo_logo(self) -> Text:
        if self._supports_pixel_art():
            variant = os.environ.get('LABAGENT_CLI_LOGO_VARIANT', '1').strip()
            if variant == '2':
                return self._build_echo_logo_pixel2()
            return self._build_echo_logo_pixel()
        return self._build_echo_logo_ascii()

    def _build_wordmark(self) -> Text:
        return Text.from_markup(
            "[bold bright_cyan]"
            " _        _    ____    _    ____ _____ _   _ _____\n"
            "| |      / \\  | __ )  / \\  / ___| ____| \\ | |_   _|\n"
            "| |     / _ \\ |  _ \\ / _ \\| |  _|  _| |  \\| | | |  \n"
            "| |___ / ___ \\| |_) / ___ \\ |_| | |___| |\\  | | |  \n"
            "|_____/_/   \\_\\____/_/   \\_\\____|_____|_| \\_| |_|  \n"
            "[/bold bright_cyan]"
        )

    def _build_signature(self) -> Text:
        return Text.from_markup(
            "[dim]shared runtime / local coding agent[/dim]"
        )

    def _build_meta(self, session_id: str, model_name: str) -> Text:
        return Text.from_markup(
            f"[bold]Session[/bold]  [cyan]{session_id}[/cyan]\n"
            f"[bold]Model[/bold]    [magenta]{model_name}[/magenta]\n"
            f"[bold]Mode[/bold]     [green]{self._mode_label}[/green]"
        )

    def _build_logo_block(self, stage: int):
        logo = self._build_echo_logo() if stage >= 1 else Text("")
        return Padding(Align.center(logo), (1, 0, 1, 0))

    def _build_right_block(self, session_id: str, model_name: str, stage: int):
        parts: list[object] = []
        if stage >= 2:
            parts.append(self._build_wordmark())
        if stage >= 3:
            parts.append(Text(""))
            parts.append(self._build_signature())
        if stage >= 4:
            parts.append(self._build_meta(session_id, model_name))
        body = Group(*parts) if parts else Text("")
        return Padding(body, (1, 0, 1, 0))

    def _build_banner_content(self, session_id: str, model_name: str, stage: int) -> Columns:
        left = self._build_logo_block(stage)
        right = self._build_right_block(session_id, model_name, stage)
        return Columns([left, right], expand=True, equal=True, padding=(0, 2))

    def _build_banner(self, session_id: str, model_name: str, stage: int) -> Align:
        return Align.center(
            Panel(
                Padding(self._build_banner_content(session_id, model_name, stage), (0, 1)),
                title='[bold white]LabAgent Boot[/bold white]',
                subtitle='[dim]local coding runtime[/dim]',
                border_style='bright_cyan',
            )
        )

    def _build_model_picker(self, models: list[str], cursor: int, selected: int) -> Panel:
        rows: list[str] = [
            '[bold]Select model[/bold]',
            '[dim]Use Up/Down to move, Space to select, Enter to confirm, Esc to cancel.[/dim]',
            '',
        ]
        for index, model in enumerate(models):
            pointer = '[bright_white]>[/bright_white]' if index == cursor else ' '
            circle = '[blue]*[/blue]' if index == selected else '[dim]o[/dim]'
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
            if second not in {'[', 'O'}:
                return 'escape'
            sequence = ''
            while True:
                ch = sys.stdin.read(1)
                if not ch:
                    break
                sequence += ch
                if ch.isalpha() or ch == '~':
                    break
            final = sequence[-1:] if sequence else ''
            return {'A': 'up', 'B': 'down'}.get(final, '')
        return {' ': 'space', '\r': 'enter', '\n': 'enter'}.get(first, first)

    def _read_char(self) -> str:
        if os.name == 'nt':
            return msvcrt.getwch()
        return sys.stdin.read(1)

    def choose_model(self, models: list[str], current_model: str) -> str | None:
        if not models:
            return None
        selected = models.index(current_model) if current_model in models else 0
        cursor = selected
        with self._raw_keyboard():
            with self.console.screen(hide_cursor=True):
                while True:
                    self.console.print(self._build_model_picker(models, cursor, selected))
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
                    self.console.file.write('\x1b[H\x1b[J')
                    self.console.file.flush()

    def read_prompt(self, prompt: str = 'labagent> ') -> str:
        if self._prompt_session is not None:
            return self._prompt_session.prompt(prompt)
        buffer: list[str] = []
        cursor = 0
        out = self.console.file
        out.write(prompt)
        out.flush()
        with self._raw_keyboard():
            while True:
                ch = self._read_char()
                if ch in {'\r', '\n'}:
                    out.write('\n')
                    out.flush()
                    return ''.join(buffer)
                if ch == '\x03':
                    out.write('\n')
                    out.flush()
                    raise KeyboardInterrupt
                if ch == '\x04':
                    out.write('\n')
                    out.flush()
                    raise EOFError
                if ch in {'\x7f', '\b'}:
                    if cursor > 0:
                        cursor -= 1
                        buffer.pop(cursor)
                elif ch == '\x1b':
                    second = self._read_char()
                    if second in {'[', 'O'}:
                        third = self._read_char()
                        if third == 'D' and cursor > 0:
                            cursor -= 1
                        elif third == 'C' and cursor < len(buffer):
                            cursor += 1
                        elif third.isdigit():
                            while True:
                                tail = self._read_char()
                                if not tail or tail.isalpha() or tail == '~':
                                    break
                    else:
                        continue
                else:
                    if ch.isprintable():
                        buffer.insert(cursor, ch)
                        cursor += 1

                line = ''.join(buffer)
                out.write('\r')
                out.write(prompt)
                out.write(line)
                out.write(' ')
                out.write('\r')
                out.write(prompt)
                if cursor > 0:
                    out.write(line[:cursor])
                out.flush()

    def _elapsed_text(self) -> str:
        if self._turn_started_at is None:
            return '-'
        return f'{time.time() - self._turn_started_at:.1f}s'

    def _build_status_panel(self) -> Panel:
        table = Table.grid(padding=(0, 1))
        table.add_column(style='bold white')
        table.add_column(style='cyan')
        table.add_row('Session', self._session_id or '-')
        table.add_row('Model', self._model_name or '-')
        table.add_row('Task', self._task_id[:12] if self._task_id else '-')
        table.add_row('Status', self._turn_status)
        table.add_row('Tools', str(self._tool_count))
        table.add_row('Active', self._active_tool or '-')
        table.add_row('Memory', 'saved' if self._memory_saved else 'pending')
        table.add_row('Elapsed', self._elapsed_text())
        return Panel(table, title='Status', border_style='bright_blue')

    def _build_prompt_panel(self) -> Panel:
        prompt_text = self._turn_prompt or 'No active prompt.'
        body = Group(
            Text(self._shorten(prompt_text, 260) or '(empty)', style='white'),
            Text(''),
            Text(f'Thought: {self._shorten(self._thought, 180) or "-"}', style='dim'),
        )
        return Panel(body, title='Current Turn', border_style='blue')

    def _build_recent_activity_panel(self) -> Panel:
        if not self._recent_events:
            return Panel(Text('Waiting for events...', style='dim'), title='Recent Activity', border_style='cyan')
        rows: list[Text] = []
        for style, content in self._recent_events:
            rows.append(Text(content, style=style))
        return Panel(Group(*rows), title='Recent Activity', border_style='cyan')

    def _build_reasoning_panel(self) -> Panel:
        if not self._reasoning_buffer:
            content = Text('No reasoning surfaced.', style='dim')
        else:
            content = Text(self._shorten(self._reasoning_buffer, 1200), style='yellow')
        return Panel(content, title='Reasoning', border_style='yellow')

    def _build_answer_panel(self) -> Panel:
        answer_text = self._answer_buffer or 'Waiting for assistant output...'
        return Panel(Text(answer_text, style='white'), title='Assistant', border_style='green')

    def _build_runtime_layout(self) -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(name='top', size=9),
            Layout(name='body'),
            Layout(name='footer', size=4),
        )
        layout['top'].split_row(
            Layout(self._build_status_panel(), name='status', ratio=1),
            Layout(self._build_prompt_panel(), name='turn', ratio=2),
        )
        layout['body'].split_row(
            Layout(self._build_answer_panel(), name='answer', ratio=3),
            Layout(
                Group(
                    self._build_recent_activity_panel(),
                    self._build_reasoning_panel(),
                ),
                name='activity',
                ratio=2,
            ),
        )
        footer_text = Text.from_markup(
            '[dim]/help  /session  /models  /skills  /add2lib <文档路径>  /exit[/dim]'
        )
        layout['footer'].update(Panel(footer_text, title='Shortcuts', border_style='dim'))
        return layout

    def _sync_live(self) -> None:
        if self._live is not None:
            self._live.update(self._build_runtime_layout())

    def _start_live(self) -> None:
        if self._live is not None:
            return
        self._live = Live(
            self._build_runtime_layout(),
            console=self.console,
            refresh_per_second=12,
            transient=False,
        )
        self._live.start()

    def _stop_live(self) -> None:
        if self._live is None:
            return
        self._live.update(self._build_runtime_layout())
        self._live.stop()
        self._live = None

    def _push_event(self, style: str, content: str) -> None:
        self._recent_events.append((style, self._shorten(content, 180) or '(empty)'))

    def set_session_context(self, session_id: str, model_name: str, mode_label: str = 'interactive cli') -> None:
        self._session_id = session_id
        self._model_name = model_name
        self._mode_label = mode_label
        self._sync_live()

    def begin_turn(self, prompt: str, task_id: str, *, mode_label: str | None = None) -> None:
        self._reset_turn_state()
        self._turn_prompt = prompt
        self._task_id = task_id
        self._turn_status = 'running'
        self._turn_started_at = time.time()
        if mode_label is not None:
            self._mode_label = mode_label
        self._push_event('cyan', 'Turn started')
        self._start_live()
        self._sync_live()

    def print_banner(self, session_id: str, model_name: str) -> None:
        self.set_session_context(session_id, model_name)
        with Live(console=self.console, refresh_per_second=30, transient=True) as live:
            for stage, delay in ((1, 0.06), (2, 0.08), (3, 0.07), (4, 0.0)):
                live.update(self._build_banner(session_id, model_name, stage))
                if delay:
                    time.sleep(delay)
        self.console.print(self._build_banner(session_id, model_name, 4))
        self.console.print(Rule(style='dim blue'))
        self.console.print('[dim]输入 `/exit` 退出，输入 `/help` 查看说明，输入 `/models` 切换模型，输入 `/skills` 查看可用 skills，输入 `/add2lib <文档路径>` 导入知识库。[/dim]')

    def print_help(self) -> None:
        self.console.print(
            Panel.fit(
                '/exit  退出\n/help  显示帮助\n/session  显示当前 session id\n/models  交互式切换模型\n/skills  显示当前可用 skills\n/add2lib <文档路径>  导入 PDF / TXT / MD / DOCX 到知识库',
                title='Commands',
                border_style='green',
            )
        )

    def print_skills(self, skills: list[object]) -> None:
        if not skills:
            self.console.print(Panel.fit('No skills available.', title='Skills', border_style='yellow'))
            return
        lines: list[str] = []
        for skill in skills:
            lines.append(f"[bold cyan]{skill.name}[/bold cyan]")
            lines.append(f"  {skill.description}")
            lines.append(f"  [dim]{skill.location}[/dim]")
            lines.append('')
        self.console.print(Panel('\n'.join(lines[:-1]), title='Skills', border_style='bright_blue'))

    def render_event(self, event: dict) -> None:
        event_type = event.get('type')
        if self._live is None and event_type in {'thought', 'reasoning', 'tool_exec', 'tool_result', 'answer_chunk', 'error'}:
            self._start_live()

        if event_type == 'thought':
            self._thought = str(event.get('content', '')).strip() or 'Thinking'
            self._push_event('dim', f'Thought: {self._thought}')
            self._sync_live()
            return
        if event_type == 'reasoning':
            self._reasoning_buffer = str(event.get('content', '')).strip()
            self._push_event('yellow', 'Reasoning updated')
            self._sync_live()
            return
        if event_type == 'tool_exec':
            self._active_tool = str(event.get('tool', '')).strip()
            self._tool_count += 1
            payload = self._shorten(event.get('input', '{}'), 120)
            self._push_event('cyan', f'→ {self._active_tool}: {payload}')
            self._sync_live()
            return
        if event_type == 'tool_result':
            result_preview = self._truncate_tool_result(event.get('output', ''))
            tool_name = self._active_tool or 'tool'
            self._push_event('bright_cyan', f'← {tool_name}: {result_preview}')
            self._active_tool = ''
            self._sync_live()
            return
        if event_type == 'answer_chunk':
            content = str(event.get('content', ''))
            self._answer_buffer += content
            self._turn_status = 'responding'
            self._sync_live()
            return
        if event_type == 'error':
            self._turn_status = 'failed'
            self._active_tool = ''
            self._push_event('red', f"Error: {self._shorten(event.get('content', ''), 160)}")
            self._sync_live()
            return
        if event_type == 'final_message':
            return

        self._push_event('white', str(event))
        self._sync_live()

    def finish_turn(self, *, status: str, memory_saved: bool) -> None:
        if self._live is None and self._turn_status == 'idle' and not self._task_id:
            return
        self._turn_status = status
        self._memory_saved = memory_saved
        self._active_tool = ''
        if status == 'completed':
            self._push_event('green', 'Turn completed')
        else:
            self._push_event('red', f'Turn finished with status={status}')
        if memory_saved:
            self._push_event('green', 'Memory card saved')
        self._sync_live()
        self._stop_live()
        self.console.print(Rule(style='dim blue'))

    def finish_answer(self) -> None:
        if self._live is None:
            return
        self.finish_turn(status=self._turn_status or 'completed', memory_saved=self._memory_saved)

    def print_user(self, content: str) -> None:
        prompt = self._shorten(content, 220)
        self.console.print(Panel(Text(prompt, style='white'), title='You', border_style='bright_blue'))

    def print_session_list(self, records: list[dict]) -> None:
        if not records:
            self.console.print('[dim]No sessions found.[/dim]')
            return
        table = Table(title='Sessions', header_style='bold cyan')
        table.add_column('Session ID', style='cyan')
        table.add_column('Updated At', style='magenta')
        table.add_column('Messages', justify='right')
        table.add_column('Preview', overflow='fold')
        for record in records:
            preview = record.get('preview') or '(empty)'
            table.add_row(
                str(record.get('session_id', '')),
                str(record.get('updated_at', '')),
                str(record.get('message_count', 0)),
                self._shorten(preview, 100),
            )
        self.console.print(table)

    def print_markdown(self, content: str) -> None:
        self.console.print(Markdown(content))

    def print_model_switched(self, model_name: str) -> None:
        self._model_name = model_name
        self.console.print(Panel.fit(f'Model switched to [magenta]{model_name}[/magenta].', border_style='blue'))
