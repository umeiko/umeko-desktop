"""ACP v1 stdio preview backed by the same desktop session host."""
from __future__ import annotations

import json
from pathlib import Path
from queue import Empty, Queue
import sys
import threading
import time

from .project_info import VERSION
from .terminal_client import TerminalClient

MAX_REQUEST = 2 * 1024 * 1024


class ACP:
    def __init__(self):
        self.sessions = {}
        self.turns = {}
        self.permissions = {}
        self.sequence = 0
        self.initialized = False

    def write(self, **message):
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", **message}, ensure_ascii=False) + "\n")
        sys.stdout.flush()

    def respond(self, identifier, result):
        if identifier is not None:
            self.write(id=identifier, result=result)

    def error(self, identifier, message, code=-32602):
        if identifier is not None:
            self.write(id=identifier, error={"code": code, "message": message})

    def update(self, session, kind, **update):
        self.write(method="session/update", params={
            "sessionId": session, "update": {"sessionUpdate": kind, **update},
        })

    def options(self, client):
        state = client.call("state")
        models = [{"value": row["model"], "name": row["model"]} for row in client.call("models")]
        efforts = [{"value": value, "name": value} for value in client.call("efforts")]
        options = [{"id": "effort", "name": "Thinking level", "category": "thought_level", "type": "select",
                    "currentValue": state["effort"], "options": efforts}]
        if models:
            options.insert(0, {"id": "model", "name": "Model", "category": "model", "type": "select",
                               "currentValue": state["model"] or models[0]["value"], "options": models})
        return options

    def open(self, params, load):
        if params.get("mcpServers"):
            raise ValueError("The Umeko ACP preview accepts an empty mcpServers list")
        if not Path(params["cwd"]).is_absolute():
            raise ValueError("cwd must be absolute")
        identifier = params.get("sessionId", "") if load else ""
        if identifier in self.turns:
            raise ValueError("The session already has an active ACP prompt")
        client = TerminalClient()
        try:
            state = client.call("attach", cwd=params["cwd"], session=identifier, protocol="acp")
            if load and Path(state["cwd"]).resolve() != Path(params["cwd"]).resolve():
                raise ValueError("cwd does not match the saved Umeko session")
            if load:
                deadline = time.monotonic() + 8
                while state["phase"] == "loading-history" and time.monotonic() < deadline:
                    time.sleep(0.05)
                    state = client.call("state")
                if state["phase"] == "loading-history" or state.get("historyError"):
                    raise ValueError(state.get("historyError") or "Loading session history timed out")
            session = state["id"]
            old = self.sessions.get(session)
            if old:
                old.close()
            self.sessions[session] = client
            if load:
                for row in state["messages"]:
                    if row["role"] in ("user", "assistant") and row["text"]:
                        self.update(session, "user_message_chunk" if row["role"] == "user" else "agent_message_chunk",
                                    content={"type": "text", "text": row["text"]})
            return {"configOptions": self.options(client), **({} if load else {"sessionId": session})}
        except (OSError, ValueError, RuntimeError, KeyError, TypeError):
            client.close()
            raise

    def _answer(self, response):
        pending = self.permissions.pop(response.get("id"), None)
        if not pending:
            return
        session, request, options = pending
        if session not in self.turns:
            return
        outcome = (response.get("result") or {}).get("outcome") or {}
        option = outcome.get("optionId")
        value = options.get(option) if outcome.get("outcome") == "selected" else None
        self.sessions[session].send("answer", approval=request, value=value)

    def handle(self, request):
        identifier = request.get("id")
        method = request.get("method")
        params = request.get("params") or {}
        try:
            if not method:
                self._answer(request)
                return
            if method == "initialize":
                self.initialized = True
                self.respond(identifier, {"protocolVersion": 1, "agentInfo": {
                    "name": "umeko", "title": "Umeko ACP Preview", "version": VERSION},
                    "authMethods": [], "agentCapabilities": {"loadSession": True,
                    "sessionCapabilities": {"list": {}, "close": {}}}})
                return
            if not self.initialized:
                raise ValueError("Initialize ACP first")
            if method in ("session/new", "session/load"):
                self.respond(identifier, self.open(params, method == "session/load"))
            elif method == "session/list":
                client = TerminalClient()
                try:
                    rows = client.call("sessions")
                finally:
                    client.close()
                cwd = params.get("cwd")
                self.respond(identifier, {"sessions": [
                    {"sessionId": row["id"], "cwd": row["workspace"], "title": row["title"]}
                    for row in rows if row["workspace"] and (not cwd or Path(row["workspace"]).resolve() == Path(cwd).resolve())]})
            elif method == "session/prompt":
                session = params["sessionId"]
                if session in self.turns or self.sessions[session].call("state")["busy"]:
                    raise ValueError("This Umeko session is already active")
                blocks = params["prompt"]
                if any(block["type"] != "text" for block in blocks):
                    raise ValueError("The Umeko ACP preview accepts text prompts")
                text = "\n".join(block["text"] for block in blocks).strip()
                if not text:
                    raise ValueError("The prompt is empty")
                message = self.sessions[session].send("send", text=text)
                self.turns[session] = {"id": identifier, "message": message, "approval": None, "tools": set()}
            elif method == "session/cancel":
                session = params["sessionId"]
                if session in self.turns:
                    self.turns[session]["cancelled"] = True
                    self.sessions[session].send("abort")
            elif method == "session/close":
                session = params["sessionId"]
                if session in self.turns:
                    raise ValueError("Cancel the active prompt before closing")
                self.sessions.pop(session).close()
                self.respond(identifier, {})
            elif method == "session/set_config_option":
                client = self.sessions[params["sessionId"]]
                key, value = params["configId"], params["value"]
                if key not in ("model", "effort"):
                    raise ValueError("Unknown Umeko configuration option")
                client.call(key, **{key: value})
                self.respond(identifier, {"configOptions": self.options(client)})
            else:
                self.error(identifier, "Method not found", -32601)
        except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
            self.error(identifier, str(error))

    def _permission(self, session, approval):
        method = approval.get("method")
        request = approval["id"]
        if method == "confirm":
            values = {"allow": True, "reject": False}
            options = [{"optionId": "allow", "name": "Allow once", "kind": "allow_once"},
                       {"optionId": "reject", "name": "Reject", "kind": "reject_once"}]
        elif method == "select":
            values = {str(index): value for index, value in enumerate(approval.get("options") or [])}
            options = [{"optionId": identifier, "name": value, "kind": "allow_once"} for identifier, value in values.items()]
        else:
            self.sessions[session].send("answer", approval=request, value=None)
            return
        self.sequence += 1
        identifier = f"permission-{self.sequence}"
        self.permissions[identifier] = (session, request, values)
        self.write(id=identifier, method="session/request_permission", params={"sessionId": session,
                   "toolCall": {"toolCallId": str(request), "title": approval.get("title") or "Umeko tool",
                                "status": "pending", "rawInput": approval.get("detail")}, "options": options})

    def _runtime(self, session, event, turn):
        kind = event["type"]
        if kind in ("delta", "thinking_delta"):
            self.update(session, "agent_message_chunk" if kind == "delta" else "agent_thought_chunk",
                        content={"type": "text", "text": event.get("text", "")})
        elif kind == "tool" and event.get("id"):
            identifier = event["id"]
            status = {"done": "completed", "error": "failed"}.get(event.get("state"), "in_progress")
            if identifier not in turn["tools"]:
                turn["tools"].add(identifier)
                self.update(session, "tool_call", toolCallId=identifier, title=event.get("name", "Tool"), status=status)
            else:
                self.update(session, "tool_call_update", toolCallId=identifier, status=status)
        elif kind in ("done", "exit"):
            del self.turns[session]
            self.permissions = {key: value for key, value in self.permissions.items() if value[0] != session}
            if turn.get("cancelled"):
                self.respond(turn["id"], {"stopReason": "cancelled"})
            elif turn.get("error") or kind == "exit":
                self.error(turn["id"], turn.get("error") or "Umeko Pi runtime exited", -32603)
            else:
                self.respond(turn["id"], {"stopReason": "end_turn"})
        elif kind == "error":
            turn["error"] = event.get("message", "Umeko Pi error")

    def poll(self):
        for session, client in tuple(self.sessions.items()):
            if not client.alive:
                turn = self.turns.pop(session, None)
                if turn:
                    self.error(turn["id"], "Umeko Desktop disconnected", -32603)
                del self.sessions[session]
                continue
            for frame in client.read():
                turn = self.turns.get(session)
                if not turn:
                    continue
                if frame.get("id") == turn["message"] and frame.get("error"):
                    self.error(turn["id"], frame["error"])
                    del self.turns[session]
                elif frame.get("event") == "runtime":
                    self._runtime(session, frame["value"], turn)
                elif frame.get("event") == "state":
                    approval = frame["state"].get("approval") or {}
                    if approval and approval.get("id") != turn["approval"]:
                        turn["approval"] = approval["id"]
                        self._permission(session, approval)


def run_acp():
    requests = Queue(maxsize=32)

    def read():
        while line := sys.stdin.buffer.readline(MAX_REQUEST + 1):
            requests.put(line)
            if len(line) > MAX_REQUEST:
                break
        requests.put(None)

    threading.Thread(target=read, daemon=True).start()
    acp = ACP()
    try:
        while True:
            try:
                line = requests.get(timeout=0.03)
                if line is None:
                    return 0
                try:
                    if len(line) > MAX_REQUEST:
                        raise ValueError("ACP request is too large")
                    request = json.loads(line)
                    if not isinstance(request, dict):
                        raise ValueError("Expected a JSON-RPC object")
                    acp.handle(request)
                except (ValueError, UnicodeError) as error:
                    acp.write(id=None, error={"code": -32700, "message": str(error)})
            except Empty:
                pass
            acp.poll()
    finally:
        for client in acp.sessions.values():
            client.close()
