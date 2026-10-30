"""Loopback-only tests for the bundled stdlib CodeArts transport."""
import concurrent.futures
from contextvars import ContextVar
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import socket
import struct
import sys
import tempfile
import threading
import time
import types
import unittest
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "provider_dev/bundled/codearts/scripts"
package = types.ModuleType("codearts_transport_fixture")
package.__path__ = [str(SCRIPTS)]
sys.modules[package.__name__] = package
spec = importlib.util.spec_from_file_location(package.__name__ + ".transport", SCRIPTS / "transport.py")
transport = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = transport
spec.loader.exec_module(transport)

TOOLS = [{"name": "square", "description": "square", "parameters": {"type": "object", "properties": {"value": {"type": "number"}}}}]


def rpc(url, method, params=None):
    target = urlsplit(url)
    conn = http.client.HTTPConnection(target.hostname, target.port, timeout=5)
    try:
        raw = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})
        conn.request("POST", target.path, raw, {"Content-Type": "application/json"})
        response = conn.getresponse()
        return json.loads(response.read())["result"]
    finally:
        conn.close()


class FakeServer:
    def __init__(self, mode="tools"):
        self.mode, self.mcp, self.registrations = mode, {}, []
        self.prompts, self.results, self.deleted, self.order = [], [], [], []
        self.aborted = False
        self.clients, self.connections, self.threads = [], [], []
        self.condition = threading.Condition()
        self.closed = threading.Event()
        self.refresh_listed = threading.Event()
        self.allow_ack = threading.Event()
        self.session_count = 0
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_):
                pass

            def do_GET(self):
                if urlsplit(self.path).path != "/event":
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                self.wfile.flush()
                with outer.condition:
                    outer.clients.append(self.wfile)
                    outer.connections.append(self.connection)
                    outer.condition.notify_all()
                outer.closed.wait(10)
                self.close_connection = True

            def do_DELETE(self):
                outer.deleted.append(urlsplit(self.path).path)
                self.reply(True)

            def reply(self, data=None, status=200):
                raw = json.dumps(data).encode() if data is not None else b""
                self.send_response(status)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                body = json.loads(raw) if raw else None
                path = urlsplit(self.path).path
                if path == "/mcp":
                    name, url = body["name"], body["config"]["url"]
                    outer.mcp[name] = url
                    outer.registrations.append(name)
                    init = rpc(url, "initialize")
                    assert init["capabilities"]["tools"]["listChanged"]
                    assert rpc(url, "tools/list")["tools"]
                    if outer.mode == "refresh":
                        outer.spawn(outer.notifications, name, url)
                    self.reply({name: {"status": "connected"}})
                elif path == "/session":
                    outer.session_count += 1
                    assert body["permission"][0]["action"] == "deny"
                    self.reply({"id": f"ses-{outer.session_count}"})
                elif path.endswith("prompt_async"):
                    sid = path.split("/")[2]
                    outer.prompts.append((sid, body))
                    self.reply(status=204)
                    with outer.condition:
                        outer.condition.notify_all()
                    if outer.mode != "silent":
                        outer.spawn(outer.run, sid, body, len(outer.prompts))
                elif path.endswith("disconnect"):
                    outer.order.append("disconnect:" + path.split("/")[2])
                    self.reply(True)
                elif path.endswith("abort"):
                    outer.aborted = True
                    self.reply(True)
                else:
                    self.send_error(404)

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.http.daemon_threads = True
        self.spawn(self.http.serve_forever, poll_interval=0.05)

    def spawn(self, target, *args, **kwargs):
        thread = threading.Thread(target=target, args=args, kwargs=kwargs, daemon=True)
        self.threads.append(thread)
        thread.start()

    def emit(self, kind, **properties):
        raw = ("data: " + json.dumps({"type": kind, "properties": properties}) + "\n\n").encode()
        with self.condition:
            for client in list(self.clients):
                try:
                    client.write(raw)
                    client.flush()
                except OSError:
                    self.clients.remove(client)

    def notifications(self, name, url):
        target = urlsplit(url)
        conn = http.client.HTTPConnection(target.hostname, target.port, timeout=5)
        self.connections.append(conn)
        try:
            conn.request("GET", target.path)
            response = conn.getresponse()
            while not self.closed.is_set():
                line = response.readline()
                if not line:
                    return
                if line.startswith(b"data:"):
                    self.order.append("notification")
                    self.refreshed = rpc(url, "tools/list")["tools"]
                    self.order.append("list")
                    self.refresh_listed.set()
                    self.allow_ack.wait(5)
                    self.emit("mcp.tools.changed", server=name)
                    self.order.append("ack")
        except (OSError, ValueError):
            pass
        finally:
            conn.close()

    def run(self, sid, body, turn):
        name = "pi" + body["agent"][-1]
        if turn == 1:
            for number in range(2 if self.mode == "tools" else 1):
                result = rpc(self.mcp[name], "tools/call", {"name": "square", "arguments": {"value": number + 2}})
                self.results.append(result)
                self.order.append("result")
                if result.get("isError"):
                    return
        self.emit("message.updated", info={"sessionID": sid, "role": "assistant", "id": "a"})
        self.emit("message.part.updated", part={"sessionID": sid, "id": f"reason-{turn}", "type": "reasoning", "text": ""})
        self.emit("message.part.delta", sessionID=sid, partID=f"reason-{turn}", field="text", delta="Checked.")
        self.emit("message.part.delta", sessionID=sid, partID=f"text-{turn}", field="text", delta="Done ")
        self.emit("message.part.delta", sessionID=sid, partID=f"text-{turn}", field="text", delta="now.")
        self.emit("message.part.updated", part={"sessionID": sid, "id": f"text-{turn}", "type": "text", "text": "Done now."})
        finish = {"sessionID": sid, "id": f"usage-{turn}", "type": "step-finish", "tokens": {"input": 5, "output": 6, "cache": {"read": 2}}, "reason": "stop"}
        self.emit("message.part.updated", part=finish)
        self.emit("message.part.updated", part=finish)
        self.emit("session.idle", sessionID=sid)

    def wait_prompts(self, count):
        with self.condition:
            return self.condition.wait_for(lambda: len(self.prompts) >= count, 5)

    def close(self):
        self.closed.set()
        self.allow_ack.set()
        for conn in self.connections:
            try:
                sock = conn.sock if isinstance(conn, http.client.HTTPConnection) else conn
                if sock:
                    sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        self.http.shutdown()
        self.http.server_close()
        for thread in self.threads:
            thread.join(timeout=1)


class Controller(transport.CodeartsServer):
    def __init__(self, fake, root):
        super().__init__(None, root, queue_timeout=5)
        self.fake = fake

    def connection(self):
        return {"url": f"http://127.0.0.1:{self.fake.http.server_port}", "username": "fixture", "password": "fixture", "directory": "C:/UmekoTests/fixture"}

    def _release(self, lease):
        self.fake.order.append("release")
        return super()._release(lease)


def collect(events):
    chunks = list(events)
    message = {"role": "assistant", "content": ""}
    for chunk in chunks:
        for choice in chunk.get("choices", []):
            delta = choice["delta"]
            message["content"] += delta.get("content", "")
            if delta.get("tool_calls"):
                message["tool_calls"] = [{k: v for k, v in c.items() if k != "index"} for c in delta["tool_calls"]]
    return message, chunks


class TransportTests(unittest.TestCase):
    def setup_fixture(self, mode="tools", **options):
        root = Path("C:/UmekoTests/codearts-transport")
        root.mkdir(parents=True, exist_ok=True)
        temp = tempfile.TemporaryDirectory(dir=root)
        fake = FakeServer(mode)
        context = types.SimpleNamespace(cancelled=threading.Event(), profile_dir="C:/forbidden-original-profile")
        controller = Controller(fake, temp.name)
        settings = {"inactivity_timeout": 3, "handoff_timeout": 4, "request_timeout": 1, **options}
        provider = transport.CodeartsTransport(context, types.SimpleNamespace(profile_dir=temp.name), server=controller, **settings)
        self.addCleanup(temp.cleanup)
        self.addCleanup(fake.close)
        self.addCleanup(provider.close)
        return fake, provider, context, controller

    def test_two_held_calls_stream_and_same_official_session_followup(self):
        fake, provider, _, controller = self.setup_fixture()
        messages = [{"role": "system", "content": "system fixture"}, {"role": "user", "content": "compute"}]
        for value in (4, 9):
            assistant, chunks = collect(provider.events("fixture/model", messages, TOOLS, 100, {}))
            self.assertEqual(chunks[-1]["choices"][0]["finish_reason"], "tool_calls")
            call = assistant["tool_calls"][0]
            self.assertEqual(len(fake.results), (0 if value == 4 else 1))
            messages += [assistant, {"role": "tool", "call_id": call["id"], "content": str(value)}]
        assistant, chunks = collect(provider.events("fixture/model", messages, TOOLS, 100, {}))
        self.assertEqual(assistant["content"], "Done now.")
        self.assertEqual("".join(c["choices"][0]["delta"].get("reasoning_content", "") for c in chunks if c["choices"]), "Checked.")
        self.assertEqual(len([c for c in chunks if "usage" in c]), 1)
        self.assertEqual([r["content"][0]["text"] for r in fake.results], ["4", "9"])
        messages += [assistant, {"role": "user", "content": "continue"}]
        self.assertEqual(collect(provider.events("fixture/model", messages, TOOLS, 100, {}))[0]["content"], "Done now.")
        self.assertEqual(fake.session_count, 1)
        self.assertEqual(fake.prompts[1][1]["parts"], [{"type": "text", "text": "USER:"}, {"type": "text", "text": "continue"}])
        self.assertEqual(controller._leases, {})
        self.assertEqual(fake.order[-2:], ["disconnect:pi0", "release"])

    def test_schema_change_waits_for_matching_cache_ack(self):
        fake, provider, _, _ = self.setup_fixture("refresh")
        messages = [{"role": "user", "content": "discover"}]
        assistant, _ = collect(provider.events("fixture/model", messages, TOOLS, 100, {}))
        call = assistant["tool_calls"][0]
        messages += [assistant, {"role": "tool", "call_id": call["id"], "content": "loadout changed"}]
        changed = [{**TOOLS[0], "name": "cube"}]
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(collect, provider.events("fixture/model", messages, changed, 100, {}))
            self.assertTrue(fake.refresh_listed.wait(2))
            self.assertEqual(fake.results, [])
            fake.emit("mcp.tools.changed", server="pi2")
            self.assertFalse(future.done())
            fake.allow_ack.set()
            self.assertEqual(future.result(timeout=4)[0]["content"], "Done now.")
        self.assertEqual(fake.refreshed[0]["name"], "cube")
        self.assertLess(fake.order.index("ack"), fake.order.index("result"))

    def test_three_slots_and_fifo_fourth_waiter(self):
        fake, provider, _, controller = self.setup_fixture("silent")
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(collect, provider.events("fixture/model", [{"role": "user", "content": str(n)}], TOOLS, 100, {})) for n in range(4)]
            self.assertTrue(fake.wait_prompts(3))
            self.assertEqual(sorted(fake.registrations), ["pi0", "pi1", "pi2"])
            self.assertEqual(len(controller._leases), 3)
            sid = fake.prompts[0][0]
            fake.emit("session.idle", sessionID=sid)
            self.assertTrue(fake.wait_prompts(4))
            for sid, _ in fake.prompts[1:]:
                fake.emit("session.idle", sessionID=sid)
            for future in futures:
                self.assertEqual(future.result(timeout=3)[1][-1]["choices"][0]["finish_reason"], "stop")
        self.assertEqual(controller._leases, {})

    def test_cancel_and_close_settle_owned_resources(self):
        fake, provider, context, controller = self.setup_fixture("silent")
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(collect, provider.events("fixture/model", [{"role": "user", "content": "wait"}], TOOLS, 100, {}))
            self.assertTrue(fake.wait_prompts(1))
            context.cancelled.set()
            with self.assertRaisesRegex(RuntimeError, "已取消"):
                future.result(timeout=4)
        provider.close()
        self.assertTrue(fake.aborted)
        self.assertEqual(len(fake.deleted), 1)
        self.assertEqual(controller._leases, {})
        self.assertFalse(provider._states)

    def test_branch_history_starts_isolated_session(self):
        fake, provider, _, _ = self.setup_fixture("silent")
        with concurrent.futures.ThreadPoolExecutor() as pool:
            first = pool.submit(collect, provider.events("fixture/model", [{"role": "user", "content": "same"}], TOOLS, 100, {}))
            self.assertTrue(fake.wait_prompts(1))
            fake.emit("session.idle", sessionID="ses-1")
            first.result(timeout=2)
            branch = pool.submit(collect, provider.events("fixture/model", [{"role": "user", "content": "different"}], TOOLS, 100, {}))
            self.assertTrue(fake.wait_prompts(2))
            fake.emit("session.idle", sessionID="ses-2")
            branch.result(timeout=2)
        self.assertEqual(fake.session_count, 2)

    def test_pre_cancel_never_acquires_or_creates_session(self):
        fake, provider, context, controller = self.setup_fixture("silent")
        context.cancelled.set()
        with self.assertRaisesRegex(RuntimeError, "已取消"):
            collect(provider.events("fixture/model", [{"role": "user", "content": "cancel"}], TOOLS, 100, {}))
        self.assertEqual(fake.session_count, 0)
        self.assertEqual(controller._leases, {})

    def test_inactivity_timeout_deletes_session_and_releases(self):
        fake, provider, _, controller = self.setup_fixture("silent", inactivity_timeout=0.2)
        with self.assertRaisesRegex(RuntimeError, "长时间没有返回内容"):
            collect(provider.events("fixture/model", [{"role": "user", "content": "timeout"}], TOOLS, 100, {}))
        self.assertEqual(len(fake.deleted), 1)
        self.assertEqual(controller._leases, {})

    def test_refresh_timeout_returns_error_and_settles_pending_rpc(self):
        fake, provider, _, controller = self.setup_fixture("refresh", request_timeout=0.2)
        messages = [{"role": "user", "content": "discover"}]
        assistant, _ = collect(provider.events("fixture/model", messages, TOOLS, 100, {}))
        messages += [assistant, {"role": "tool", "call_id": assistant["tool_calls"][0]["id"], "content": "changed"}]
        with self.assertRaisesRegex(RuntimeError, "长时间没有返回内容"):
            collect(provider.events("fixture/model", messages, [{**TOOLS[0], "name": "cube"}], 100, {}))
        self.assertEqual(len(fake.deleted), 1)
        self.assertEqual(controller._leases, {})
        self.assertTrue(fake.results[0]["isError"])

    def test_close_during_session_creation_deletes_acknowledged_session(self):
        fake, provider, _, controller = self.setup_fixture("silent")
        entered, resume = threading.Event(), threading.Event()
        original = provider._open

        def delayed(state, path, *args, **kwargs):
            result = original(state, path, *args, **kwargs)
            if path == "/session":
                entered.set()
                resume.wait(2)
            return result

        provider._open = delayed
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(collect, provider.events("fixture/model", [{"role": "user", "content": "close"}], TOOLS, 100, {}))
            self.assertTrue(entered.wait(2))
            closing = pool.submit(provider.close)
            resume.set()
            closing.result(timeout=3)
            with self.assertRaisesRegex(RuntimeError, "已取消"):
                future.result(timeout=3)
        self.assertEqual(fake.deleted, ["/session/ses-1"])
        self.assertEqual(controller._leases, {})

    def test_generator_close_cancels_held_tool_request(self):
        fake, provider, _, controller = self.setup_fixture()
        events = provider.events("fixture/model", [{"role": "user", "content": "tool"}], TOOLS, 100, {})
        first = next(events)
        self.assertTrue(first["choices"][0]["delta"]["tool_calls"])
        events.close()
        self.assertTrue(fake.aborted)
        self.assertEqual(fake.deleted, ["/session/ses-1"])
        self.assertEqual(controller._leases, {})
        self.assertFalse(provider._states)

    def test_english_errors_and_service_messages_are_plugin_localized(self):
        _, provider, context, controller = self.setup_fixture("silent")
        context.language = "en"
        context.cancelled.set()
        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            collect(provider.events("fixture/model", [{"role": "user", "content": "cancel"}], TOOLS, 100, {}))
        controller.language = "en"
        with self.assertRaisesRegex(ValueError, "request ID is invalid"):
            controller.handle({"action": "acquire", "requestId": ""})

    def test_account_instances_share_package_wide_three_request_limit(self):
        _, first, _, first_control = self.setup_fixture("silent")
        _, second, _, second_control = self.setup_fixture("silent")
        states = [transport._State("fixture/model", [], TOOLS) for _ in range(4)]
        owners = [first, first, second, second]
        for owner, state in zip(owners, states):
            self.addCleanup(owner._cleanup, state)
        for owner, state in zip(owners[:3], states[:3]):
            owner._acquire(state)
        self.assertEqual(len(first_control._leases) + len(second_control._leases), 3)
        started = threading.Event()

        def fourth():
            started.set()
            second._acquire(states[3])

        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(fourth)
            self.assertTrue(started.wait(1))
            self.assertFalse(future.done())
            first._release(states[0])
            future.result(timeout=2)
        self.assertEqual(len(first_control._leases) + len(second_control._leases), 3)

    def test_request_scoped_cancel_aborts_only_matching_quiet_request(self):
        fake, provider, original, controller = self.setup_fixture("silent")

        class ScopedContext:
            cancelled = original.cancelled
            language = "zh"
            scope = ContextVar("codearts-test-request-cancel", default=None)

            @property
            def request_cancelled(self):
                return self.scope.get() or self.cancelled

        context = ScopedContext()
        provider.context = context
        first_cancel, second_cancel = threading.Event(), threading.Event()

        def request(label, cancel):
            token = context.scope.set(cancel)
            try:
                return collect(provider.events("fixture/model", [{"role": "user", "content": label}], TOOLS, 100, {}))
            finally:
                context.scope.reset(token)

        with concurrent.futures.ThreadPoolExecutor() as pool:
            first = pool.submit(request, "first quiet request", first_cancel)
            second = pool.submit(request, "second quiet request", second_cancel)
            self.assertTrue(fake.wait_prompts(2))
            first_sid = next(sid for sid, body in fake.prompts if any(p.get("text") == "first quiet request" for p in body["parts"]))
            second_sid = next(sid for sid, body in fake.prompts if any(p.get("text") == "second quiet request" for p in body["parts"]))
            first_cancel.set()
            with self.assertRaisesRegex(RuntimeError, "已取消"):
                first.result(timeout=3)
            self.assertFalse(second.done())
            self.assertFalse(context.cancelled.is_set())
            self.assertEqual(fake.deleted, ["/session/" + first_sid])
            fake.emit("session.idle", sessionID=second_sid)
            self.assertEqual(second.result(timeout=3)[1][-1]["choices"][0]["finish_reason"], "stop")
        self.assertEqual(controller._leases, {})

    def test_broker_keepalive_peer_reset_closes_without_handler_traceback(self):
        _, provider, _, _ = self.setup_fixture("silent")
        state = transport._State("fixture/model", [], TOOLS)
        state.slot = 0
        url = provider._broker(state)
        self.addCleanup(provider._cleanup, state)
        done, errors = threading.Event(), []
        original = state.broker.RequestHandlerClass

        class RecordingHandler(original):
            def handle(self):
                try:
                    super().handle()
                finally:
                    done.set()

        state.broker.RequestHandlerClass = RecordingHandler
        state.broker.handle_error = lambda *_args: errors.append("handler error")
        target = urlsplit(url)
        conn = http.client.HTTPConnection(target.hostname, target.port, timeout=2)
        try:
            conn.request("POST", target.path, json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}),
                         {"Content-Type": "application/json"})
            response = conn.getresponse()
            self.assertEqual(json.loads(response.read())["result"], {})
            # Force an actual TCP reset while the broker waits for the next
            # HTTP/1.1 request, matching the official client's close sequence.
            conn.sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER,
                                 struct.pack("hh" if os.name == "nt" else "ii", 1, 0))
        finally:
            conn.close()
        self.assertTrue(done.wait(2))
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
