"""Stdlib CodeArts SSE/MCP handoff. Only the caller executes advertised tools.

Pending-call, schema-refresh and registry ownership adapted from
@saccolabs/pi-claude-cli 0.10.0, MIT, Copyright (c) 2026 Rebecca Chernoff.
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

import base64
import copy
from collections import deque
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import queue
import socket
import threading
import time
from urllib.parse import quote, urlencode, urlsplit
from uuid import uuid4

try:
    from .server import CodeartsServer
    from .i18n import tr
except ImportError:  # Scripts are also loadable by the SDK's file entrypoint.
    from server import CodeartsServer
    from i18n import tr

REQUEST_ERROR = "CodeArts 请求未能完成，请重试。"
TIMEOUT_ERROR = "CodeArts 长时间没有返回内容，请重试。"
ABORT_ERROR = "已取消 CodeArts 请求。"
TOOL_ERROR = "无法继续这次工具调用，请重新发送问题。"
STREAM_ERROR = "CodeArts 响应提前结束，请重试。"
_END = object()


class _Admission:
    """Package-wide FIFO: multiple account instances still share three turns."""
    def __init__(self):
        self.condition = threading.Condition()
        self.waiting = deque()
        self.active = set()

    def acquire(self, state):
        with self.condition:
            self.waiting.append(state.id)
            try:
                while not state.closed.is_set():
                    if self.waiting[0] == state.id and len(self.active) < 3:
                        self.waiting.popleft()
                        self.active.add(state.id)
                        self.condition.notify_all()
                        return
                    self.condition.wait()
                raise RuntimeError(ABORT_ERROR)
            finally:
                if state.id in self.waiting:
                    self.waiting.remove(state.id)
                    self.condition.notify_all()

    def release(self, state):
        with self.condition:
            self.active.discard(state.id)
            self.condition.notify_all()

    def wake(self):
        with self.condition:
            self.condition.notify_all()


_ADMISSION = _Admission()


def _view(messages):
    """Ignore gateway metadata, preserving the replay-relevant transcript."""
    return [{k: copy.deepcopy(m[k]) for k in ("role", "content", "tool_calls", "call_id", "tool_call_id")
             if k in m and m[k] is not None} for m in messages if m.get("role") != "system"]


def _parts(messages):
    parts = []
    for m in messages:
        if m.get("role") == "system":
            continue
        label = m.get("role", "user").upper()
        if m.get("role") == "tool":
            label += " RESULT id=" + str(m.get("call_id") or m.get("tool_call_id") or "")
        parts.append({"type": "text", "text": label + ":"})
        content = m.get("content") or ""
        if isinstance(content, str):
            parts.append({"type": "text", "text": content})
        elif isinstance(content, list):
            for block in content:
                if block.get("type") in ("text", "input_text"):
                    parts.append({"type": "text", "text": block.get("text", "")})
                elif block.get("type") == "image_url":
                    image = block.get("image_url", {})
                    url = image.get("url", "") if isinstance(image, dict) else image
                    mime = url.split(";", 1)[0].removeprefix("data:") if url.startswith("data:") else "image/png"
                    parts.append({"type": "file", "mime": mime, "url": url})
        for call in m.get("tool_calls") or []:
            function = call.get("function", call)
            parts.append({"type": "text", "text": "TOOL CALL " + function.get("name", "") +
                          " id=" + str(call.get("id", "")) + ": " + str(function.get("arguments", "{}"))})
    return parts


def _mcp_result(message=None, *, error=TOOL_ERROR):
    if message is None:
        return {"content": [{"type": "text", "text": error}], "isError": True}
    content = message.get("content", "")
    if not isinstance(content, list):
        content = [{"type": "text", "text": content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)}]
    return {"content": content, "isError": bool(message.get("isError", False))}


class _State:
    def __init__(self, model, messages, tools):
        self.id = uuid4().hex
        self.request_id = uuid4().hex
        self.model, self.messages, self.tools = model, copy.deepcopy(messages), copy.deepcopy(tools)
        self.lock = threading.RLock()
        self.operation = threading.RLock()
        self.closed = threading.Event()
        self.cleanup_done = threading.Event()
        self.session = self.lease = self.connection = self.broker = None
        self.slot = None
        self.registered = self.prompt_started = self.attached = False
        self.sink = None
        self.pending, self.backlog = {}, []
        self.parts, self.kinds, self.users, self.usage_parts = {}, {}, set(), set()
        self.history, self.output = [], {"role": "assistant", "content": ""}
        self.reason = "stop"
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
                      "prompt_tokens_details": {"cached_tokens": 0},
                      "completion_tokens_details": {"reasoning_tokens": 0}}
        self.timer = None
        self.refresh = None
        self.streams = set()
        self.http_connections = set()
        self.event_thread = None


class CodeartsTransport:
    """One account's shared 3-slot manager, with separate official sessions.

    ``server`` is an injectable control manager for loopback-only tests. Public
    events are OpenAI completion chunks, including reasoning and usage chunks.
    Held MCP requests are resumed by their exact returned tool-call IDs.
    """
    def __init__(self, context, account, *, server=None, inactivity_timeout=300,
                 handoff_timeout=1800, request_timeout=30):
        self.context, self.account = context, account
        self.server = server or CodeartsServer(account, account.profile_dir,
                                               progress=getattr(account, "_progress", None),
                                               language=getattr(context, "language", "zh"))
        self.inactivity_timeout, self.handoff_timeout = inactivity_timeout, handoff_timeout
        self.request_timeout = request_timeout
        self._lock, self._states, self._closed = threading.RLock(), {}, False

    def _localized(self, message):
        keys = {REQUEST_ERROR: "transport_request", TIMEOUT_ERROR: "transport_timeout",
                ABORT_ERROR: "transport_abort", TOOL_ERROR: "transport_tool", STREAM_ERROR: "transport_stream"}
        return tr(getattr(self.context, "language", "zh"), keys[message])

    @staticmethod
    def _is_cancelled(value):
        return bool(value() if callable(value) else value.is_set() if hasattr(value, "is_set") else value)

    def _cancelled(self, request_cancelled=None):
        return self._is_cancelled(getattr(self.context, "cancelled", False)) or self._is_cancelled(request_cancelled)

    def _arm(self, state, timeout):
        with state.lock:
            if state.timer:
                state.timer.cancel()
            if state.closed.is_set():
                return
            state.timer = threading.Timer(timeout, lambda: self._fail(state, TIMEOUT_ERROR))
            state.timer.daemon = True
            state.timer.start()

    def _open(self, state, path, method="GET", body=None, *, stream=False, cleanup=False):
        if state.closed.is_set() and not cleanup:
            raise RuntimeError(ABORT_ERROR)
        info = state.connection
        url = urlsplit(info["url"])
        if url.scheme != "http" or url.hostname not in ("127.0.0.1", "localhost", "::1"):
            raise RuntimeError(REQUEST_ERROR)
        target = path
        if info.get("directory"):
            target += ("&" if "?" in target else "?") + urlencode({"directory": info["directory"]})
        auth = base64.b64encode((info["username"] + ":" + info["password"]).encode()).decode("ascii")
        headers = {"Authorization": "Basic " + auth}
        if stream:
            headers["Accept"] = "text/event-stream"
        if body is not None:
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        conn = http.client.HTTPConnection(url.hostname, url.port,
                    timeout=max(self.inactivity_timeout, self.handoff_timeout) if stream else self.request_timeout)
        with state.lock:
            state.http_connections.add(conn)
        try:
            conn.request(method, target, body, headers)
            response = conn.getresponse()
            if not 200 <= response.status < 300:
                raise RuntimeError(REQUEST_ERROR)
            if stream:
                return conn, response
            raw = response.read()
            return json.loads(raw) if raw else None
        except Exception:
            with state.lock:
                state.http_connections.discard(conn)
            conn.close()
            raise
        finally:
            if not stream:
                with state.lock:
                    state.http_connections.discard(conn)
                conn.close()

    def _control(self, **body):
        return self.server.handle(body)

    def _put(self, state, delta=None, finish=None, usage=None):
        with state.lock:
            sink = state.sink
            if sink is None:
                return
            event = {"object": "chat.completion.chunk", "model": state.model,
                     "choices": [] if usage is not None else [{"index": 0, "delta": delta or {}, "finish_reason": finish}]}
            if usage is not None:
                event["usage"] = usage
            sink.put(event)

    def _end(self, state, reason):
        with state.lock:
            if state.sink is None:
                return
            self._put(state, finish=reason)
            state.sink.put(_END)
            state.sink = None

    def _fail(self, state, message):
        with state.lock:
            if state.closed.is_set():
                return
            if state.sink is not None:
                state.sink.put(RuntimeError(self._localized(message)))
                state.sink.put(_END)
                state.sink = None
        self._cleanup(state, aborted=True)

    def _cleanup(self, state, aborted=False):
        with state.lock:
            if state.closed.is_set():
                return
            state.closed.set()
            if state.timer:
                state.timer.cancel()
            if state.refresh:
                state.refresh["event"].set()
            for call in state.pending.values():
                call["result"] = _mcp_result(error=self._localized(TOOL_ERROR))
                call["event"].set()
            state.pending.clear()
            for stream in list(state.streams):
                stream.set()
        _ADMISSION.wake()
        # Queue acquisition has no HTTP socket. Cancel only an unleased waiter;
        # an owned lease must stay unavailable until its MCP disconnect succeeds.
        if not state.lease:
            self._control(action="cancel", requestId=state.request_id)
        # Let an already accepted session-create response expose its ID before
        # deleting it. No further setup operation starts after closed is set.
        try:
            with state.operation:
                self._cleanup_owned(state, aborted)
        finally:
            state.cleanup_done.set()

    def _cleanup_owned(self, state, aborted):
        with state.lock:
            connections = list(state.http_connections)
        # Wake SSE readers before deleting the owned remote session.
        for conn in connections:
            try:
                if conn.sock:
                    conn.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            conn.close()
        if state.connection and state.session:
            if aborted:
                try:
                    self._open(state, f"/session/{quote(state.session)}/abort", "POST", cleanup=True)
                except Exception:
                    pass
            try:
                self._open(state, f"/session/{quote(state.session)}", "DELETE", cleanup=True)
            except Exception:
                pass
        try:
            self._release(state)
        except Exception:
            # Do not recycle a slot whose disconnect was not acknowledged.
            self.server.close()
            _ADMISSION.release(state)
        if state.broker:
            state.broker.shutdown()
            state.broker.server_close()
            if state.broker_thread is not threading.current_thread():
                state.broker_thread.join(timeout=self.request_timeout)
        self._control(action="cancel", requestId=state.request_id)
        with self._lock:
            self._states.pop(state.id, None)

    def _release(self, state):
        if state.registered:
            self._open(state, f"/mcp/pi{state.slot}/disconnect", "POST", cleanup=state.closed.is_set())
            state.registered = False
        if state.lease:
            self._control(action="release", leaseId=state.lease)
            state.lease = None
        _ADMISSION.release(state)

    def _notify(self, state):
        with state.lock:
            refresh = state.refresh
            if refresh:
                for event in state.streams:
                    refresh["notified"] = True
                    event.set()

    def _broker(self, state):
        owner, token = self, uuid4().hex

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def handle(self):
                try:
                    super().handle()
                except (ConnectionResetError, BrokenPipeError):
                    # The official client may reset an idle keepalive socket
                    # during disconnect. These peer exits are normal teardown.
                    self.close_connection = True

            def log_message(self, *_args):
                pass

            def _send(self, status, value=None):
                raw = json.dumps(value).encode("utf-8") if value is not None else b""
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                if raw:
                    self.wfile.write(raw)

            def _valid(self):
                if self.path != "/mcp/" + token:
                    self._send(404)
                    return False
                return True

            def do_GET(self):
                if not self._valid():
                    return
                event = threading.Event()
                with state.lock:
                    if state.closed.is_set():
                        self._send(410)
                        return
                    state.streams.add(event)
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-cache")
                    self.end_headers()
                    self.wfile.write(b": connected\n\n")
                    self.wfile.flush()
                    owner._notify(state)
                    while not state.closed.is_set():
                        event.wait(0.25)
                        if state.closed.is_set():
                            break
                        if event.is_set():
                            event.clear()
                            self.wfile.write(b'event: message\ndata: {"jsonrpc":"2.0","method":"notifications/tools/list_changed"}\n\n')
                            self.wfile.flush()
                except (OSError, ValueError):
                    pass
                finally:
                    with state.lock:
                        state.streams.discard(event)
                    self.close_connection = True

            def do_DELETE(self):
                if self._valid():
                    self._send(204)

            def do_POST(self):
                if not self._valid():
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if length > 8 * 1024 * 1024:
                        self._send(413)
                        return
                    rpc = json.loads(self.rfile.read(length))
                    if "id" not in rpc:
                        self._send(202)
                        return
                    method, params = rpc.get("method"), rpc.get("params") or {}
                    if method == "initialize":
                        result = {"protocolVersion": params.get("protocolVersion", "2024-11-05"),
                                  "capabilities": {"tools": {"listChanged": True}},
                                  "serverInfo": {"name": f"pi{state.slot}", "version": "1.0.0"}}
                    elif method == "tools/list":
                        with state.lock:
                            result = {"tools": [{"name": t["name"], "description": t.get("description", ""),
                                                 "inputSchema": t.get("parameters", {})} for t in state.tools]}
                            if state.refresh and state.refresh["notified"]:
                                state.refresh["listed"] = True
                    elif method == "ping":
                        result = {}
                    elif method == "tools/call":
                        name, args = params.get("name"), params.get("arguments", {})
                        with state.lock:
                            valid = not state.closed.is_set() and state.prompt_started and isinstance(args, dict) and any(t["name"] == name for t in state.tools)
                            call = {"id": "codearts_" + uuid4().hex, "name": name, "arguments": args,
                                    "event": threading.Event(), "result": None}
                            if valid:
                                state.pending[call["id"]] = call
                        if valid:
                            owner._deliver(state, call)
                            call["event"].wait(owner.handoff_timeout + owner.request_timeout)
                            result = call["result"] or _mcp_result(error=owner._localized(TOOL_ERROR))
                        else:
                            result = _mcp_result(error=owner._localized(TOOL_ERROR))
                    else:
                        self._send(200, {"jsonrpc": "2.0", "id": rpc["id"], "error": {"code": -32601, "message": tr(getattr(owner.context, "language", "zh"), "server_unsupported")}})
                        return
                    self._send(200, {"jsonrpc": "2.0", "id": rpc["id"], "result": result})
                except (OSError, ValueError, TypeError, KeyError):
                    self.close_connection = True

        state.broker = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        state.broker.daemon_threads = True
        state.broker_thread = threading.Thread(target=state.broker.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        state.broker_thread.start()
        return f"http://127.0.0.1:{state.broker.server_port}/mcp/{token}"

    def _deliver(self, state, call):
        with state.lock:
            if state.sink is None:
                state.backlog.append(("tool", call))
                return
            function = {"name": call["name"], "arguments": json.dumps(call["arguments"], ensure_ascii=False)}
            tc = {"id": call["id"], "type": "function", "function": function}
            state.output.setdefault("tool_calls", []).append(tc)
            self._put(state, {"tool_calls": [{"index": 0, **tc}]})
            self._end(state, "tool_calls")
            self._arm(state, self.handoff_timeout)

    def _observe(self, state, event):
        p = event.get("properties") or {}
        kind = event.get("type")
        with state.lock:
            if state.closed.is_set():
                return
            if kind == "mcp.tools.changed":
                if p.get("server") == f"pi{state.slot}" and state.refresh and state.refresh["listed"]:
                    state.refresh["ack"] = True
                    state.refresh["event"].set()
                return
            part, info = p.get("part") or {}, p.get("info") or {}
            if (p.get("sessionID") or part.get("sessionID") or info.get("sessionID")) != state.session or not state.prompt_started:
                return
            self._arm(state, self.inactivity_timeout if state.sink is not None else self.handoff_timeout)
            if kind == "message.updated":
                if info.get("role") == "user":
                    state.users.add(info.get("id"))
                return
            if (part.get("messageID") or p.get("messageID")) in state.users:
                return
            if state.sink is None:
                state.backlog.append(("event", event))
                return
            if kind == "message.part.updated" and part.get("type") in ("text", "reasoning"):
                ident, text = part["id"], part.get("text", "")
                previous = state.parts.get(ident, "")
                delta = text[len(previous):] if text.startswith(previous) else ""
                state.kinds[ident] = part["type"]
                state.parts[ident] = previous + delta
                self._text(state, part["type"], delta)
            elif kind == "message.part.delta" and p.get("field") == "text":
                ident, delta = p["partID"], p.get("delta", "")
                state.parts[ident] = state.parts.get(ident, "") + delta
                self._text(state, state.kinds.get(ident, "text"), delta)
            elif kind == "message.part.updated" and part.get("type") == "step-finish" and part["id"] not in state.usage_parts:
                state.usage_parts.add(part["id"])
                t = part.get("tokens") or {}
                cache = t.get("cache") or {}
                prompt = (t.get("input") or 0) + (cache.get("read") or 0) + (cache.get("write") or 0)
                completion = t.get("output") or 0
                state.usage["prompt_tokens"] += prompt
                state.usage["completion_tokens"] += completion
                state.usage["total_tokens"] += prompt + completion
                state.usage["prompt_tokens_details"]["cached_tokens"] += cache.get("read", 0)
                state.usage["completion_tokens_details"]["reasoning_tokens"] += t.get("reasoning", 0)
                self._put(state, usage=copy.deepcopy(state.usage))
                if part.get("reason") in ("length", "max-tokens"):
                    state.reason = "length"
            elif kind == "session.error":
                threading.Thread(target=self._fail, args=(state, REQUEST_ERROR), daemon=True).start()
            elif kind == "session.idle":
                if state.pending:
                    threading.Thread(target=self._fail, args=(state, TOOL_ERROR), daemon=True).start()
                else:
                    # Release only after this slot's advertised broker disconnects.
                    self._release(state)
                    state.history = _view(state.messages + [state.output])
                    state.prompt_started = False
                    if state.timer:
                        state.timer.cancel()
                    self._end(state, state.reason)

    def _text(self, state, kind, text):
        if text:
            key = "reasoning_content" if kind == "reasoning" else "content"
            state.output[key] = state.output.get(key, "") + text
            self._put(state, {key: text})

    def _read_events(self, state, response):
        data = []
        try:
            while not state.closed.is_set():
                line = response.readline()
                if not line:
                    raise RuntimeError(STREAM_ERROR)
                line = line.decode("utf-8").rstrip("\r\n")
                if line.startswith("data:"):
                    data.append(line[5:].lstrip())
                elif not line and data:
                    self._observe(state, json.loads("\n".join(data)))
                    data = []
        except Exception:
            if not state.closed.is_set():
                self._fail(state, STREAM_ERROR)

    def _register(self, state):
        self._open(state, "/mcp", "POST", {"name": f"pi{state.slot}", "config": {
            "type": "remote", "url": state.broker_url, "oauth": False, "enabled": True,
            "timeout": int(self.handoff_timeout * 1000)}})
        state.registered = True

    def _acquire(self, state):
        _ADMISSION.acquire(state)
        lease = self._control(action="acquire", requestId=state.request_id)
        with state.lock:
            state.lease, state.slot = lease["leaseId"], lease["slot"]
        if state.closed.is_set():
            self._control(action="release", leaseId=state.lease)
            raise RuntimeError(ABORT_ERROR)

    def _run(self, state, messages, tools):
        with state.operation:
            self._work(state, messages, tools)

    def _work(self, state, messages, tools):
        try:
            if state.closed.is_set():
                return
            if state.session and state.prompt_started:
                results = [m for m in messages if m.get("role") == "tool" and (m.get("call_id") or m.get("tool_call_id")) in state.pending]
                if not results:
                    raise RuntimeError(TOOL_ERROR)
                if tools != state.tools:
                    with state.lock:
                        state.tools = copy.deepcopy(tools)
                        refresh = {"event": threading.Event(), "notified": False, "listed": False, "ack": False}
                        state.refresh = refresh
                    self._notify(state)
                    deadline = time.monotonic() + self.request_timeout
                    while not refresh["event"].wait(min(0.05, max(0, deadline - time.monotonic()))):
                        if time.monotonic() >= deadline:
                            raise RuntimeError(TIMEOUT_ERROR)
                    if not refresh["ack"] or state.closed.is_set():
                        raise RuntimeError(ABORT_ERROR)
                    state.refresh = None
                with state.lock:
                    for message in results:
                        call = state.pending.pop(message.get("call_id") or message.get("tool_call_id"))
                        call["result"] = _mcp_result(message)
                        call["event"].set()
                    backlog, state.backlog = state.backlog, []
                    for kind, item in backlog:
                        self._deliver(state, item) if kind == "tool" else self._observe(state, item)
                return
            self._acquire(state)
            if not state.connection:
                state.connection = self._control(action="connection")
                state.broker_url = self._broker(state)
            self._register(state)
            if not state.session:
                session = self._open(state, "/session", "POST", {"title": "Umeko", "permission": [
                    {"permission": "*", "pattern": "*", "action": "deny"},
                    {"permission": f"pi{state.slot}_*", "pattern": "*", "action": "allow"}]})
                state.session = session["id"]
                _, response = self._open(state, "/event", stream=True)
                state.event_thread = threading.Thread(target=self._read_events, args=(state, response), daemon=True)
                state.event_thread.start()
            provider, sep, model = state.model.partition("/")
            if not sep:
                raise RuntimeError(REQUEST_ERROR)
            visible = [m for m in messages if m.get("role") != "system"]
            new_messages = visible[len(state.history):] if state.history else messages
            payload = {"agent": f"umeko{state.slot}", "model": {"providerID": provider, "modelID": model},
                       "system": "\n\n".join(m.get("content", "") for m in messages if m.get("role") == "system" and isinstance(m.get("content"), str)),
                       "parts": _parts(new_messages), "tools": {"*": False, f"pi{state.slot}_*": True}}
            state.prompt_started = True
            self._open(state, f"/session/{quote(state.session)}/prompt_async", "POST", payload)
        except Exception as error:
            message = str(error) if str(error) in (ABORT_ERROR, TIMEOUT_ERROR, TOOL_ERROR) else REQUEST_ERROR
            self._fail(state, message)

    def events(self, model, messages, tools, max_tokens, parameters):
        del max_tokens, parameters  # Official server selects its configured limits.
        # Capture the ContextVar-backed request event here, in the HTTP worker.
        # Background workers must not resolve another thread's request scope.
        # The event is watched only until this generator consumes its own END;
        # a normal tool handoff then keeps the official session and broker alive.
        request_cancelled = getattr(self.context, "request_cancelled", getattr(self.context, "cancelled", False))
        messages, tools = copy.deepcopy(messages), copy.deepcopy(tools or [])
        ids = {m.get("call_id") or m.get("tool_call_id") for m in messages if m.get("role") == "tool"}
        view = _view(messages)
        with self._lock:
            if self._closed:
                raise RuntimeError(self._localized(ABORT_ERROR))
            matches = [s for s in self._states.values() if ids.intersection(s.pending)]
            if not matches:
                matches = [s for s in self._states.values() if s.history and not s.prompt_started and not s.attached and s.model == model and
                           s.tools == tools and len(view) > len(s.history) and view[:len(s.history)] == s.history]
            if len(matches) > 1:
                raise RuntimeError(self._localized(TOOL_ERROR))
            state = matches[0] if matches else _State(model, messages, tools)
            if state.attached or state.model != model:
                raise RuntimeError(self._localized(TOOL_ERROR))
            state.attached = True
            state.messages = messages
            state.output = {"role": "assistant", "content": ""}
            state.usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
                           "prompt_tokens_details": {"cached_tokens": 0},
                           "completion_tokens_details": {"reasoning_tokens": 0}}
            state.request_id = state.request_id if state.prompt_started else uuid4().hex
            sink = queue.Queue()
            state.sink = sink
            self._states[state.id] = state
        worker, completed = None, False
        try:
            if self._cancelled(request_cancelled):
                self._fail(state, ABORT_ERROR)
            else:
                self._arm(state, self.inactivity_timeout)
                worker = threading.Thread(target=self._run, args=(state, messages, tools), daemon=True)
                worker.start()
            while True:
                if self._cancelled(request_cancelled) and not state.closed.is_set():
                    self._fail(state, ABORT_ERROR)
                try:
                    event = sink.get(timeout=0.05)
                except queue.Empty:
                    continue
                if event is _END:
                    completed = True
                    break
                if isinstance(event, Exception):
                    raise event
                yield event
        finally:
            with state.lock:
                state.attached = False
            if not completed:
                self._fail(state, ABORT_ERROR)
            if worker and worker is not threading.current_thread():
                worker.join(timeout=self.request_timeout + 1)
            if state.closed.is_set():
                state.cleanup_done.wait(self.request_timeout * 4 + 2)

    def close(self):
        with self._lock:
            self._closed = True
            states = list(self._states.values())
        for state in states:
            self._fail(state, ABORT_ERROR)
        self.server.close()
        for state in states:
            if state.event_thread and state.event_thread is not threading.current_thread():
                state.event_thread.join(timeout=self.request_timeout + 1)
