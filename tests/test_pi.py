"""Verify upstream Pi tools, resources and native sessions through the real bridge."""
import json
import base64
import os
import queue
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from app.gateway import Gateway, LocalServer
from app.integration import Completion
from app.pi_runtime import node_executable, RELEASE_NAME
from app.storage import Store
from app.transcripts import preview

ROOT = Path(__file__).resolve().parents[1]
FULL_TOOLS = {"read", "bash", "powershell", "edit", "write", "grep", "find", "ls", "codemode", "tool_search"}


class PiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.store = Store(self.path / "data")
        self.store.data.update(selectedProvider="internal", selectedModel="umeko-default", providers=[{"id":"internal", "name":"Fixture", "api":"internal", "baseUrl":"", "key":"", "models":[{"upstream":"default", "alias":"umeko-default"}]}])
        self.calls = []
        self.tool_name = "write"
        self.gateway = Gateway(self.store, self)
        self.server = LocalServer(self.gateway, 0, "pi-fixture-key", private=True)
        agent = self.path / "agent"
        (agent / "skills/fixture").mkdir(parents=True)
        (agent / "skills/fixture/SKILL.md").write_text("---\nname: fixture\ndescription: Local fixture skill\n---\nSKILL_MARKER_NATIVE\n", encoding="utf-8")
        (agent / "extensions").mkdir()
        (agent / "extensions/probe.js").write_text('''export default function(pi) {
          pi.on("before_agent_start", async () => ({ systemPrompt: "EXTENSION_MARKER_NATIVE" }));
          pi.registerCommand("fixture-confirm", { description: "fixture", handler: async (_args, ctx) => {
            const allowed = await ctx.ui.confirm("Native extension", "Confirm fixture");
            ctx.ui.notify(allowed ? "EXTENSION_CONFIRMED" : "EXTENSION_DENIED");
          }});
        }''', encoding="utf-8")
        self.payload = {"type": "inspect", "gateway": f"http://127.0.0.1:{self.server.port}/", "token": "pi-fixture-key",
            "model": "umeko-default", "models": self.gateway.models(), "workspace": str(self.path), "defaultCwd": str(self.path),
            "agentDir": str(agent), "sessionDir": str(self.path / "sessions"), "agent": {}}
        self.start()

    def complete(self, model, messages, tools, max_tokens):
        self.calls.append((model, messages, tools))
        if hasattr(self, "response_fn"):
            return self.response_fn(model, messages, tools, max_tokens)
        if not tools:
            return Completion("Summary: fixture workspace and native file operations completed.", input_tokens=100, output_tokens=12)
        if messages[-1]["role"] != "tool":
            arguments = {"path": "native.txt", "content": "native tool result"} if self.tool_name == "write" else {}
            return Completion(tool_calls=[{"id": "native-tool", "name": self.tool_name, "arguments": arguments}])
        return Completion("native complete", input_tokens=10, output_tokens=3)

    def start(self):
        self.process = subprocess.Popen([node_executable(), str(ROOT / "runtime/releases" / RELEASE_NAME / "bridge.mjs")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        self.events, self.errors = queue.Queue(), []
        self.reader = threading.Thread(target=lambda: [self.events.put(json.loads(line)) for line in self.process.stdout if line.startswith("{")], daemon=True)
        self.reader.start()
        self.stderr_reader = threading.Thread(target=lambda: self.errors.extend(self.process.stderr.readlines()), daemon=True)
        self.stderr_reader.start()

    def send(self, payload):
        self.process.stdin.write(json.dumps(payload) + "\n")
        self.process.stdin.flush()

    def command(self, payload):
        self.send(payload)
        output = []
        while True:
            try:
                event = self.events.get(timeout=20)
            except queue.Empty:
                self.fail("Pi timeout: " + "".join(self.errors))
            output.append(event)
            if event.get("type") == "ui_request":
                self.send({"type": "ui_response", "id": event["id"], "value": True})
            if event.get("type") == "done":
                break
        self.assertFalse([e for e in output if e.get("type") == "error"], output)
        return output

    def stop(self):
        if self.process.poll() is None:
            self.send({"type": "shutdown"})
            self.process.wait(timeout=10)
        self.reader.join(timeout=2)
        self.stderr_reader.join(timeout=2)
        self.process.stdin.close(); self.process.stdout.close(); self.process.stderr.close()

    def tearDown(self):
        try:
            self.stop()
        finally:
            self.server.close()
            self.temp.cleanup()

    def test_native_skills_extensions_tool_loop_resume_and_fork(self):
        events = self.command(self.payload)
        state = next(e for e in events if e["type"] == "state")
        self.assertTrue(FULL_TOOLS.issubset(set(state["resources"]["tools"])))
        self.assertIn("fixture", [s["name"] for s in state["resources"]["skills"]])
        self.assertTrue(any(e["path"].endswith("probe.js") for e in state["resources"]["extensions"]))
        events = self.command({"type": "prompt", "text": "/skill:fixture Write native.txt"})
        state = next(e for e in events if e["type"] == "state")
        self.assertEqual((self.path / "native.txt").read_text(), "native tool result")
        self.assertIn("SKILL_MARKER_NATIVE", json.dumps(self.calls[0][1]))
        self.assertIn("EXTENSION_MARKER_NATIVE", json.dumps(self.calls[0][1]))
        file = Path(state["session"]["file"])
        self.assertEqual(preview(file)[0], state["messages"])
        tool = next(tool for message in state["messages"] for tool in message.get("tools", []))
        self.assertEqual(tool["path"], str((self.path / "native.txt").resolve()))
        self.assertEqual(tool["state"], "done")
        entries = [json.loads(line) for line in file.read_text(encoding="utf-8").splitlines()]
        self.assertTrue(any(e.get("message", {}).get("role") == "toolResult" for e in entries))
        original_id = state["session"]["id"]
        events = self.command({"type": "prompt", "text": "/fixture-confirm"})
        self.assertTrue(any(e.get("message") == "EXTENSION_CONFIRMED" for e in events))
        events = self.command({"type": "fork"})
        forked = next(e for e in events if e["type"] == "state")
        self.assertNotEqual(forked["session"]["id"], original_id)
        self.assertEqual(len(forked["messages"]), len(state["messages"]))
        self.stop()
        self.start()
        events = self.command({**self.payload, "sessionFile": str(file)})
        resumed = next(e for e in events if e["type"] == "state")
        self.assertEqual(resumed["session"]["id"], original_id)
        self.assertEqual(len(resumed["messages"]), len(state["messages"]))

    def test_native_reasoning_reaches_live_events_and_cold_history(self):
        self.response_fn = lambda *_: Completion("Visible answer", thinking="Compare the local fixture.")
        self.command(self.payload)
        events = self.command({"type": "prompt", "text": "Reason about the fixture"})
        self.assertEqual("".join(e["text"] for e in events if e["type"] == "thinking_delta"), "Compare the local fixture.")
        message = next(e for e in events if e["type"] == "message" and e["role"] == "assistant")
        self.assertEqual(message["thinking"], "Compare the local fixture.")
        state = next(e for e in events if e["type"] == "state")
        file = state["session"]["file"]
        self.assertEqual(state["messages"][-1]["thinking"], "Compare the local fixture.")
        self.assertEqual(preview(file)[0], state["messages"])
        self.stop(); self.start()
        restored = next(e for e in self.command({**self.payload, "sessionFile": file}) if e["type"] == "state")
        self.assertEqual(restored["messages"], state["messages"])

    def test_native_context_usage_updates_and_compaction_unknown_survives_resume(self):
        (self.path / "agent/settings.json").write_text(json.dumps({"compaction": {"enabled": True, "keepRecentTokens": 50, "reserveTokens": 100}}))
        self.response_fn = lambda *_: Completion("Context fixture result. " * 40, input_tokens=32000, output_tokens=1000)
        state = next(e for e in self.command(self.payload) if e["type"] == "state")
        self.assertEqual(state["contextUsage"]["model"], "umeko-default")
        events = self.command({"type": "prompt", "text": "Check the local fixture. " * 100})
        state = next(e for e in events if e["type"] == "state")
        usage = state["contextUsage"]
        self.assertEqual(usage["tokens"], 33000)
        self.assertEqual(usage["contextWindow"], 128000)
        self.assertAlmostEqual(usage["percent"], 33000 / 128000 * 100)
        self.assertTrue(any(e["type"] == "context_usage" and e["usage"]["tokens"] == 33000 for e in events), events)
        events = self.command({"type": "compact"})
        state = next(e for e in events if e["type"] == "state")
        self.assertIsNone(state["contextUsage"]["tokens"])
        self.assertIsNone(state["contextUsage"]["percent"])
        self.assertTrue(any(e["type"] == "context_usage" and e["usage"]["percent"] is None for e in events))
        self.stop(); self.start()
        restored = next(e for e in self.command({**self.payload, "sessionFile": state["session"]["file"]}) if e["type"] == "state")
        self.assertEqual(restored["contextUsage"], state["contextUsage"])
        updated = next(e for e in self.command({"type": "prompt", "text": "Continue the fixture"}) if e["type"] == "state")
        self.assertEqual(updated["contextUsage"]["tokens"], 33000)

    def test_model_context_override_reaches_native_usage_after_resume(self):
        self.response_fn = lambda *_: Completion("Custom context fixture.", input_tokens=32000, output_tokens=1000)
        self.store.data["providers"][0]["models"][0].update(
            upstream="k3", contextWindow=262144, contextWindowAuto=False)
        self.payload["models"] = self.gateway.models()
        self.command(self.payload)
        state = next(e for e in self.command({"type": "prompt", "text": "Use the local fixture."}) if e["type"] == "state")
        usage = state["contextUsage"]
        self.assertEqual(usage["contextWindow"], 262144)
        self.assertEqual(usage["tokens"], 33000)
        self.assertAlmostEqual(usage["percent"], 33000 / 262144 * 100)
        # The same saved conversation adopts a newly configured limit on reload.
        self.stop(); self.start()
        self.store.data["providers"][0]["models"][0].update(contextWindowAuto=True)
        self.payload["models"] = self.gateway.models()
        state = next(e for e in self.command({**self.payload, "sessionFile": state["session"]["file"]}) if e["type"] == "state")
        self.assertEqual(state["contextUsage"]["contextWindow"], 1048576)
        self.assertAlmostEqual(state["contextUsage"]["percent"], 33000 / 1048576 * 100)

    def test_native_image_payload_and_model_modalities_follow_saved_vision_flag(self):
        probe = self.path / "agent/extensions/vision-probe.js"
        probe.write_text('''export default function(pi) {
          pi.on("session_start", async (_event, ctx) => ctx.ui.notify("MODEL_INPUT:" + ctx.model.input.join(",")));
        }''')
        model = self.store.data["providers"][0]["models"][0]
        model.update(vision=True, visionAuto=False)
        self.payload["models"] = self.gateway.models()
        events = self.command(self.payload)
        self.assertTrue(any(e.get("message") == "MODEL_INPUT:text,image" for e in events), events)
        from PySide6.QtCore import QByteArray, QBuffer, QIODevice
        from PySide6.QtGui import QImage
        pixels = QImage(16, 16, QImage.Format_RGB32)
        pixels.fill(0x668877)
        raw = QByteArray()
        buffer = QBuffer(raw)
        buffer.open(QIODevice.WriteOnly)
        self.assertTrue(pixels.save(buffer, "PNG"))
        buffer.close()
        png = base64.b64encode(bytes(raw)).decode()
        self.response_fn = lambda *_: Completion("Native image received.")
        state = next(e for e in self.command({"type": "prompt", "text": "Read this fixture.", "images": [{"type": "image", "data": png, "mimeType": "image/png"}]}) if e["type"] == "state")
        self.assertEqual(state["messages"][-1]["text"], "Native image received.")
        user = next(message for message in reversed(self.calls[-1][1]) if message["role"] == "user")
        self.assertIsInstance(user["content"], list)
        self.assertTrue(any(block.get("type") == "image_url" and block["image_url"]["url"].startswith("data:image/") and ";base64," in block["image_url"]["url"] for block in user["content"]), user)
        entries = [json.loads(line) for line in Path(state["session"]["file"]).read_text(encoding="utf-8").splitlines()]
        self.assertTrue(any(block.get("type") == "image" for entry in entries for block in entry.get("message", {}).get("content", []) if isinstance(block, dict)))
        self.stop(); self.start()
        model["vision"] = False
        self.payload["models"] = self.gateway.models()
        events = self.command({**self.payload, "sessionFile": state["session"]["file"]})
        self.assertTrue(any(e.get("message") == "MODEL_INPUT:text" for e in events), events)

    def test_all_native_tools_and_optional_extensions_reach_model_after_reload_and_resume(self):
        settings = self.path / "agent/settings.json"
        original = json.dumps({"defaultTools": ["read"], "codemode": {"mode": "only"}})
        settings.write_text(original)
        extension = self.path / "agent/extensions/optional.js"
        extension.write_text('''import { Type } from "typebox";
        export default function(pi) {
          for (const [name, exposure] of [["optional_fixture", "direct"], ["deferred_fixture", "deferred"], ["hidden_fixture", "hidden"]]) {
            pi.registerTool({name, description:"Fixture " + name, exposure, defaultActive:false,
              parameters:Type.Object({}), async execute() {return {content:[{type:"text",text:name + "_RESULT"}],details:{}};}});
          }
        }''', encoding="utf-8")
        (self.path / "search.txt").write_text("FULL_TOOL_MARKER")
        shell_tool, shell_command = ("powershell", "Write-Output FULL_SHELL_MARKER") if os.name == "nt" else ("bash", "printf FULL_SHELL_MARKER")
        script = '''const listing = await tools.ls({path:"."});
        const files = await tools.find({pattern:"*.txt",path:"."});
        const matches = await tools.grep({pattern:"FULL_TOOL_MARKER",path:"search.txt"});
        ''' + f'''const shell = await tools.{shell_tool}({{command:{json.dumps(shell_command)}}});
        text({{listing,files,matches,shell}});'''
        calls = [("codemode", {"code": script}), ("tool_search", {"query": "deferred_fixture", "limit": 1}),
                 ("deferred_fixture", {}), ("optional_fixture", {})]
        def response(model, messages, tools, max_tokens):
            names = {tool["name"] for tool in tools}
            self.assertTrue(FULL_TOOLS.issubset(names), names)
            self.assertIn("optional_fixture", names)
            self.assertNotIn("hidden_fixture", names)
            index = len(self.calls) - 1
            if index < len(calls):
                name, arguments = calls[index]
                return Completion(tool_calls=[{"id": f"full-{index}", "name": name, "arguments": arguments}])
            self.assertIn("deferred_fixture", names)
            return Completion("Full native tool loop completed")
        self.response_fn = response
        state = next(e for e in self.command(self.payload) if e["type"] == "state")
        self.assertTrue(FULL_TOOLS.issubset(set(state["resources"]["tools"])))
        self.assertIn("optional_fixture", state["resources"]["tools"])
        self.assertNotIn("deferred_fixture", state["resources"]["tools"])
        self.command({"type": "prompt", "text": "Run all fixture tools"})
        results = [m for m in self.calls[-1][1] if m["role"] == "tool"]
        self.assertEqual(len(results), len(calls))
        for marker in ("search.txt", "FULL_TOOL_MARKER", "FULL_SHELL_MARKER"):
            self.assertIn(marker, str(results[0]))
        self.assertIn("deferred_fixture_RESULT", str(results[2]))
        self.assertIn("optional_fixture_RESULT", str(results[3]))
        self.assertEqual(settings.read_text(), original)
        # Reload must also activate tools newly registered inactive by an extension.
        extension.write_text(extension.read_text().replace("optional_fixture", "reloaded_fixture"), encoding="utf-8")
        state = next(e for e in self.command({"type": "reload"}) if e["type"] == "state")
        self.assertIn("reloaded_fixture", state["resources"]["tools"])
        self.assertTrue(FULL_TOOLS.issubset(set(state["resources"]["tools"])))
        file = state["session"]["file"]
        for command in ({"type": "fork"}, {"type": "new"}, {"type": "open", "path": file}):
            state = next(e for e in self.command(command) if e["type"] == "state")
            self.assertTrue(FULL_TOOLS.issubset(set(state["resources"]["tools"])))
            self.assertIn("reloaded_fixture", state["resources"]["tools"])
        self.stop(); self.start()
        state = next(e for e in self.command({**self.payload, "sessionFile": file}) if e["type"] == "state")
        self.assertTrue(FULL_TOOLS.issubset(set(state["resources"]["tools"])))
        self.assertIn("reloaded_fixture", state["resources"]["tools"])
        self.assertEqual(settings.read_text(), original)

    def test_no_builtin_models_and_unconfigured_extension_network_blocked(self):
        ai = ROOT / "runtime/releases" / RELEASE_NAME / "node_modules/@earendil-works/pi-ai/dist"
        self.assertEqual((ai / "models.generated.js").read_text().count("= {}"), 3)
        probe = self.path / "agent/extensions/network.js"
        probe.write_text('''export default function(pi) {
          pi.on("session_start", async (_event, ctx) => {
            let blocked = false;
            try { await fetch("https://unconfigured.invalid/"); } catch { blocked = true; }
            if (!blocked) throw new Error("unguarded fetch");
            try { pi.registerProvider("hidden", {baseUrl:"https://unconfigured.invalid", api:"openai-completions", apiKey:"fixture"}); }
            catch { ctx.ui.notify("HIDDEN_PROVIDER_BLOCKED"); }
          });
        }''', encoding="utf-8")
        events = self.command(self.payload)
        self.assertTrue(any(e.get("message") == "HIDDEN_PROVIDER_BLOCKED" for e in events), events)
        self.assertFalse(self.calls)

    def test_native_manual_compaction(self):
        (self.path / "agent/settings.json").write_text(json.dumps({"compaction": {"enabled": True, "keepRecentTokens": 50, "reserveTokens": 100}}))
        self.command(self.payload)
        for index in range(4):
            self.command({"type": "prompt", "text": f"Turn {index}: " + "fixture context " * 80})
        events = self.command({"type": "compact"})
        state = next(e for e in events if e["type"] == "state")
        entries = [json.loads(line) for line in Path(state["session"]["file"]).read_text(encoding="utf-8").splitlines()]
        self.assertTrue(any(e.get("type") == "compaction" for e in entries))

    def test_native_followup_and_steering_queue_promote_without_abort(self):
        started, release = threading.Event(), threading.Event()
        def response(model, messages, tools, max_tokens):
            if len(self.calls) == 1:
                started.set()
                self.assertTrue(release.wait(10))
                return Completion(tool_calls=[{"id": "queued-write", "name": "write", "arguments": {"path": "queued.txt", "content": "native queue"}}])
            return Completion("Native queue handled")
        self.response_fn = response
        self.command(self.payload)
        self.send({"type": "prompt", "text": "Original task"})
        try:
            self.assertTrue(started.wait(10))
            self.send({"type": "follow-up", "text": "FOLLOW_UP_MARKER"})
            self.send({"type": "steer", "text": "STEERING_MARKER"})
            def until(predicate):
                output = []
                while True:
                    event = self.events.get(timeout=15)
                    output.append(event)
                    self.assertNotEqual(event.get("type"), "queue_rejected", event)
                    if predicate(event): return output
            until(lambda e: e.get("type") == "queue" and e.get("followUp") == ["FOLLOW_UP_MARKER"] and e.get("steering") == ["STEERING_MARKER"])
            self.send({"type": "promote-queue"})
            until(lambda e: e.get("type") == "queue" and not e.get("followUp") and len(e.get("steering", [])) == 2)
            release.set()
            output = until(lambda e: e.get("type") == "done")
            self.assertFalse([e for e in output if e.get("type") == "error"], output)
            self.assertEqual((self.path / "queued.txt").read_text(), "native queue")
            state = next(e for e in output if e.get("type") == "state")
            text = "\n".join(m["text"] for m in state["messages"])
            self.assertIn("FOLLOW_UP_MARKER", text)
            self.assertIn("STEERING_MARKER", text)
            self.assertTrue(any("FOLLOW_UP_MARKER" in str(call[1]) for call in self.calls[1:]))
            self.assertTrue(any("STEERING_MARKER" in str(call[1]) for call in self.calls[1:]))
        finally:
            release.set()

    def test_native_rename_export_and_fork_target(self):
        self.command(self.payload)
        first = next(e for e in self.command({"type": "prompt", "text": "first session"}) if e["type"] == "state")
        first_file = Path(first["session"]["file"])
        self.command({"type": "new"})
        self.command({"type": "prompt", "text": "second session"})
        forked = next(e for e in self.command({"type": "fork", "targetFile": str(first_file)}) if e["type"] == "state")
        self.assertEqual(forked["messages"], first["messages"])
        self.assertNotEqual(forked["session"]["id"], first["session"]["id"])
        def action(**payload):
            result = subprocess.run([node_executable(), str(ROOT / "runtime/releases" / RELEASE_NAME / "bridge.mjs"), "--session-action"],
                input=json.dumps({"sessionFile": str(first_file), **payload}), capture_output=True, text=True, encoding="utf-8", timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return json.loads(result.stdout)
        action(action="rename", title="Renamed native session")
        entries = [json.loads(line) for line in first_file.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(entries[-1]["type"], "session_info")
        self.assertEqual(entries[-1]["name"], "Renamed native session")
        export = self.path / "export.jsonl"
        action(action="export", outputFile=str(export))
        self.assertEqual(export.read_bytes(), first_file.read_bytes())

    def test_native_mcp_stdio_project_override_and_tool_call(self):
        server = self.path / "mcp-fixture.mjs"
        server.write_text('''import { createInterface } from "node:readline";
          const rl = createInterface({input:process.stdin});
          rl.on("line", line => {
            const r = JSON.parse(line); if (r.id === undefined) return;
            let result = {};
            if (r.method === "initialize") result = {protocolVersion:r.params.protocolVersion,capabilities:{tools:{}},serverInfo:{name:"fixture",version:"1"}};
            else if (r.method === "tools/list") result = {tools:[{name:"echo",description:"Local fixture",inputSchema:{type:"object",properties:{}}}]};
            else if (r.method === "tools/call") result = {content:[{type:"text",text:process.argv[2]}]};
            process.stdout.write(JSON.stringify({jsonrpc:"2.0",id:r.id,result})+"\\n");
          });''', encoding="utf-8")
        global_config = {"mcpServers": {"fixture": {"command": node_executable(), "args": [str(server), "GLOBAL"], "exposure": "direct"}}}
        project_config = {"mcpServers": {"fixture": {"command": node_executable(), "args": [str(server), "PROJECT"], "exposure": "direct"}}}
        (self.path / "agent/mcp.json").write_text(json.dumps(global_config))
        (self.path / ".pi").mkdir()
        (self.path / ".pi/mcp.json").write_text(json.dumps(project_config))
        state = next(e for e in self.command(self.payload) if e["type"] == "state")
        mcp = state["resources"]["mcp"]
        self.assertEqual(len(mcp), 1, mcp)
        self.assertEqual(mcp[0]["scope"], "project")
        self.assertIn("connected", mcp[0]["state"], state["resources"])
        self.tool_name = mcp[0]["tools"][0]["name"]
        self.command({"type": "prompt", "text": "Call the fixture MCP tool"})
        result = [m for m in self.calls[-1][1] if m["role"] == "tool"][-1]
        self.assertIn("PROJECT", str(result))
        self.assertNotIn("GLOBAL", str(result))
        self.command({"type": "mcp-command", "text": "/mcp reconnect fixture"})
        for exposure in ("codemode", "deferred"):
            with self.subTest(exposure=exposure):
                project_config["mcpServers"]["fixture"]["exposure"] = exposure
                (self.path / ".pi/mcp.json").write_text(json.dumps(project_config))
                # A new branch has no previously activated MCP loadout to restore.
                state = next(e for e in self.command({"type": "new"}) if e["type"] == "state")
                self.assertIn("connected", state["resources"]["mcp"][0]["state"])
                tool = state["resources"]["mcp"][0]["tools"][0]["name"]
                self.assertNotIn(tool, state["resources"]["tools"])
                baseline = len(self.calls)
                def response(model, messages, tools, max_tokens):
                    self.assertTrue(FULL_TOOLS.issubset({t["name"] for t in tools}))
                    index = len(self.calls) - baseline - 1
                    if index == 0:
                        name, arguments = ("codemode", {"code": f"text(await tools.{tool}({{}}));"}) if exposure == "codemode" else ("tool_search", {"query": tool, "limit": 1})
                    elif index == 1 and exposure == "deferred":
                        self.assertIn(tool, {t["name"] for t in tools})
                        name, arguments = tool, {}
                    else:
                        return Completion("MCP native discovery completed")
                    return Completion(tool_calls=[{"id": f"{exposure}-{index}", "name": name, "arguments": arguments}])
                self.response_fn = response
                self.command({"type": "prompt", "text": f"Call fixture through {exposure}"})
                self.assertIn("PROJECT", str(self.calls[-1][1]))

    def test_native_mcp_http_only_configured_endpoint(self):
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                requests.append(body)
                if "id" not in body:
                    self.send_response(202); self.end_headers(); return
                method = body["method"]
                if method == "initialize":
                    result = {"protocolVersion": body["params"]["protocolVersion"], "capabilities": {"tools": {}}, "serverInfo": {"name": "fixture-http", "version": "1"}}
                elif method == "tools/list":
                    result = {"tools": [{"name": "echo", "description": "Local HTTP fixture", "inputSchema": {"type": "object", "properties": {}}}]}
                else:
                    result = {"content": [{"type": "text", "text": "HTTP_TOOL_RESULT"}]}
                output = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": result}).encode()
                self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(output))); self.end_headers(); self.wfile.write(output)
            def do_GET(self):
                self.send_response(405); self.end_headers()
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            config = {"mcpServers": {"web": {"url": f"http://127.0.0.1:{server.server_port}/mcp", "exposure": "direct"}}}
            (self.path / "agent/mcp.json").write_text(json.dumps(config))
            state = next(e for e in self.command(self.payload) if e["type"] == "state")
            mcp = state["resources"]["mcp"][0]
            self.assertIn("connected", mcp["state"], state["resources"])
            self.tool_name = mcp["tools"][0]["name"]
            self.command({"type": "prompt", "text": "Call the HTTP MCP tool"})
            self.assertIn("HTTP_TOOL_RESULT", str(self.calls[-1][1]))
            self.assertTrue(any(r["method"] == "tools/call" for r in requests))
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
