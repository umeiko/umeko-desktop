"""Explicit request formats, independent of provider names and effort vocabulary.

Adapted from earendil-works/pi v1.3.0,
packages/ai/src/api/openai-completions.ts (compatibility mapping and
resolveChatTemplateKwargs). Copyright (c) 2025 Mario Zechner, MIT.
Only documented fields needed by Umeko are retained; no host/model heuristics.
Native protocol adapters retain responsibility for their existing mappings.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
from __future__ import annotations

FORMAT_OPTIONS = [
    {"value": "openai", "label": "OpenAI (off: omit effort)"},
    {"value": "openai-none", "label": "OpenAI (off: none)"},
    {"value": "chat-template", "label": "Chat template kwargs"},
    {"value": "qwen", "label": "enable_thinking"},
    {"value": "deepseek", "label": "thinking.type enabled/disabled"},
    {"value": "anthropic-adaptive", "label": "Anthropic adaptive/disabled"},
]
OPENAI_FORMATS = tuple(option["value"] for option in FORMAT_OPTIONS
                       if option["value"] != "anthropic-adaptive")
_FORMATS = {*OPENAI_FORMATS, "anthropic-adaptive", "anthropic", "responses"}


def valid_format(value: object) -> bool:
    return isinstance(value, str) and value in _FORMATS


validformat = valid_format


def format_parameters(format: str, effort: str) -> dict:
    """Map the exact effort string; off is a separate action, not a rank."""
    if not valid_format(format):
        raise ValueError("Unknown thinking format")
    on = effort != "off"
    if format == "openai-none":
        return {"reasoning_effort": effort if on else "none"}
    if format in ("openai", "anthropic", "responses"):
        return {"reasoning_effort": effort} if on else {}
    if format == "chat-template":
        values = {"enable_thinking": on}
        if on:
            values["reasoning_effort"] = effort
        return {"chat_template_kwargs": values}
    if format == "qwen":
        values = {"enable_thinking": on}
    else:
        values = {"thinking": {"type": ("adaptive" if format == "anthropic-adaptive"
                                          else "enabled") if on else "disabled"}}
    if on:
        values["reasoning_effort"] = effort
    return values
