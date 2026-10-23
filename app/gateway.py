"""Provider routing and loopback OpenAI / Anthropic protocol endpoints.

No public hosts, provider discovery, inherited proxies, or environment API keys.
Only explicit user-created provider URLs are contacted.
"""
from __future__ import annotations

import hmac
import ipaddress
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .integration import Completion, IntegrationRequired
from .model_capabilities import normalize_model, normalize_vision
from .protocols import response_events, collect_openai, anthropic_events_to_openai, openai_events_to_anthropic
from .request_diagnostics import RequestDiagnostics, RequestFailure
from .network_retry import upstream_failure
from umeko_provider_sdk.network import network_scope, proxy_handler, trace, TracedResponse


def validate_base_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("请输入有效的 http(s) API 地址，凭据请填写在 API Key 中")
    if parsed.query or parsed.fragment:
        raise ValueError("API 地址不能包含查询参数或片段")
    return url.strip().rstrip("/")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("供应商返回重定向；请直接填写最终 API 地址")


class Gateway:
    def __init__(self, store, adapter, plugins=None):
        self.store, self.adapter, self.plugins = store, adapter, plugins
        self.diagnostics = RequestDiagnostics(store.directory)

    def provider(self, provider_id):
        return next((p for p in self.store.data["providers"] if p["id"] == provider_id), None)

    def models(self):
        rows = []
        for p in self.store.data["providers"]:
            if p["api"] == "internal" and getattr(self.adapter, "ready", True) is False:
                continue
            for model in p["models"]:
                metadata = normalize_model(model)
                rows.append({"id": model["alias"], "object": "model", "owned_by": p["name"],
                             "contextWindow": metadata["contextWindow"],
                             "input": ["text", "image"] if metadata["vision"] else ["text"]})
        return rows

    def supports_vision(self, alias, provider_id=None):
        return any(m["alias"] == alias and normalize_vision(m)["vision"]
                   for p in self.store.data["providers"] if provider_id is None or p["id"] == provider_id for m in p["models"])

    def resolve(self, alias, provider_id=None):
        providers = [self.provider(provider_id)] if provider_id else self.store.data["providers"]
        for p in providers:
            if p:
                for m in p["models"]:
                    if m["alias"] == alias:
                        return p, m["upstream"]
        raise ValueError("模型别名不存在，请检查模型映射")

    def complete(self, alias, messages, tools=None, max_tokens=4096, provider_id=None, parameters=None):
        data = collect_openai(self.events(alias, messages, tools, max_tokens, provider_id, parameters))
        msg, usage = data["choices"][0]["message"], data.get("usage", {})
        calls = [{"id": c["id"], "name": c["function"]["name"], "arguments": json.loads(c["function"]["arguments"])} for c in msg.get("tool_calls") or []]
        return Completion(msg.get("content") or "", calls, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0), data["choices"][0]["finish_reason"], msg.get("reasoning_content") or "")

    def events(self, alias, messages, tools=None, max_tokens=4096, provider_id=None, parameters=None):
        p, model = self.resolve(alias, provider_id)
        records = []
        request = {'transport': p['api'], 'model': model, 'messages': messages,
                   'tools': tools or [], 'max_tokens': max_tokens, 'parameters': parameters or {}}
        try:
            with network_scope(p.get('proxy'), records):
                for event in self._events(alias, messages, tools, max_tokens, provider_id, parameters):
                    if event.get('error'):
                        raise ValueError(json.dumps(event, ensure_ascii=False))
                    yield event
        except (IntegrationRequired, PermissionError):
            raise
        except Exception as error:
            raise self.diagnostics.failure(p, request, records[-1]['response'] if records else {},
                                           repr(error), records) from None

    def _events(self, alias, messages, tools=None, max_tokens=4096, provider_id=None, parameters=None):
        p, model = self.resolve(alias, provider_id)
        if any(isinstance(m.get("content"), list) and any(block.get("type") == "image_url" for block in m["content"]) for m in messages) and not self.supports_vision(alias, p["id"]):
            raise ValueError("当前模型未启用视觉，请在模型配置中勾选“视觉”或切换支持图片的模型")
        tools = tools or []
        parameters = parameters or {}
        if p["api"] == "plugin":
            if self.plugins is None:
                raise IntegrationRequired("请先导入供应商实现")
            yield from self.plugins.events(p["id"], model, messages, tools, max_tokens, parameters)
            return
        if p["api"] == "internal":
            if callable(getattr(self.adapter, "events", None)):
                yield from self.adapter.events(model, messages, tools, max_tokens, parameters)
                return
            result = self.adapter.complete(model, messages, tools, max_tokens)
            if not isinstance(result, Completion):
                raise TypeError("内部适配器必须返回 Completion")
            yield openai_response(result, model)
            return
        base = validate_base_url(p["baseUrl"])
        headers = {"Content-Type": "application/json"}
        if p["api"] == "anthropic":
            url = base + ("/messages" if base.endswith("/v1") else "/v1/messages")
            headers.update({"x-api-key": p["key"], "anthropic-version": "2023-06-01"})
            parameters = dict(parameters)
            if "reasoning_effort" in parameters:
                parameters["output_config"] = {"effort": parameters.pop("reasoning_effort")}
            if "stop" in parameters:
                stop = parameters.pop("stop")
                parameters["stop_sequences"] = [stop] if isinstance(stop, str) else stop
            choice = parameters.get("tool_choice")
            if isinstance(choice, str):
                parameters["tool_choice"] = {"type": {"required": "any"}.get(choice, choice)}
            elif isinstance(choice, dict) and choice.get("type") == "function":
                parameters["tool_choice"] = {"type": "tool", "name": choice["function"]["name"]}
            parallel = parameters.pop("parallel_tool_calls", None)
            if parallel is not None:
                parameters.setdefault("tool_choice", {"type": "auto"})["disable_parallel_tool_use"] = not parallel
            body = {**parameters, "model": model, "max_tokens": max_tokens, "stream": True,
                    "messages": [self.to_anthropic_message(m) for m in messages if m["role"] != "system"]}
            system = "\n".join(str(m.get("content", "")) for m in messages if m["role"] == "system")
            if system:
                body["system"] = system
            if tools:
                body["tools"] = [{"name": t["name"], "description": t.get("description", ""), "input_schema": t["parameters"]} for t in tools]
        else:
            url = base + "/chat/completions"
            headers["Authorization"] = "Bearer " + p["key"]
            body = {**parameters, "model": model, "messages": messages, "max_tokens": max_tokens, "stream": True}
            if tools:
                body["tools"] = [{"type": "function", "function": t} for t in tools]
        request = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
        opener = urllib.request.build_opener(proxy_handler(p.get('proxy')), NoRedirect())
        record = {'request': {'url': url, 'method': 'POST', 'headers': headers, 'body': body},
                  'response': {'status': None, 'headers': {}, 'body': ''}}
        trace.get().append(record)
        try:
            with opener.open(request, timeout=90) as response:
                record['response'].update(status=response.status, headers=dict(response.headers))
                events = response_events(TracedResponse(response, record))
                yield from anthropic_events_to_openai(events) if p["api"] == "anthropic" else events
        except urllib.error.HTTPError as exc:
            record['response'].update(status=exc.code, headers=dict(exc.headers), body=exc.read().decode('utf-8', 'replace'))
            exc.close()
            raise ValueError(f"供应商返回 HTTP {exc.code}，请检查地址、密钥和模型名称") from None
        except (urllib.error.URLError, TimeoutError):
            record['exception'] = traceback.format_exc()
            raise ValueError("无法连接供应商，请检查地址、网络与证书") from None

    @staticmethod
    def to_anthropic_message(m):
        if m["role"] == "tool":
            return {"role": "user", "content": [{"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m.get("content", "")}]}
        value = m.get("content")
        content = []
        if isinstance(value, str) and value:
            content.append({"type": "text", "text": value})
        elif isinstance(value, list):
            for block in value:
                if block.get("type") == "text":
                    content.append(block)
                elif block.get("type") == "image_url":
                    url = block["image_url"]["url"]
                    if not url.startswith("data:") or ";base64," not in url:
                        raise ValueError("图片必须以本机附件的 base64 数据提供")
                    head, data = url.split(",", 1)
                    content.append({"type": "image", "source": {"type": "base64", "media_type": head[5:].split(";")[0], "data": data}})
        for call in m.get("tool_calls", []):
            content.append({"type": "tool_use", "id": call["id"], "name": call["function"]["name"], "input": json.loads(call["function"]["arguments"])})
        return {"role": m["role"], "content": content or [{"type": "text", "text": " "}]}

class LocalServer:
    def __init__(self, gateway, port, token="", private=False, protocols=None, host="127.0.0.1", authenticator=None):
        if host not in ("127.0.0.1", "0.0.0.0") or (private and host != "127.0.0.1"):
            raise ValueError("内核通道仅允许本机访问；代理服务只支持本机或局域网监听")
        self.gateway, self.token, self.private = gateway, token, private
        self.host, self.authenticator = host, authenticator
        self.closed = False
        self.protocols = protocols or {"openai": True, "anthropic": True}
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def handle(self):
                try:
                    super().handle()
                except (ConnectionError, TimeoutError):
                    pass

            def log_message(self, *_):
                pass

            def end_headers(self):
                origin = self.headers.get("Origin", "")
                parsed = urllib.parse.urlsplit(origin)
                local_origin = parsed.hostname in ("127.0.0.1", "localhost", "::1")
                if owner.host == "0.0.0.0" and not owner.private:
                    try:
                        local_origin = local_origin or ipaddress.ip_address(parsed.hostname).is_private
                    except ValueError:
                        pass
                if parsed.scheme in ("http", "https") and local_origin:
                    self.send_header("Access-Control-Allow-Origin", origin)
                    self.send_header("Vary", "Origin")
                    self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, x-api-key, anthropic-version")
                    self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                super().end_headers()

            def do_OPTIONS(self):
                self.send_response(204)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def respond(self, code, body):
                raw = json.dumps(body, ensure_ascii=False).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(raw)

            def authorized(self):
                if owner.closed:
                    self.close_connection = True
                    return False
                value = self.headers.get("Authorization", "")
                supplied = value[7:] if value.startswith("Bearer ") else self.headers.get("x-api-key", "")
                if owner.authenticator:
                    return owner.authenticator(supplied)
                return bool(supplied) and hmac.compare_digest(supplied.encode("utf-8"), owner.token.encode("utf-8"))

            def do_GET(self):
                if not self.authorized():
                    return self.respond(401, {"error": {"message": "Invalid API key", "type": "authentication_error"}})
                if self.path in ("/v1/models", "/models"):
                    return self.respond(200, {"object": "list", "data": owner.gateway.models()})
                if self.path == "/":
                    return self.respond(200, {"status": "running", "name": "Umeko"})
                self.respond(404, {"error": {"message": "Not found"}})

            def do_POST(self):
                if not self.authorized():
                    return self.respond(401, {"error": {"message": "Invalid API key", "type": "authentication_error"}})
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    if not 0 < size <= 32_000_000:
                        return self.respond(413, {"error": {"message": "Invalid request size"}})
                    self.connection.settimeout(100)
                    body = json.loads(self.rfile.read(size))
                    if self.path not in ("/v1/chat/completions", "/v1/messages", "/chat/completions", "/messages"):
                        return self.respond(404, {"error": {"message": "Not found"}})
                    anth = self.path in ("/v1/messages", "/messages")
                    if not owner.protocols["anthropic" if anth else "openai"]:
                        return self.respond(404, {"error": {"message": "Protocol disabled"}})
                    messages = body["messages"]
                    if not isinstance(messages, list) or not messages:
                        raise ValueError("messages 必须是非空数组")
                    if anth:
                        messages = anthropic_to_openai(messages)
                        if body.get("system"):
                            system = body["system"]
                            if isinstance(system, list):
                                system = "\n".join(c.get("text", "") for c in system)
                            messages.insert(0, {"role": "system", "content": system})
                    tools = body.get("tools", [])
                    tools = [{"name": t["name"], "description": t.get("description", ""), "parameters": t["input_schema"]} for t in tools] if anth else [t["function"] for t in tools]
                    parameters = {k: body[k] for k in ("temperature", "top_p", "top_k", "stop", "tool_choice", "parallel_tool_calls", "reasoning_effort") if k in body}
                    if anth and "effort" in body.get("output_config", {}):
                        parameters["reasoning_effort"] = body["output_config"]["effort"]
                    if anth and "stop_sequences" in body:
                        parameters["stop"] = body["stop_sequences"]
                    if anth and isinstance(parameters.get("tool_choice"), dict):
                        choice = parameters["tool_choice"]
                        if "disable_parallel_tool_use" in choice:
                            parameters["parallel_tool_calls"] = not choice["disable_parallel_tool_use"]
                        parameters["tool_choice"] = {"type": "function", "function": {"name": choice["name"]}} if choice.get("type") == "tool" else {"any": "required"}.get(choice.get("type"), choice.get("type", "auto"))
                    max_tokens = min(max(int(body.get("max_tokens", body.get("max_completion_tokens", 4096))), 1), 32768)
                    if body.get("stream"):
                        return self.stream_events(owner.gateway.events(body["model"], messages, tools, max_tokens, parameters=parameters), body["model"], anth)
                    result = owner.gateway.complete(body["model"], messages, tools, max_tokens, parameters=parameters)
                    self.respond(200, anthropic_response(result, body["model"]) if anth else openai_response(result, body["model"]))
                except IntegrationRequired as exc:
                    self.respond(422 if owner.private else 503, {"error": {"type": "integration_required", "message": str(exc)}})
                except PermissionError as exc:
                    self.respond(403, {"error": {"type": "permission_error", "message": str(exc)}})
                except RequestFailure as exc:
                    self.respond(503 if exc.retryable else 400, {"error": upstream_failure(exc)})
                except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                    self.respond(400, {"error": {"type": "invalid_request_error", "message": str(exc)[:300]}})
                except ConnectionError:
                    pass
                except Exception:
                    self.respond(502, {"error": {"type": "upstream_error", "message": "请求失败，请检查适配器或供应商配置"}})

            def stream_events(self, events, model, anth):
                # Fetch the first event before committing a 200 response, so login errors
                # retain their HTTP status. Later failures become explicit SSE errors.
                iterator = iter(events)
                first = next(iterator, None)
                def source():
                    if first is not None:
                        yield first
                    yield from iterator
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
                def event(data, kind=None):
                    raw = (f"event: {kind}\n" if kind else "") + "data: " + json.dumps(data, ensure_ascii=False) + "\n\n"
                    self.wfile.write(raw.encode())
                    self.wfile.flush()
                try:
                    if anth:
                        for item in openai_events_to_anthropic(source(), model, "msg_" + uuid.uuid4().hex):
                            event(item, item["type"])
                    else:
                        common = {"id": "chatcmpl-" + uuid.uuid4().hex, "object": "chat.completion.chunk", "created": int(time.time()), "model": model}
                        for item in source():
                            if item.get("error"):
                                raise ValueError("上游流返回错误")
                            if any("message" in c for c in item.get("choices", [])):
                                choice = item["choices"][0]
                                delta = choice["message"]
                                if delta.get("tool_calls"):
                                    delta = {**delta, "tool_calls": [{"index": i, **c} for i, c in enumerate(delta["tool_calls"])]}
                                event({**common, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]})
                                event({**common, "choices": [{"index": 0, "delta": {}, "finish_reason": choice.get("finish_reason", "stop")}], "usage": item.get("usage", {})})
                            else:
                                event({**item, **common})
                        self.wfile.write(b"data: [DONE]\n\n")
                except ConnectionError:
                    pass
                except Exception as failure:
                    event({"type": "error", "error": upstream_failure(failure)}, "error" if anth else None)
                finally:
                    iterator.close() if hasattr(iterator, "close") else None
                    self.close_connection = True

        self.httpd = ThreadingHTTPServer((host, port), Handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.closed = True
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)


def openai_response(result, model):
    msg = {"role": "assistant", "content": result.text or None}
    if result.thinking:
        msg["reasoning_content"] = result.thinking
    if result.tool_calls:
        msg["tool_calls"] = [{"id": t["id"], "type": "function", "function": {"name": t["name"], "arguments": json.dumps(t["arguments"])}} for t in result.tool_calls]
    return {"id": "chatcmpl-" + uuid.uuid4().hex, "object": "chat.completion", "created": int(time.time()), "model": model,
            "choices": [{"index": 0, "message": msg, "finish_reason": "length" if result.finish_reason == "length" else "tool_calls" if result.tool_calls else result.finish_reason}],
            "usage": {"prompt_tokens": result.input_tokens, "completion_tokens": result.output_tokens, "total_tokens": result.input_tokens + result.output_tokens}}


def anthropic_response(result, model):
    content = ([{"type": "text", "text": result.text}] if result.text else []) + [{"type": "tool_use", "id": t["id"], "name": t["name"], "input": t["arguments"]} for t in result.tool_calls]
    if result.thinking:
        content.insert(0, {"type": "thinking", "thinking": result.thinking})
    return {"id": "msg_" + uuid.uuid4().hex, "type": "message", "role": "assistant", "model": model, "content": content,
            "stop_reason": "max_tokens" if result.finish_reason == "length" else "tool_use" if result.tool_calls else "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": result.input_tokens, "output_tokens": result.output_tokens}}


def anthropic_to_openai(messages):
    output = []
    for m in messages:
        if isinstance(m.get("content"), str):
            output.append(m)
            continue
        text, calls, results = [], [], []
        for c in m.get("content", []):
            if c["type"] == "text":
                text.append(c["text"])
            elif c["type"] == "tool_use":
                calls.append({"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": json.dumps(c["input"])}})
            elif c["type"] == "tool_result":
                val = c["content"]
                results.append({"role": "tool", "tool_call_id": c["tool_use_id"], "content": val if isinstance(val, str) else "\n".join(b.get("text", "") for b in val)})
            elif c["type"] == "image" and c["source"]["type"] == "base64":
                source = c["source"]
                text.append({"type": "image_url", "image_url": {"url": "data:" + source["media_type"] + ";base64," + source["data"]}})
            else:
                raise ValueError("当前仅支持文本与工具调用内容")
        if text or calls:
            content = "\n".join(text) if all(isinstance(t, str) for t in text) else [{"type": "text", "text": t} if isinstance(t, str) else t for t in text]
            msg = {"role": m["role"], "content": content}
            if calls:
                msg["tool_calls"] = calls
            output.append(msg)
        output.extend(results)
    return output
