"""Incremental SSE and compatible OpenAI/Anthropic message conversion."""
from __future__ import annotations

import codecs
import json


def iter_sse(chunks):
    decoder = codecs.getincrementaldecoder("utf-8")()
    buffer, lines = "", []
    for chunk in chunks:
        buffer += decoder.decode(chunk) if isinstance(chunk, bytes) else chunk
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            line = line.rstrip("\r")
            if not line:
                if lines:
                    value = "\n".join(lines)
                    if value != "[DONE]":
                        yield json.loads(value)
                    lines = []
            elif line.startswith("data:"):
                lines.append(line[5:].lstrip(" "))
    buffer += decoder.decode(b"", final=True)
    if buffer.startswith("data:"):
        lines.append(buffer[5:].strip())
    if lines and "\n".join(lines) != "[DONE]":
        yield json.loads("\n".join(lines))


def response_events(response):
    if "event-stream" not in response.headers.get("Content-Type", ""):
        raw = response.read(16 * 1024 * 1024)
        if raw.lstrip().startswith(b"{"):
            yield json.loads(raw)
        else:
            yield from iter_sse([raw])
        return
    def chunks():
        read = getattr(response, "read1", response.read)
        while part := read(8192):
            yield part
    yield from iter_sse(chunks())


def collect_openai(events):
    text, thinking, calls, finish, usage = [], [], {}, "stop", {}
    final = None
    for event in events:
        if event.get("error"):
            raise ValueError("上游流返回错误")
        usage.update(event.get("usage") or {})
        for choice in event.get("choices") or []:
            if choice.get("message") is not None:
                final = choice["message"]
            delta = choice.get("delta") or {}
            if delta.get("content"):
                text.append(delta["content"])
            reasoning = delta.get("reasoning_content") or delta.get("reasoning") or delta.get("reasoning_text")
            if reasoning:
                thinking.append(reasoning)
            for call in (delta.get("tool_calls") or []):
                slot = calls.setdefault(call.get("index", 0), {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                if call.get("id"):
                    slot["id"] += call["id"]
                for key in ("name", "arguments"):
                    slot["function"][key] += call.get("function", {}).get(key, "")
            finish = choice.get("finish_reason") or finish
    message = final or {"role": "assistant", "content": "".join(text), **({"tool_calls": list(calls.values())} if calls else {})}
    reasoning = message.get("reasoning_content") or message.get("reasoning") or message.get("reasoning_text") or "".join(thinking)
    if reasoning:
        message = {**message, "reasoning_content": reasoning}
    return {"choices": [{"message": message, "finish_reason": finish}], "usage": usage}


def anthropic_events_to_openai(events):
    tool_indices, next_tool = {}, 0
    for event in events:
        kind = event.get("type")
        if kind == "error":
            raise ValueError("供应商流返回错误")
        delta, usage, finish = {}, {}, None
        if kind == "message_start":
            usage = {"prompt_tokens": event["message"].get("usage", {}).get("input_tokens", 0)}
            delta = {"role": "assistant"}
        elif kind == "content_block_start" and event["content_block"]["type"] == "tool_use":
            block = event["content_block"]
            tool_indices[event["index"]] = next_tool
            delta = {"tool_calls": [{"index": next_tool, "id": block["id"], "type": "function", "function": {"name": block["name"], "arguments": ""}}]}
            next_tool += 1
        elif kind == "content_block_start" and event["content_block"]["type"] == "thinking":
            delta = {"reasoning_content": event["content_block"].get("thinking", "")}
        elif kind == "content_block_delta":
            part = event["delta"]
            if part["type"] == "text_delta":
                delta = {"content": part["text"]}
            elif part["type"] == "thinking_delta":
                delta = {"reasoning_content": part["thinking"]}
            elif part["type"] == "input_json_delta":
                delta = {"tool_calls": [{"index": tool_indices[event["index"]], "function": {"arguments": part["partial_json"]}}]}
        elif kind == "message_delta":
            finish = {"end_turn": "stop", "stop_sequence": "stop", "max_tokens": "length", "tool_use": "tool_calls"}.get(event["delta"].get("stop_reason"), "stop")
            usage = {"completion_tokens": event.get("usage", {}).get("output_tokens", 0)}
            if "input_tokens" in event.get("usage", {}):
                usage["prompt_tokens"] = event["usage"]["input_tokens"]
        elif event.get("content") is not None:
            calls, text, thinking = [], [], []
            for block in event["content"]:
                if block["type"] == "text":
                    text.append(block["text"])
                elif block["type"] == "thinking":
                    thinking.append(block.get("thinking", ""))
                elif block["type"] == "tool_use":
                    calls.append({"id": block["id"], "type": "function", "function": {"name": block["name"], "arguments": json.dumps(block["input"])}})
            yield {"choices": [{"message": {"role": "assistant", "content": "".join(text), "tool_calls": calls, **({"reasoning_content": "".join(thinking)} if thinking else {})}, "finish_reason": {"tool_use": "tool_calls", "max_tokens": "length"}.get(event.get("stop_reason"), "stop")}],
                   "usage": {"prompt_tokens": event.get("usage", {}).get("input_tokens", 0), "completion_tokens": event.get("usage", {}).get("output_tokens", 0)}}
            continue
        if delta or usage or finish:
            yield {"choices": [{"index": 0, "delta": delta, "finish_reason": finish}], **({"usage": usage} if usage else {})}


def openai_events_to_anthropic(events, model, message_id):
    yield {"type": "message_start", "message": {"id": message_id, "type": "message", "role": "assistant", "model": model, "content": [], "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 0, "output_tokens": 0}}}
    blocks, tools, next_index, text_index, thinking_index = [], {}, 0, None, None
    finish, output_tokens, input_tokens = "end_turn", 0, 0
    for event in events:
        if event.get("error"):
            raise ValueError("上游流返回错误")
        output_tokens = event.get("usage", {}).get("completion_tokens", output_tokens)
        input_tokens = event.get("usage", {}).get("prompt_tokens", input_tokens)
        for choice in event.get("choices", []):
            delta = choice.get("delta") or choice.get("message") or {}
            thinking = delta.get("reasoning_content") or delta.get("reasoning") or delta.get("reasoning_text")
            if thinking:
                if thinking_index is None:
                    thinking_index = next_index; next_index += 1; blocks.append(thinking_index)
                    yield {"type": "content_block_start", "index": thinking_index, "content_block": {"type": "thinking", "thinking": ""}}
                yield {"type": "content_block_delta", "index": thinking_index, "delta": {"type": "thinking_delta", "thinking": thinking}}
            if delta.get("content"):
                if text_index is None:
                    text_index = next_index; next_index += 1; blocks.append(text_index)
                    yield {"type": "content_block_start", "index": text_index, "content_block": {"type": "text", "text": ""}}
                yield {"type": "content_block_delta", "index": text_index, "delta": {"type": "text_delta", "text": delta["content"]}}
            for fallback_index, call in enumerate(delta.get("tool_calls", [])):
                key = call.get("index", fallback_index)
                if key not in tools:
                    tools[key] = next_index; next_index += 1; blocks.append(tools[key])
                    yield {"type": "content_block_start", "index": tools[key], "content_block": {"type": "tool_use", "id": call["id"], "name": call["function"]["name"], "input": {}}}
                arguments = call.get("function", {}).get("arguments")
                if arguments:
                    yield {"type": "content_block_delta", "index": tools[key], "delta": {"type": "input_json_delta", "partial_json": arguments}}
            if choice.get("finish_reason"):
                finish = {"stop": "end_turn", "length": "max_tokens", "tool_calls": "tool_use"}.get(choice["finish_reason"], "end_turn")
    for index in blocks:
        yield {"type": "content_block_stop", "index": index}
    yield {"type": "message_delta", "delta": {"stop_reason": finish, "stop_sequence": None}, "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens}}
    yield {"type": "message_stop"}
