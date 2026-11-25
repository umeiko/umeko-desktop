"""Interactive Umeko chat rendered in a terminal."""
from __future__ import annotations

import asyncio
from collections import deque
import os
import re
import time

from prompt_toolkit import Application
from prompt_toolkit.application import in_terminal
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import ConditionalContainer, Float, FloatContainer, HSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.output import ColorDepth
from prompt_toolkit.renderer import print_formatted_text
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import TextArea
from prompt_toolkit.utils import get_cwidth

from .project_info import VERSION
from .terminal_models import ModelMenu
from .terminal_viewport import TranscriptWindow

CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
LABEL = {"queued": "Queued", "running": "Running", "waiting": "Waiting", "completed": "Done",
         "failed": "Failed", "stopped": "Stopped"}
COMMANDS = {
    "/models": "Switch LLM model",
    "/compact": "Compact the conversation context",
}

# Kimi Code TUI's Braille frames and cadence (MIT, licenses/kimi-code-MIT.txt).
SPINNER_FRAMES = tuple("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏")
MOON_FRAMES = tuple("🌑🌒🌓🌔🌕🌖🌗🌘")
LOADER_SECONDS = 0.120
TICKER_SECONDS = 0.080

# Each character represents two vertically stacked pixels.
UMEKO_LOGO = (
    "▄██████████████▄",
    "████  ████  ████",
    "▀███▄▄████▄▄████",
    "  ▀████████████▀",
)
UMEKO_LOGO_COMPACT = (
    "▄████████████▄",
    "███  ████  ███",
    " ▀███████████▀",
)


def clean(value):
    return CONTROL.sub("", str(value or "")).replace("\t", "    ")


def _terminal_color_depth():
    configured = ColorDepth.from_env()
    if configured is not None:
        return configured
    if os.environ.get("COLORTERM", "").lower() in ("truecolor", "24bit"):
        return ColorDepth.DEPTH_24_BIT
    try:
        import curses
    except ImportError:
        return None
    try:
        curses.setupterm()
        colors = curses.tigetnum("colors")
    except curses.error:
        return None
    if colors < 1:
        return ColorDepth.DEPTH_1_BIT
    if colors < 256:
        return ColorDepth.DEPTH_4_BIT
    if colors >= 1 << 24:
        return ColorDepth.DEPTH_24_BIT
    return ColorDepth.DEPTH_8_BIT


class SlashCommands(Completer):
    def get_completions(self, document, _event):
        prefix = document.text_before_cursor
        if not prefix.startswith("/") or any(character.isspace() for character in prefix):
            return
        for command, description in COMMANDS.items():
            if command.startswith(prefix):
                yield Completion(command, -len(prefix), display_meta=description)


class TerminalUI:
    def __init__(self, client, state):
        self.client, self.state = client, state
        self.requests = {}
        self.log = deque(maxlen=12)
        self.model_notice = ""
        self.reviewing = False
        self.review_pages = 0
        self.inline_start = 0
        self.last_committed = None
        self.transcript_complete = True
        self.welcome_pending = not self.state.get("id")
        self.expanded = False
        self.show_agents = False
        self.messages = list(state.get("messages", ()))
        self.exit_armed = 0.0
        self.disconnected = False
        self.animation_start = None
        self.animation_frames = (0, 0)
        self.editor = TextArea(height=Dimension(min=1, max=7), multiline=True, wrap_lines=True,
                               prompt=[("class:accent", "❯ ")], completer=SlashCommands(),
                               complete_while_typing=True)
        self.editor.window.height = lambda: Dimension.exact(min(7, max(3, self.editor.text.count("\n") + 1)))
        self.transcript = TranscriptWindow(FormattedTextControl(self._transcript))
        self.model_menu = ModelMenu(self)
        self.picker_active = Condition(lambda: bool(self.model_menu.page))
        composer = ConditionalContainer(HSplit([
            Window(char="─", height=1, style="class:line"),
            self.editor,
        ]), filter=~self.picker_active)
        body = HSplit([
            Window(height=Dimension(min=0, preferred=0)),
            self.transcript,
            Window(FormattedTextControl(self._panels), height=self._panel_height, wrap_lines=False),
            composer,
            self.model_menu.container,
            Window(char="─", height=1, style="class:line"),
            Window(FormattedTextControl(self._footer), height=1),
        ])
        self.app = Application(
            layout=Layout(FloatContainer(body, floats=[
                Float(xcursor=True, ycursor=True, transparent=True, content=CompletionsMenu(max_height=2)),
            ]), focused_element=self.editor),
            key_bindings=self._keys(), full_screen=False, mouse_support=False,
            color_depth=_terminal_color_depth(),
            style=Style.from_dict({
                "header": "bold", "accent": "ansicyan bold", "line": "ansibrightblack",
                "logo": "#3b6cf6", "logo-ansi": "ansiblue",
                "muted": "ansibrightblack", "user": "ansicyan", "warn": "ansiyellow",
                "success": "ansigreen", "error": "ansired", "queue": "ansibrightblack",
                "thinking": "ansibrightblack italic",
            }),
        )

        self.app.after_render += self._apply_review_pages

    @property
    def loading_frame(self):
        frame = self.animation_frames[0]
        return SPINNER_FRAMES[frame % len(SPINNER_FRAMES)]

    def _progress_frame(self):
        waiting = self.state.get("phase") == "waiting"
        active_tool = any(tool.get("state") == "running" for row in self.messages[-2:]
                          for tool in row.get("tools", ()))
        if waiting or active_tool:
            return MOON_FRAMES[self.animation_frames[0] % len(MOON_FRAMES)]
        return self.loading_frame

    def _welcome(self):
        width = self.app.output.get_size().columns
        titles = ("Welcome to Umeko", "Type / for commands")
        title_width = max(map(get_cwidth, titles))
        if width < title_width:
            return [("class:accent", "Umeko\n")]
        framed = width >= title_width + 4
        interior = width - 2 if framed else width
        indent = "  " if framed else ""
        gap = "   "
        logo_space = interior - len(indent) - len(gap) - title_width
        logo = UMEKO_LOGO if logo_space >= len(UMEKO_LOGO[0]) else UMEKO_LOGO_COMPACT
        logo_width = max(map(get_cwidth, logo))
        if logo_space >= logo_width:
            side_titles = [""] * len(logo)
            start = (len(logo) - len(titles)) // 2
            side_titles[start:start + len(titles)] = titles
            values = list(zip(logo, side_titles, strict=True))
        else:
            values = [(row, "") for row in logo]
            values.extend(("", title) for title in titles)
        values.extend([
            ("", ""),
            ("", "Directory  " + clean(self.state["cwd"])),
            ("", "Session    " + clean(self.state.get("id") or "New conversation")),
            ("", "Model      " + clean(self.state.get("model") or "Configure with /models")),
            ("", "Version    " + VERSION + " · Experimental"),
        ])
        logo_style = (
            "class:logo-ansi" if self.app.color_depth == ColorDepth.DEPTH_4_BIT else "class:logo"
        )
        rows = [("class:accent", "╭" + "─" * interior + "╮\n")] if framed else []
        for logo_row, line in values:
            spacing = gap if logo_row and line else ""
            padding = len(indent) + (logo_width if logo_row else 0) + len(spacing)
            while padding + get_cwidth(line) > interior:
                line = line[:-1]
            if framed:
                rows.extend([("class:accent", "│"), ("", indent)])
            if logo_row:
                rows.extend([(logo_style, logo_row.ljust(logo_width)), ("", spacing)])
            rows.append(("", line))
            if framed:
                rows.extend([("", " " * (interior - padding - get_cwidth(line))), ("class:accent", "│")])
            rows.append(("", "\n"))
        if framed:
            rows.append(("class:accent", "╰" + "─" * interior + "╯\n"))
        return rows

    def _format_messages(self, rows, *, expanded=False):
        text = []
        for row in rows:
            body = clean(row.get("text"))
            thinking = clean(row.get("thinking"))
            if thinking:
                live = row is self.messages[-1] and self.state.get("busy") and not body and not row.get("tools")
                text.append(("class:thinking", "\n ◇ Thinking…\n" if live else "\n ◇ Thinking · Ctrl+O\n"))
                if live or expanded:
                    text.append(("class:thinking", " " + thinking + "\n"))
            if row.get("role") == "user":
                text.append(("class:user", f"\n ❯ {body}\n"))
            elif body:
                text.append(("class:error" if row.get("error") else "", f"\n {body}\n"))
            if row.get("compaction"):
                detail = row["compaction"]
                failed = detail.get("state") == "failure"
                style = "class:error" if failed else "class:muted"
                title = f"\n ◇ Context compaction · {clean(detail.get('state'))}\n"
                text.append((style, title))
                if failed and detail.get("error"):
                    text.append((style, "   " + clean(detail["error"]) + "\n"))
                elif expanded and detail.get("summary"):
                    text.append((style, clean(detail["summary"]) + "\n"))
            for tool in row.get("tools", []):
                indicator = {"done": "✓", "error": "✕", "running": self.loading_frame}.get(tool.get("state"), "·")
                text.append(("class:muted", f" {indicator} {clean(tool.get('name'))} {clean(tool.get('path'))}\n"))
                if expanded and tool.get("result"):
                    text.append(("class:muted", clean(tool["result"]) + "\n"))
        return text

    def _transcript(self):
        start = 0 if self.reviewing else self.inline_start
        text = self._format_messages(self.messages[start:], expanded=self.expanded)
        for style, message in self.log:
            text.append((style, message + "\n"))
        return FormattedText(text)

    @staticmethod
    def _row_key(row):
        return (row.get("entryId"), row.get("role"), hash(row.get("text", "")),
                hash(row.get("thinking", "")), tuple(tool.get("id") for tool in row.get("tools", [])),
                row.get("compaction", {}).get("eventId") if row.get("compaction") else None)

    async def _flush_scrollback(self):
        if self.reviewing or not self.transcript_complete:
            return
        if self.last_committed is not None:
            # Replaying an earlier indexed page can move the bookmark. A
            # missing bookmark leaves the full authoritative view inspectable.
            start = self.inline_start
            if not 0 < start <= len(self.messages) or self._row_key(self.messages[start - 1]) != self.last_committed:
                start = next((i + 1 for i in range(len(self.messages) - 1, -1, -1)
                              if self._row_key(self.messages[i]) == self.last_committed), 0)
            self.inline_start = start
            if not start:
                return
        end = len(self.messages)
        if self.state.get("busy"):
            end = next((i for i in range(end - 1, self.inline_start - 1, -1)
                        if self.messages[i]["role"] == "user"), self.inline_start)
        fragments = self._welcome() if self.welcome_pending else []
        self.welcome_pending = False
        if end > self.inline_start:
            fragments.extend(self._format_messages(self.messages[self.inline_start:end]))
            self.last_committed = self._row_key(self.messages[end - 1])
            self.inline_start = end
        if fragments:
            async with in_terminal():
                print_formatted_text(self.app.output, FormattedText(fragments), self.app.style,
                                     color_depth=self.app.color_depth)

    def _show_review(self):
        if not self.reviewing:
            self.reviewing = True
            self.transcript.anchor = None

    def _leave_review(self):
        self.reviewing = False
        self.review_pages = 0
        self.expanded = False
        self.transcript.anchor = None

    def _apply_review_pages(self, _):
        if self.review_pages:
            for _ in range(self.review_pages):
                self.transcript.scroll_page(-1)
            self.review_pages = 0
            self.app.invalidate()

    def _panel_lines(self):
        rows = []
        if self.reviewing:
            rows.append(("class:muted", "  History · PgUp / PgDn · Ctrl+End follow latest"))
        if self.model_notice:
            rows.append(("class:success", self.model_notice))
        approval = self.state.get("approval") or {}
        if approval:
            detail = clean(approval.get("detail")).partition("\n")[0]
            rows.append(("class:warn", f"  {clean(approval.get('title') or 'Action required')}  {detail}"))
            options = approval.get("options") or []
            if options:
                rows += [("class:warn", f"    {index + 1}. {clean(option)}") for index, option in enumerate(options[:7])]
            elif approval.get("method") == "confirm":
                rows.append(("class:warn", "    Enter y to approve · n to decline"))
        queue = self.state.get("queue") or []
        if queue:
            rows.append(("class:queue", f"  Queued ({len(queue)})  ·  Ctrl+S steer"))
            for item in queue[-4:]:
                title = "/compact" if item.get("mode") == "compact" else ""
                preview = " ".join(clean(item.get("text")).split())[:98]
                rows.append(("class:queue", f"    ↳ {title} {preview}"))
        agents = self.state.get("agents") or []
        if agents:
            counts = {status: sum(row["status"] == status for row in agents) for status in LABEL}
            detail = " · ".join(f"{count} {LABEL[status].lower()}" for status, count in counts.items() if count)
            spinner = SPINNER_FRAMES[self.animation_frames[1]] + " " if counts["running"] else ""
            rows.append(("class:accent", f"  {spinner}Subagents  {detail}  ·  Ctrl+B details"))
            if self.show_agents:
                for row in agents[-6:]:
                    task = " ".join(clean(row.get("task")).split())[:56]
                    rows.append(("class:muted", f"    {clean(row['name'])} · {LABEL.get(row['status'], clean(row['status']))} {task}"))
        if self.state.get("busy"):
            status = ("Waiting for a background job" if self.state.get("phase") == "waiting" else
                      self.state.get("status") or self.state.get("phase") or "Working")
            rows.append(("class:muted", f"  {self._progress_frame()} {clean(status)}"))
        return rows

    def _panel_height(self):
        return min(17, len(self._panel_lines()))

    def _panels(self):
        return FormattedText([(style, text + "\n") for style, text in self._panel_lines()[:17]])

    def _footer(self):
        if self.disconnected:
            return FormattedText([("class:warn", "  Desktop connection closed  ·  Ctrl+D exit")])
        usage = self.state.get("usage") or {}
        percent = usage.get("percent")
        model = self.state.get("pendingModel") or self.state.get("model") or "No model"
        effort = self.state.get("pendingEffort") or self.state.get("effort")
        status = f"{clean(model)}  {clean(effort)}"
        commands = "  │  / Commands"
        width = self.app.output.get_size().columns - 2
        if isinstance(percent, (int, float)):
            context = f"  │  Context {percent:.0f}%"
            if get_cwidth(status + context + commands) <= width:
                status += context
        workspace = clean(self.state.get("cwd"))
        divider = "  │  "
        budget = width - get_cwidth(status + divider + commands)
        if workspace and budget >= 8:
            if get_cwidth(workspace) > budget:
                workspace = "…" + workspace[-(budget - 1):]
                while get_cwidth(workspace) > budget:
                    workspace = "…" + workspace[2:]
            status = workspace + divider + status
        return FormattedText([("class:muted", "  " + status), ("class:accent", commands)])

    def _keys(self):
        keys = KeyBindings()

        @keys.add("up", filter=self.picker_active)
        def model_up(_):
            if self.model_menu.page != "form":
                self.model_menu.move(-1)

        @keys.add("down", filter=self.picker_active)
        def model_down(_):
            if self.model_menu.page != "form":
                self.model_menu.move(1)

        choose_effort = Condition(lambda: self.model_menu.page == "models")

        @keys.add("tab", filter=choose_effort)
        def next_provider(_):
            self.model_menu.change_tab(1)

        @keys.add("s-tab", filter=choose_effort)
        def previous_provider(_):
            self.model_menu.change_tab(-1)

        @keys.add("left", filter=choose_effort)
        def less_thinking(_):
            self.model_menu.think(-1)

        @keys.add("right", filter=choose_effort)
        def more_thinking(_):
            self.model_menu.think(1)

        @keys.add("escape", filter=self.picker_active)
        @keys.add("c-c", filter=self.picker_active)
        def dismiss_picker(_):
            self.model_menu.escape()

        @keys.add("enter", filter=self.picker_active)
        def select_model(_):
            self.model_menu.submit()

        @keys.add("enter", filter=~self.picker_active)
        def submit(_):
            completion = self.editor.buffer.complete_state
            if completion and completion.completions:
                self.editor.buffer.apply_completion(completion.current_completion or completion.completions[0])
            self._submit(False)

        @keys.add("c-s", filter=~self.picker_active)
        def steer(_):
            self._submit(True)

        @keys.add("c-q", filter=~self.picker_active)
        def queue(_):
            self._submit(False, hold=True)

        @keys.add("c-j", filter=~self.picker_active)
        @keys.add("escape", "enter", filter=~self.picker_active)
        def newline(_):
            self.editor.buffer.insert_text("\n")

        @keys.add("c-o")
        def tools(_):
            self.expanded = not self.expanded
            if self.expanded:
                self._show_review()
            elif self.transcript.anchor is None:
                self._leave_review()

        @keys.add("c-b")
        def children(_):
            self.show_agents = not self.show_agents

        @keys.add("pageup")
        def up(_):
            if not self.reviewing or self.review_pages:
                self._show_review()
                self.review_pages += 1
            elif self.transcript.anchor == (0, 0) and self.state.get("historyEarlier"):
                self._request("history")
            else:
                self.transcript.scroll_page(-1)

        @keys.add("pagedown")
        def down(_):
            if self.reviewing:
                self.transcript.scroll_page(1)
                if self.transcript.anchor is None and not self.expanded:
                    self._leave_review()

        @keys.add("c-end")
        def follow(_):
            self._leave_review()

        @keys.add("c-c", filter=~self.picker_active)
        def interrupt(event):
            if self.disconnected:
                event.app.exit()
            elif self.state.get("busy"):
                self._request("abort")
            elif self.editor.text:
                self.editor.text = ""
            elif time.monotonic() < self.exit_armed:
                event.app.exit()
            else:
                self.exit_armed = time.monotonic() + 2
                self.log.append(("class:muted", "Press Ctrl+C again to exit"))

        @keys.add("c-d", filter=~self.picker_active)
        def exit_or_delete(event):
            if self.editor.text and not self.disconnected:
                self.editor.buffer.delete()
            else:
                event.app.exit()

        return keys

    def _request(self, operation, restore="", *, alias="", **parameters):
        try:
            identifier = self.client.send(operation, **parameters)
        except OSError as error:
            self.log.append(("class:error", clean(error)))
            return False
        self.requests[identifier] = (operation, restore, parameters.get("action", ""), alias)
        return True

    def _submit(self, steer, *, hold=False):
        if self.disconnected:
            return
        text = self.editor.text.strip()
        if steer and (not self.state.get("busy") or self.state.get("approval")):
            return
        approval = self.state.get("approval") or {}
        if approval:
            method = approval.get("method")
            value = text
            if method == "confirm" and text.lower() in ("y", "n", "yes", "no"):
                value = text.lower() in ("y", "yes")
            elif method == "select" and text.isdecimal() and 0 < int(text) <= len(approval.get("options") or []):
                value = approval["options"][int(text) - 1]
            elif method in ("confirm", "select") or not text:
                return
            self._request("answer", restore=text, approval=approval["id"], value=value)
        elif text.startswith("/") and self._command(text):
            pass
        elif text or steer:
            if not self._request("steer" if steer else "send", restore=text, text=text, hold=hold):
                return
            if text:
                self.model_notice = ""
                self._leave_review()
        else:
            return
        self.editor.text = ""

    def _command(self, text):
        command, *args = text.split(maxsplit=1)
        argument = args[0] if args else ""
        if command == "/models":
            self._request("models", alias=argument)
        elif command == "/compact":
            self._request("compact", restore=text, text=argument)
        else:
            return False
        return True

    def _restore(self, text):
        if text:
            self.editor.text = "\n\n".join(filter(None, (text, self.editor.text)))
            self.editor.buffer.cursor_position = len(self.editor.text)

    def _handle(self, frame):
        if frame.get("event") == "transcript":
            self.transcript_complete = bool(frame.get("complete"))
            if "keep" in frame:
                del self.messages[frame["keep"]:]
            elif "row" in frame:
                self.messages.append({**frame["row"], "text": "", "thinking": ""})
            elif "field" in frame and self.messages:
                self.messages[-1][frame["field"]] += frame["append"]
        elif frame.get("event") == "state":
            state = frame["state"]
            if state.get("busy") and not self.state.get("busy"):
                self.model_notice = ""
            self.state = state
        elif frame.get("event") in ("queue_rejected", "queue_returned"):
            self._restore(frame.get("text") or "\n\n".join([*frame.get("steering", []), *frame.get("followUp", [])]))
            if frame.get("message"):
                self.log.append(("class:warn", clean(frame["message"])))
        elif frame.get("event") == "notice":
            self.log.append(("class:muted", clean(frame.get("message"))))
        elif frame.get("id") in self.requests:
            operation, restore, action, alias = self.requests.pop(frame["id"])
            value, error = frame.get("result"), frame.get("error")
            if operation == "provider" and action != "presets":
                self.model_menu.save_result(action, value, clean(error))
            elif error:
                self._restore(restore)
                self.log.append(("class:error", clean(error)))
            elif operation == "model" and isinstance(value, dict):
                status = "Next turn" if value.get("pending") else "Selected"
                self.model_notice = f"  {status} · {clean(value.get('model'))} · Thinking {clean(value.get('effort')).capitalize()}"
            elif operation == "models":
                rows = [{**row, "name": clean(row["name"]).replace("\n", " ")} for row in value]
                self.model_menu.show_models(rows, clean(alias))
            elif operation == "provider":
                rows = [{**row, "name": clean(row["name"]).replace("\n", " ")} for row in value]
                self.model_menu.show_providers(rows)

    def _animate(self):
        busy = self.state.get("busy") or self.model_menu.in_flight
        children_running = any(row.get("status") == "running" for row in self.state.get("agents", ()))
        if busy or children_running:
            now = time.monotonic()
            if self.animation_start is None:
                self.animation_start = now
            elapsed = now - self.animation_start
            frames = (int(elapsed / LOADER_SECONDS) if busy else 0,
                      int(elapsed / TICKER_SECONDS) % len(SPINNER_FRAMES) if children_running else 0)
        else:
            self.animation_start = None
            frames = (0, 0)
        changed = frames != self.animation_frames
        self.animation_frames = frames
        return changed

    async def _poll(self):
        while self.client.alive:
            refresh = False
            for frame in self.client.read():
                refresh = True
                self._handle(frame)
            await self._flush_scrollback()
            if self._animate() or refresh:
                self.app.invalidate()
            await asyncio.sleep(0.036)
        self.disconnected = True
        if self.model_menu.page:
            self.model_menu.in_flight = False
            self.model_menu.close()
        self.state = {**self.state, "busy": False, "approval": {}, "agents": []}
        self.animation_frames = (0, 0)
        self.app.invalidate()

    async def run(self):
        self._request("transcript")
        self.app.create_background_task(self._poll())
        await self.app.run_async()


def run(client, state):
    asyncio.run(TerminalUI(client, state).run())
