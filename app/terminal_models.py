"""The /models selector and the provider setup pages it opens."""
from __future__ import annotations

from pathlib import Path

from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.layout import ConditionalContainer, HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.widgets import TextArea


class ModelMenu:
    def __init__(self, ui):
        self.ui = ui
        self.page = ""
        self.rows = []
        self.index = 0
        self.efforts = {}
        self.tabs = []
        self.tab = 0
        self.fields = []
        self.values = {}
        self.field_index = 0
        self.action = ""
        self.in_flight = False
        self.editor = TextArea(multiline=False, height=1, prompt=self._prompt,
                               password=Condition(lambda: self.page == "form" and self.field == "key"))
        self.editor.buffer.on_text_changed += self._changed
        self.container = ConditionalContainer(HSplit([
            Window(char="─", height=1, style="class:accent"),
            Window(FormattedTextControl(self._panel), height=lambda: len(self._lines()), wrap_lines=False),
            self.editor,
        ]), filter=Condition(lambda: bool(self.page)))

    @property
    def field(self):
        return self.fields[self.field_index][0] if self.fields else ""

    def _prompt(self):
        if self.page == "form":
            return f"  {self.fields[self.field_index][1]}  ❯ "
        return "  Search  ❯ "

    def _changed(self, _):
        if self.page in ("models", "providers"):
            self.index = 0

    def _open(self, page):
        self.page = page
        self.index = 0
        self.editor.text = ""
        self.ui.app.layout.focus(self.editor)

    def close(self):
        self.page = ""
        self.editor.text = ""
        self.values.clear()
        self.ui.app.layout.focus(self.ui.editor)

    def show_models(self, models, alias):
        current = self.ui.state.get("pendingModel") or self.ui.state.get("model")
        if alias and not any(row["model"] == alias for row in models):
            self.ui.log.append(("class:error", f"Unknown model alias: {alias}"))
            return
        if not models:
            self.ui._request("provider", action="presets")
            return
        self.rows = [{**row, "label": row["model"], "detail": row["name"]} for row in models]
        self.rows.append({"label": "Add a provider…", "action": "presets"})
        self.tabs = [("", "All"), *dict((row["provider"], row["name"]) for row in models).items()]
        self.tab = 0
        self.efforts.clear()
        self._open("models")
        self.index = next((i for i, row in enumerate(self.rows) if row.get("model") == (alias or current)), 0)

    def show_providers(self, presets):
        self.rows = [{"label": row["name"], "detail": "API key", "preset": row["id"], "action": "save-preset"}
                     for row in presets]
        self.rows += [{"label": "Custom OpenAI-compatible", "action": "save-provider", "api": "openai"},
                      {"label": "Custom Anthropic-compatible", "action": "save-provider", "api": "anthropic"},
                      {"label": "Import provider ZIP", "action": "install"}]
        self._open("providers")

    def _matches(self):
        words = self.editor.text.casefold().split()
        provider = self.tabs[self.tab][0] if self.page == "models" else ""
        return [row for row in self.rows
                if (not provider or not row.get("provider") or row["provider"] == provider)
                and all(word in (row["label"] + " " + row.get("detail", "")).casefold() for word in words)]

    def _effort(self, row):
        alias = row["model"]
        levels = row["efforts"]
        if alias in self.efforts:
            return self.efforts[alias]
        state = self.ui.state
        if alias == (state.get("pendingModel") or state.get("model")):
            value = state.get("pendingEffort") or state.get("effort")
            if value in levels:
                return value
        return levels[len(levels) // 2]

    def _lines(self):
        if self.page == "form":
            header = ("class:accent", f"  {self.title}  ·  {self.field_index + 1}/{len(self.fields)}")
            hint = f"{self.ui.loading_frame} Saving…" if self.in_flight else "Enter continue · Esc cancel"
            return [header, ("class:muted", f"  {hint}")]
        title = "Select a model" if self.page == "models" else "Configure a provider"
        hints = "Type to search · ↑↓ navigate · Enter select · Esc cancel"
        if self.page == "models":
            hints = "↑↓ model · Enter apply · Esc cancel"
        if self.page == "models" and len(self.tabs) > 2:
            hints = "Tab provider · " + hints
        rows = [("class:accent", "  " + title), ("class:muted", "  " + hints)]
        if self.page == "models" and len(self.tabs) > 2:
            tabs = "   ".join(f"[{name}]" if i == self.tab else name for i, (_, name) in enumerate(self.tabs))
            rows.append(("class:muted", "  " + tabs))
        matches = self._matches()
        if not matches:
            return [*rows, ("class:muted", "  No matches")]
        limit = 9 if self.page == "providers" else 8
        page_size = min(limit, max(2, self.ui.app.output.get_size().rows - 12))
        start = min((self.index // page_size) * page_size, max(0, len(matches) - page_size))
        selected = matches[self.index]
        if self.page == "models" and selected.get("model"):
            levels = selected["efforts"]
            if len(levels) > 1:
                effort = self._effort(selected)
                options = "  ".join(f"[{level.capitalize()}]" if level == effort else level.capitalize()
                                   for level in levels)
                rows.append(("class:accent", f"  Thinking level   ← {options} →"))
            else:
                rows.append(("class:muted", "  Thinking level   Off · fixed for this model"))
        current = self.ui.state.get("pendingModel") or self.ui.state.get("model")
        for index in range(start, min(len(matches), start + page_size)):
            row = matches[index]
            label = row["label"]
            if row.get("detail"):
                label += f"  {row['detail']}"
            if row.get("model") and row["model"] == current:
                label += "  ← current"
            pointer = "❯" if index == self.index else " "
            rows.append(("class:accent" if index == self.index else "", f"  {pointer} {label}"))
        return rows

    def _panel(self):
        return FormattedText([(style, item + "\n") for style, item in self._lines()])

    def move(self, delta):
        matches = self._matches()
        if matches:
            self.index = (self.index + delta) % len(matches)

    def change_tab(self, delta):
        if len(self.tabs) > 2:
            self.tab = (self.tab + delta) % len(self.tabs)
            self.index = 0

    def think(self, delta):
        if self.page != "models":
            return
        matches = self._matches()
        if matches and (row := matches[self.index]).get("model"):
            levels = row["efforts"]
            index = levels.index(self._effort(row))
            index = min(len(levels) - 1, max(0, index + delta))
            self.efforts[row["model"]] = levels[index]

    def escape(self):
        if self.in_flight:
            return
        if self.page in ("models", "providers") and self.editor.text:
            self.editor.text = ""
        else:
            self.close()

    def submit(self):
        if self.page == "form":
            if not self.in_flight:
                self._submit_field()
            return
        matches = self._matches()
        if not matches:
            return
        row = matches[self.index]
        if row.get("model"):
            effort = self._effort(row)
            if self.ui._request("model", model=row["model"], effort=effort):
                self.close()
            return
        if row["action"] == "presets":
            self.ui._request("provider", action="presets")
            return
        self.action = row["action"]
        self.title = row["label"]
        self.field_index = 0
        if self.action == "save-preset":
            self.fields = [("key", "API key")]
            self.values = {"preset": row["preset"]}
        elif self.action == "install":
            self.fields = [("path", "Path to provider ZIP")]
            self.values = {}
        else:
            self.fields = [("name", "Provider name"), ("baseUrl", "Base URL"), ("models", "Model IDs (comma separated)"),
                           ("key", "API key")]
            self.values = {"api": row["api"]}
        self._open("form")

    def _submit_field(self):
        value = self.editor.text.strip()
        if not value:
            return
        if self.field == "path":
            path = Path(value).expanduser()
            if not path.is_absolute():
                path = Path(self.ui.state["cwd"]) / path
            try:
                path = path.resolve(strict=True)
                if path.suffix.lower() != ".zip" or not path.is_file():
                    raise ValueError("Choose a provider ZIP file.")
            except (OSError, ValueError) as error:
                self.ui.log.append(("class:error", str(error)))
                return
            value = str(path)
        elif self.field == "models":
            value = [{"upstream": model.strip(), "alias": ""} for model in value.split(",") if model.strip()]
            if not value:
                return
        values = {**self.values, self.field: value}
        self.editor.text = ""
        if self.field_index + 1 < len(self.fields):
            self.values = values
            self.field_index += 1
        else:
            self.in_flight = self.ui._request("provider", action=self.action, **values)

    def save_result(self, action, value, error):
        self.in_flight = False
        if error or value is False:
            self.ui.log.append(("class:error", str(error or "Could not save the provider.")))
            return
        self.close()
        if action == "install":
            self.ui.log.append(("class:success", f"Provider ZIP imported · {value}"))
        else:
            self.ui.log.append(("class:success", "Provider saved."))
            self.ui._request("models")
