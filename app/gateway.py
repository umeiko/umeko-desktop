"""Provider routing and loopback OpenAI / Anthropic protocol endpoints.

No public hosts, provider discovery, inherited proxies, or environment API keys.
Only explicit user-created provider URLs are contacted.
"""
from __future__ import annotations

import hmac
import ipaddress
import json
import re
import select
import socket
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
from .protocols import response_events, collect_openai, anthropic_events_to_openai, openai_events_to_anthropic, chat_completion_messages
from .openai_responses import responses_request, responses_events
from .request_diagnostics import RequestDiagnostics, RequestFailure
from .network_retry import upstream_failure
from .provider_errors import format_http_error, safe_text
from .model_reasoning import reasoning_levels
from .reasoning_detection import allowed_levels, is_effort_rejection, detect_model
from .reasoning_activity import ReasoningActivity
from .thinking_formats import format_parameters, valid_format
from umeko_provider_sdk.network import network_scope, proxy_handler, tls_context, trace, TracedResponse
from umeko_provider_sdk import request_scope
from umeko_provider_sdk.compatibility import ParameterMemory, compatible_open, raise_api_error
from umeko_provider_sdk.streaming import normalize_openai_events
from .project_info import VERSION


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
    def __init__(self, store, adapter, plugins=None, reasoning_rejected=None):
        self.store, self.adapter, self.plugins = store, adapter, plugins
        self.reasoning_rejected = reasoning_rejected
        self.reasoning_activity = ReasoningActivity()
        self.diagnostics = RequestDiagnostics(store.directory)
        self.compatibility = ParameterMemory(store.directory, app_version=VERSION)

    def provider(self, provider_id):
        return next((p for p in self.store.data["providers"] if p["id"] == provider_id), None)

    def generate(self, body, on_progress=None, *, poll_interval=2.0):
        from .generation import generate
        return generate(self, body, on_progress, poll_interval=poll_interval)

    def models(self):
        rows = []
        for p in self.store.data["providers"]:
            if p["api"] == "internal" and getattr(self.adapter, "ready", True) is False:
                continue
            for model in p["models"]:
                metadata = normalize_model(model)
                rows.append({"id": model["alias"], "object": "model", "owned_by": p["name"], "providerID": p.get("id", ""),
                             "contextWindow": metadata["contextWindow"],
                             **{key: metadata[key] for key in ("providerContextWindow",) if key in metadata},
                             "input": ["text", "image"] if metadata["vision"] else ["text"],
                             "reasoningLevels": reasoning_levels(model),
                             "reasoningFormat": model.get("reasoningFormat", "openai"),
                             "reasoningState": (model.get("reasoningDetection", {}).get("state", "unknown")
                                                if model.get("reasoningLevelsAuto", "reasoningLevels" not in model) else "manual"),
                             "reasoningFormatState": (model.get("reasoningFormatDetection", {}).get("state", "unknown")
                                                      if model.get("reasoningFormatAuto", True) else "manual")})
        return rows

    def detect_reasoning(self, alias, provider_id=None, advertised_levels=None):
        """Use the normal mapper/transport, with ephemeral probe observations only."""
        provider, _ = self.resolve(alias, provider_id)
        configured = next(model for model in provider["models"] if model["alias"] == alias)

        def request(effort, format, max_tokens):
            records, content = [], []
            reasoning = False
            try:
                with self.reasoning_activity.probe({(provider['id'], configured['upstream'])}), network_scope(provider.get("proxy"), records):
                    for event in self._events(alias, [{"role": "user", "content": "Reply OK."}],
                                              max_tokens=max_tokens, provider_id=provider["id"],
                                              parameters={"_umeko_reasoning_effort": effort,
                                                          "_umeko_reasoning_format": format}):
                        if event.get("error"):
                            raise ValueError(json.dumps(event, ensure_ascii=False))
                        for choice in event.get("choices", []):
                            delta = choice.get("delta", choice.get("message", {}))
                            reasoning = reasoning or any(isinstance(delta.get(key), str) and bool(delta[key].strip())
                                                         for key in ("reasoning_content", "reasoning", "reasoning_text"))
                            value = delta.get("content")
                            if isinstance(value, str):
                                content.append(value)
                            elif isinstance(value, list):
                                content.extend(part.get("text", "") for part in value
                                               if isinstance(part, dict) and isinstance(part.get("text"), str))
            except Exception as error:
                response = records[-1].get("response", {}) if records else {}
                failure = ValueError(safe_text(response.get("body") or str(error), [provider.get("key", "")]))
                failure.status_code = response.get("status")
                raise failure from None
            text = "".join(content)
            reasoning = reasoning or "<think>" in text.lower()
            ordinary = re.sub(r"<think>.*?(?:</think>|$)", "", text, flags=re.I | re.S)
            return {"thinking": bool(reasoning), "content": bool(ordinary.strip())}

        protocol = "anthropic" if provider["api"] == "anthropic" else (
            "responses" if provider.get("wireApi") == "responses" else "openai")
        return detect_model(request, advertised_levels=advertised_levels,
                            manual_levels=None if configured.get("reasoningLevelsAuto", "reasoningLevels" not in configured)
                            else reasoning_levels(configured),
                            manual_format=None if configured.get("reasoningFormatAuto", True)
                            else configured.get("reasoningFormat", "openai"), protocol=protocol)

    def detect_reasoning_levels(self, alias, provider_id=None):
        return self.detect_reasoning(alias, provider_id)["levels"]

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

    def complete(self, alias, messages, tools=None, max_tokens=None, provider_id=None, parameters=None):
        data = collect_openai(self.events(alias, messages, tools, max_tokens, provider_id, parameters))
        msg, usage = data["choices"][0]["message"], data.get("usage", {})
        calls = [{"id": c["id"], "name": c["function"]["name"], "arguments": json.loads(c["function"]["arguments"])} for c in msg.get("tool_calls") or []]
        return Completion(msg.get("content") or "", calls, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0), data["choices"][0]["finish_reason"], msg.get("reasoning_content") or "")

    def events(self, alias, messages, tools=None, max_tokens=None, provider_id=None, parameters=None):
        p, model = self.resolve(alias, provider_id)
        records = []
        request = {'transport': p['api'], 'model': model, 'messages': messages,
                   'tools': tools or [], 'max_tokens': max_tokens, 'parameters': parameters or {}}
        try:
            with self.reasoning_activity.chat((p.get('id', ''), model)), network_scope(p.get('proxy'), records):
                for event in normalize_openai_events(self._events(alias, messages, tools, max_tokens, provider_id, parameters)):
                    if event.get('error'):
                        raise ValueError(json.dumps(event, ensure_ascii=False))
                    yield event
            self.diagnostics.compatibility(p, request, records)
        except (IntegrationRequired, PermissionError):
            raise
        except Exception as error:
            effort = (parameters or {}).get("_umeko_reasoning_effort", (parameters or {}).get("reasoning_effort"))
            rejection = self._reasoning_rejection(p, model, effort, error, records)
            if rejection is not None:
                raise rejection from None
            raise self.diagnostics.failure(p, request, records[-1]['response'] if records else {},
                                           error, records) from None

    def _reasoning_rejection(self, provider, model, effort, error, records):
        if effort is None:
            return None
        response = records[-1].get("response", {}) if records else {}
        status = response.get("status")
        if status in (401, 403, 408, 425, 429) or (isinstance(status, int) and status >= 500):
            return None
        detail = response.get("body") or str(error)
        if not is_effort_rejection(detail):
            return None
        levels = allowed_levels(detail)
        if callable(self.reasoning_rejected):
            self.reasoning_rejected(provider["id"], model, effort, levels)
        if levels is None:
            configured = next((item for item in provider["models"] if item["upstream"] == model), {})
            levels = reasoning_levels(configured)
        supported = ["off"] + [item for item in levels if item not in (effort, "off")]
        message = safe_text(str(error), [provider.get("key", "")])
        return RequestFailure(f'{message}\n当前可选推理档位：{", ".join(supported)}。请调整档位后重新发送。', retryable=False)

    def _events(self, alias, messages, tools=None, max_tokens=None, provider_id=None, parameters=None):
        p, model = self.resolve(alias, provider_id)
        if any(isinstance(m.get("content"), list) and any(block.get("type") == "image_url" for block in m["content"]) for m in messages) and not self.supports_vision(alias, p["id"]):
            raise ValueError("当前模型未启用视觉，请在模型配置中勾选“视觉”或切换支持图片的模型")
        tools = tools or []
        automatic = set((parameters or {}).get('_umeko_auto_parameters', ()))
        default_tokens = max_tokens is None
        max_tokens = 4096 if default_tokens else max_tokens
        # Capture provenance before the reasoning mapper consumes private intent.
        user_parameters = {key: value for key, value in (parameters or {}).items()
                           if not key.startswith('_umeko_') and key not in automatic}
        if '_umeko_reasoning_effort' in (parameters or {}):
            user_parameters.pop('reasoning_effort', None)
        parameters = dict(parameters or {})
        private_intent = "_umeko_reasoning_effort" in parameters
        probe_override = "_umeko_reasoning_format" in parameters
        format_override = parameters.pop("_umeko_reasoning_format", None)
        already_formatted = any(key in parameters for key in
                                ("enable_thinking", "chat_template_kwargs", "thinking", "reasoning"))
        intent = parameters.pop("_umeko_reasoning_effort", None) if private_intent else (
            parameters.get("reasoning_effort") if format_override or not already_formatted else None)
        parameters = {key: value for key, value in parameters.items() if not key.startswith("_umeko_")}
        if intent is not None:
            configured = next(m for m in p["models"] if m["alias"] == alias)
            format = format_override or configured.get("reasoningFormat") or (
                "anthropic" if p["api"] == "anthropic" else "responses" if p.get("wireApi") == "responses" else "openai")
            detection = configured.get("reasoningFormatDetection", {})
            if (not probe_override and private_intent and intent == "off"
                    and configured.get("reasoningFormatAuto", True) is not False
                    and isinstance(detection, dict) and detection.get("state") == "known"
                    and detection.get("offVerified") is True and valid_format(detection.get("offFormat"))):
                format = detection["offFormat"]
            for key in ("reasoning_effort", "enable_thinking", "chat_template_kwargs", "thinking", "reasoning"):
                parameters.pop(key, None)
            parameters.update(format_parameters(format, intent))
        if not probe_override:
            automatic.update(set(parameters) - set(user_parameters))
            parameters.update(user_parameters)
        else:
            automatic.clear()
        if p["api"] == "plugin":
            if self.plugins is None:
                raise IntegrationRequired("请先导入供应商实现")
            yield from self.plugins.events(p["id"], model, chat_completion_messages(messages), tools, max_tokens, parameters)
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
        headers = {"Content-Type": "application/json", "User-Agent": "Umeko-Desktop"}
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
            body = {**parameters, "model": model, "max_tokens": max_tokens, "stream": parameters.get('stream', True),
                    "messages": [self.to_anthropic_message(m) for m in messages if m["role"] != "system"]}
            system = "\n".join(str(m.get("content", "")) for m in messages if m["role"] == "system")
            if system:
                body["system"] = system
            if tools:
                body["tools"] = [{"name": t["name"], "description": t.get("description", ""), "input_schema": t["parameters"]} for t in tools]
        elif p.get('wireApi') == 'responses':
            url = base + '/responses'
            headers['Authorization'] = 'Bearer ' + p['key']
            body = {**responses_request(messages, tools, max_tokens, parameters), 'model': model}
            if "reasoning" in parameters:
                body["reasoning"] = parameters["reasoning"]
        else:
            url = base + "/chat/completions"
            headers["Authorization"] = "Bearer " + p["key"]
            body = {**parameters, "model": model, "messages": chat_completion_messages(messages), "stream": parameters.get('stream', True)}
            if 'max_completion_tokens' not in body:
                body.setdefault('max_tokens', max_tokens)
            if tools:
                body["tools"] = [{"type": "function", "function": t} for t in tools]
        if default_tokens and not probe_override:
            automatic.add('max_output_tokens' if p.get('wireApi') == 'responses' else 'max_tokens')
        if not probe_override and 'stream' not in user_parameters:
            automatic.add('stream')
        if p.get('wireApi') == 'responses' and not probe_override:
            automatic.update(name for name in ('store',) if name not in user_parameters)
            if 'reasoning_effort' in automatic:
                automatic.add('reasoning')
            if 'tools' not in user_parameters:
                automatic.update(f'tools.{index}.strict' for index, tool in enumerate(tools)
                                 if 'strict' not in tool)
        request = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
        opener = urllib.request.build_opener(proxy_handler(p.get('proxy')), urllib.request.HTTPSHandler(context=tls_context(p.get('proxy'))), NoRedirect())
        try:
            with compatible_open(opener, request, timeout=90, memory=self.compatibility,
                                 scope=(p['id'], base, model), automatic=automatic,
                                 records=trace.get()) as response:
                def checked_events():
                    for event in response_events(response):
                        if event is None:
                            continue
                        try:
                            raise_api_error(event)
                        except ValueError:
                            # Retain both SSE bytes and a structured error for
                            # the existing reasoning capability reader.
                            records = trace.get()
                            if records:
                                failure = records[-1]['response']
                                failure['streamBody'] = failure.get('body', '')
                                failure['body'] = json.dumps(event, ensure_ascii=False)
                            raise
                        yield event
                events = checked_events()
                yield from anthropic_events_to_openai(events) if p["api"] == "anthropic" else responses_events(events) if p.get('wireApi') == 'responses' else events if probe_override else normalize_openai_events(events)
        except urllib.error.HTTPError as exc:
            try:
                raise ValueError(format_http_error(exc.code, exc.read(), exc.headers, [p['key']])) from None
            finally:
                exc.close()
        except (urllib.error.URLError, TimeoutError) as exc:
            if isinstance(exc, TimeoutError) or isinstance(getattr(exc, 'reason', None), TimeoutError):
                raise ValueError('供应商请求超时，请检查网络或超时设置') from None
            raise ValueError('无法连接供应商：' + safe_text(str(exc), [p['key']])) from None

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
            arguments = call['function']['arguments']
            content.append({"type": "tool_use", "id": call["id"], "name": call["function"]["name"], "input": json.loads(arguments) if isinstance(arguments, str) else arguments})
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
                    if self.path == '/umeko/generate' and owner.private:
                        if isinstance(body, dict) and body.get('kind') == 'video':
                            return self.request_call(lambda: self.stream_generation(body))
                        result = self.request_call(lambda: owner.gateway.generate(body))
                        return self.respond(200, result)
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
                    parameters = {key: value for key, value in body.items()
                                  if key not in ('model', 'messages', 'tools', 'max_tokens', 'system', 'output_config', 'stop_sequences')
                                  and not key.startswith('_umeko_')}
                    if owner.private and '_umeko_auto_parameters' in body:
                        automatic = body['_umeko_auto_parameters']
                        allowed = {'tool_choice', 'parallel_tool_calls', 'response_format', 'stream_options',
                                   'temperature', 'top_p', 'top_k', 'seed', 'n', 'user', 'dimensions', 'max_tokens',
                                   'max_completion_tokens', 'stream', 'reasoning_effort', 'thinking', 'reasoning', 'enable_thinking', 'chat_template_kwargs'}
                        if not isinstance(automatic, list) or any(not isinstance(key, str) or key not in allowed for key in automatic):
                            raise ValueError('Invalid automatic parameter metadata')
                        parameters['_umeko_auto_parameters'] = automatic
                    if owner.private and "_umeko_reasoning_effort" in body:
                        effort = body["_umeko_reasoning_effort"]
                        if not isinstance(effort, str) or not effort:
                            raise ValueError("Invalid private reasoning effort")
                        parameters["_umeko_reasoning_effort"] = effort
                    if anth and "effort" in body.get("output_config", {}):
                        parameters["reasoning_effort"] = body["output_config"]["effort"]
                    if anth and "stop_sequences" in body:
                        parameters["stop"] = body["stop_sequences"]
                    if anth and isinstance(parameters.get("tool_choice"), dict):
                        choice = parameters["tool_choice"]
                        if "disable_parallel_tool_use" in choice:
                            parameters["parallel_tool_calls"] = not choice["disable_parallel_tool_use"]
                        parameters["tool_choice"] = {"type": "function", "function": {"name": choice["name"]}} if choice.get("type") == "tool" else {"any": "required"}.get(choice.get("type"), choice.get("type", "auto"))
                    max_tokens = body.get('max_tokens', body.get('max_completion_tokens'))
                    if max_tokens is not None and (type(max_tokens) is not int or max_tokens <= 0):
                        raise ValueError('max_tokens must be a positive integer')
                    provider_id = body.get('_umeko_provider') if owner.private else None
                    if provider_id is not None and not isinstance(provider_id, str):
                        raise ValueError('Invalid private provider identity')
                    if body.get("stream"):
                        return self.stream_events(owner.gateway.events(body["model"], messages, tools, max_tokens, provider_id=provider_id, parameters=parameters), body["model"], anth)
                    result = owner.gateway.complete(body["model"], messages, tools, max_tokens, provider_id=provider_id, parameters=parameters)
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

            def stream_generation(self, body):
                # Keep one ordinary tool call alive. Progress travels through
                # Pi's existing tool updates; disconnect uses request_call's
                # cancellation scope, just like other streaming requests.
                from umeko_provider_sdk import current_request_cancelled
                from .generation import GenerationCancelled
                cancelled = current_request_cancelled()
                self.send_response(200)
                self.send_header('Content-Type', 'application/x-ndjson')
                self.send_header('Cache-Control', 'no-cache')
                self.send_header('Connection', 'close')
                self.end_headers()
                self.close_connection = True

                def send(value):
                    if cancelled.is_set():
                        raise GenerationCancelled('生成已取消')
                    try:
                        self.wfile.write((json.dumps(value, ensure_ascii=False) + '\n').encode())
                        self.wfile.flush()
                    except OSError:
                        cancelled.set()
                        raise GenerationCancelled('生成已取消') from None

                try:
                    result = owner.gateway.generate(body, lambda job: send({'type': 'progress', **job}))
                    send({'type': 'result', 'result': result})
                except GenerationCancelled:
                    pass
                except RequestFailure as exc:
                    send({'type': 'error', 'error': upstream_failure(exc)})
                except (ValueError, KeyError, TypeError) as exc:
                    send({'type': 'error', 'error': {'message': str(exc)[:300]}})
                except Exception:
                    send({'type': 'error', 'error': {'message': '请求失败，请检查适配器或供应商配置'}})

            def stream_events(self, events, model, anth):
                return self.request_call(lambda: self._stream_events(events, model, anth))

            def request_call(self, function):
                cancelled, finished = threading.Event(), threading.Event()

                def disconnected():
                    # A provider can be quiet before its first token. Detect
                    # peer closure independently of writes to the SSE socket.
                    while not finished.wait(0.1):
                        try:
                            if owner.closed or (select.select([self.connection], [], [], 0)[0]
                                                and not self.connection.recv(1, socket.MSG_PEEK)):
                                cancelled.set()
                                return
                        except (OSError, ValueError):
                            cancelled.set()
                            return

                watcher = threading.Thread(target=disconnected, daemon=True)
                watcher.start()
                try:
                    with request_scope(cancelled):
                        return function()
                finally:
                    finished.set()
                    watcher.join(timeout=1)

            def _stream_events(self, events, model, anth):
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
