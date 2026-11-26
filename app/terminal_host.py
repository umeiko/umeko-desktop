"""Expose the desktop's live Pi sessions to same-user terminal clients."""
from __future__ import annotations

from pathlib import Path
import threading
import time
import uuid

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QLocalServer

from .model_groups import GROUP_PROVIDER
from .terminal_ipc import MAX_FRAME, encode, endpoint, frames
from .terminal_transcript import TranscriptFeed
from .transcript_index import StaleIndex
from .transcripts import preview


def message_rows(messages, *, terminal=False):
    rows = []
    for row in messages if terminal else messages[-48:]:
        tools = [{**{key: tool.get(key) for key in ("id", "name", "state", "path")},
                  "result": str(tool.get("result") or "")[-900:]}
                 for tool in row.get("tools", [])[-6:]]
        text = str(row.get("text") or "")
        compaction = row.get("compaction")
        if terminal and compaction:
            compaction = {**compaction, "summary": str(compaction.get("summary") or "")[:32_000]}
        rows.append({"role": row.get("role"), "text": text if terminal else text[-6500:],
                     "thinking": str(row.get("thinking") or "") if terminal else "",
                     "error": bool(row.get("error")), "tools": tools, "compaction": compaction,
                     **({"entryId": row.get("entryId")} if terminal else {})})
    return rows


class TerminalHost(QObject):
    historyReady = Signal(object, object, object)

    def __init__(self, controller):
        super().__init__(controller)
        self.controller = controller
        self.peers = {}
        self.protocol_peers = set()
        self.tui_peers = set()
        self.transcripts = {}
        self.dirty = set()
        self.loading = set()
        self.history_error = {}
        self.index_rows = {}
        self.index_views = {}
        self.pending = {}
        self.waiting = {}
        self.stop_pending = set()
        self.server = QLocalServer(self)
        name = endpoint(controller.store.directory)
        QLocalServer.removeServer(name)
        self.server.setSocketOptions(QLocalServer.UserAccessOption)
        if not self.server.listen(name):
            raise OSError(self.server.errorString())
        self.server.newConnection.connect(self._accept)
        self.flush = QTimer(self, interval=65, singleShot=True)
        self.flush.timeout.connect(self._publish)
        self.historyReady.connect(self._history_ready)
        controller._pool.event.connect(self._event)
        controller.jobDone.connect(self._index_updated)
        controller.reasoningChanged.connect(self._visible_changed)
        controller.changed.connect(self._visible_changed)

    def _accept(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            if len(self.peers) >= 16:
                socket.disconnectFromServer()
                socket.deleteLater()
                continue
            self.peers[socket] = None
            socket.readyRead.connect(lambda sock=socket: self._read(sock))
            socket.disconnected.connect(lambda sock=socket: self._disconnect(sock))
            socket.bytesWritten.connect(lambda _size, sock=socket: self._pump_transcript(sock))

    def _disconnect(self, socket):
        self.protocol_peers.discard(socket)
        self.tui_peers.discard(socket)
        self.transcripts.pop(socket, None)
        record = self.peers.pop(socket, None)
        if record is not None:
            record.terminal_clients -= 1
            if not record.terminal_clients:
                self.history_error.pop(record.key, None)
                self.index_rows.pop(record.key, None)
                self.index_views.pop(record.key, None)
        socket.deleteLater()

    def _write(self, socket, value):
        if socket.bytesToWrite() > MAX_FRAME:
            socket.abort()
        elif socket in self.peers:
            socket.write(encode(value))

    def _pump_transcript(self, socket):
        feed = self.transcripts.get(socket)
        if feed is None or socket not in self.peers:
            return
        while socket.bytesToWrite() < MAX_FRAME // 4:
            if feed.state and feed.state["busy"]:
                self._write(socket, {"event": "state", "state": feed.state})
                feed.state = None
            frame = feed.next_frame()
            if frame is None:
                # An idle frame finalizes the transcript. Deliver it only
                # after all text already staged for this socket.
                if feed.state is not None:
                    self._write(socket, {"event": "state", "state": feed.state})
                    feed.state = None
                break
            self._write(socket, frame)

    def _read(self, socket):
        try:
            for request in frames(socket):
                try:
                    result = self._handle(socket, request)
                    self._write(socket, {"id": request.get("id"), "result": result})
                except (ValueError, OSError, RuntimeError, KeyError, TypeError) as error:
                    self._write(socket, {"id": request.get("id"), "error": str(error)})
        except (ValueError, UnicodeError):
            socket.abort()

    def _read_history(self, record, snapshot=None, *, earlier=False):
        # The first read of a large transcript stays off the desktop/UI thread.
        self.loading.add(record.key)
        file = record.file
        current = len(self.index_rows.get(record.key, ()))
        depth = max(48, current + 48 if earlier else current)

        def run():
            try:
                repository = self.controller.transcripts
                index = snapshot or (repository.open_recent(file) if repository.large(file) else None)
                if earlier and index and index.partial:
                    index = repository.open(file, leaf=index.leaf)
                if index:
                    first = max(0, index.count - depth)
                    while first and index.metadata(first).get("continuation"):
                        first -= 1
                    try:
                        messages = [index.row(row) for row in range(first, index.count)]
                    except StaleIndex:
                        index = repository.open(file)
                        first = max(0, index.count - depth)
                        while first and index.metadata(first).get("continuation"):
                            first -= 1
                        messages = [index.row(row) for row in range(first, index.count)]
                    result = (messages, [], index)
                else:
                    messages, tree = preview(file)
                    result = (messages, tree, None)
                self.historyReady.emit(record, result, None)
            except (ValueError, OSError, RuntimeError, StaleIndex) as error:
                self.historyReady.emit(record, None, str(error))

        threading.Thread(target=run, daemon=True).start()

    def _history_ready(self, record, result, error):
        self.loading.discard(record.key)
        if error:
            self.history_error[record.key] = error
            if record.loaded:
                self._notice(record, "Could not load the indexed transcript.")
        else:
            self.history_error.pop(record.key, None)
            messages, tree, index = result
            if index and record.terminal_clients:
                self.index_rows[record.key] = messages
                self.index_views[record.key] = index
            if not record.busy and not record.loaded:
                record.messages = [] if index else messages
                record.tree, record.transcript = tree, index
                record.loaded = True
                record.body_dirty = True
                if self.controller._view is record:
                    self.controller.chatChanged.emit()
                    self.controller.transcriptChanged.emit()
        self._dirty(record)

    def _attach(self, socket, workspace, identifier, protocol):
        c = self.controller
        if identifier:
            saved = next((row for row in c._sessions if row["id"] == identifier), None)
            meta = c.store.data["sessionMeta"].get(identifier, {})
            record = c._pool.find(identifier)
            if (not saved and (record is None or not record.terminal_owned)) or meta.get("pluginSession") or (saved and saved.get("backend") == "dsh"):
                raise ValueError("No matching Umeko Pi session")
            if identifier in c._session_files.pending or identifier in c._session_files.deleted:
                raise ValueError("The session is being removed")
            if record is None:
                record = c._saved_pi_record(saved, read_transcript=False)
                record.loaded = not bool(record.file)
            if (record.file and record.key not in self.loading and
                    (not record.loaded or (record.transcript and record.key not in self.index_rows))):
                self._read_history(record, record.transcript)
        else:
            path = Path(workspace).expanduser().resolve(strict=True)
            if not path.is_dir():
                raise ValueError("The workspace must be a directory")
            record = c._new_view(str(path))
            record.terminal_owned = True
            if protocol == "acp":
                random = uuid.uuid4().int
                record.id = str(uuid.UUID(int=(time.time_ns() // 1_000_000 << 80) | (7 << 76) | (random & ((1 << 76) - 1))))
            c._ensure_project(str(path), reopen=True)
        if protocol == "acp":
            self.protocol_peers.add(socket)
        elif protocol == "tui":
            self.tui_peers.add(socket)
        previous = self.peers[socket]
        if previous is not record:
            if previous is not None:
                previous.terminal_clients -= 1
                if not previous.terminal_clients:
                    self.index_rows.pop(previous.key, None)
                    self.index_views.pop(previous.key, None)
                    self.history_error.pop(previous.key, None)
            self.peers[socket] = record
            record.terminal_clients += 1
        c._pool.touch(record, dirty=False)
        return self._state(record, include_messages=socket not in self.tui_peers)

    def _messages(self, record):
        messages = record.messages
        if record.transcript:
            live = {row.get("entryId") for row in messages if row.get("entryId")}
            rows = self.index_rows.get(record.key, ())
            messages = [*[row for row in rows if row.get("entryId") not in live], *messages]
        return messages

    def _state(self, record, *, include_messages=True):
        state = {
            "id": record.id, "title": record.title, "cwd": record.workspace,
            "provider": record.provider, "model": record.model,
            "effort": record.reasoning_effort,
            "pendingModel": record.pending_selection[1] if record.pending_selection else None,
            "pendingEffort": record.pending_reasoning_effort,
            "usage": record.context_usage, "status": record.tool_status,
            "phase": ("loading-history" if record.key in self.loading and not record.loaded else
                      "waiting" if record.key in self.waiting else record.phase),
            "busy": record.busy or (record.key in self.loading and not record.loaded), "failed": record.failed,
            "cancelled": record.cancelled, "compacting": record.compaction_running,
            "historyError": self.history_error.get(record.key, ""),
            "historyEarlier": self._has_earlier(record),
            "queue": [{**row, "text": row["text"][:500]} for row in [*record.queue, *self.pending.get(record.key, [])][:100]],
            "agents": [{"id": row.get("id"), "name": row.get("profileName") or row.get("name") or row.get("type") or "Subagent",
                        "status": row.get("status"), "task": str(row.get("task") or row.get("description") or row.get("prompt") or "")[:300],
                        "started": row.get("startedAt")}
                       for row in list(record.subagents.values())[-24:]],
            "approval": {key: record.approval[key] for key in ("id", "method", "title", "detail", "options") if key in record.approval},
        }

        if include_messages:
            state["messages"] = message_rows(self._messages(record))
        return state

    def _has_earlier(self, record):
        index = self.index_views.get(record.key)
        return bool(index and (index.partial or len(self.index_rows[record.key]) < index.count))

    def _index_updated(self, name, result):
        if not name.startswith("transcript:") or not result.get("ok"):
            return
        record = self.controller._pool.records.get(name.split(":", 1)[1])
        if record is not None and record.terminal_clients:
            self._dirty(record)

    def _visible_changed(self):
        self._dirty(self.controller._view)

    def _dirty(self, record):
        if record.terminal_clients or record.key in self.pending:
            self.dirty.add(record.key)
            if not self.flush.isActive():
                self.flush.start()

    @staticmethod
    def _steerable(queue):
        return all(not item.get("hold") and not item["text"].startswith("!")
                   for item in queue)

    def _return_pending(self, record):
        pending = self.pending.pop(record.key, [])
        if pending:
            payload = {"event": "queue_returned", "followUp": [
                ("/compact " if item["mode"] == "compact" else "") + item["text"] for item in pending]}
            for socket, attached in tuple(self.peers.items()):
                if attached is record:
                    self._write(socket, payload)

    def _notice(self, record, message):
        for socket, attached in tuple(self.peers.items()):
            if attached is record:
                self._write(socket, {"event": "notice", "message": message})

    def _event(self, record, event):
        kind = event.get("type")
        if kind == "tool" and event.get("name") == "background_job":
            call = event.get("id")
            if event.get("state") == "running" and event.get("args", {}).get("action") == "wait":
                self.waiting.setdefault(record.key, set()).add(call)
                if record.terminal_owned and record.queue and self._steerable(record.queue):
                    self.controller._write_pi({"type": "terminal-steer"}, record)
            elif call in self.waiting.get(record.key, ()):
                waits = self.waiting[record.key]
                waits.discard(call)
                if not waits:
                    del self.waiting[record.key]
        elif kind in ("done", "exit"):
            self.waiting.pop(record.key, None)
            if record.cancelled or (record.failed and (record.action != "compact" or kind == "exit")):
                self._return_pending(record)
        if record.terminal_clients and kind in ("queue_rejected", "queue_returned", "notice"):
            payload = {"event": kind}
            for key in ("text", "message", "messageId", "followUp", "steering"):
                if key in event:
                    payload[key] = event[key]
            for socket, attached in tuple(self.peers.items()):
                if attached is record:
                    self._write(socket, payload)
        if event.get("type") in ("delta", "thinking_delta", "tool", "done", "exit", "error"):
            for socket in tuple(self.protocol_peers):
                if self.peers.get(socket) is record:
                    fields = {key: event[key] for key in ("type", "text", "message", "name", "id", "path", "state") if key in event}
                    self._write(socket, {"event": "runtime", "value": fields})
        self._dirty(record)

    def _publish(self):
        dirty, self.dirty = self.dirty, set()
        for key in dirty:
            record = self.controller._pool.records.get(key)
            if record is None:
                self.pending.pop(key, None)
                continue
            if key in self.stop_pending and record.phase in ("running", "idle"):
                self.stop_pending.discard(key)
                self.controller._stop(record)
            self._drain(record)
            if not record.terminal_clients:
                continue
            state = self._state(record, include_messages=False)
            rows, full_rows = None, None
            for socket, attached in tuple(self.peers.items()):
                if record is not attached:
                    continue
                if socket in self.tui_peers:
                    feed = self.transcripts.get(socket)
                    if feed is None:
                        self._write(socket, {"event": "state", "state": state})
                    else:
                        index = record.transcript
                        cached = self.index_views.get(record.key)
                        stale = index and (cached is None or cached.size < index.size
                                           or (cached.size == index.size and cached.leaf != index.leaf))
                        if stale and record.key not in self.history_error:
                            if record.key not in self.loading:
                                self._read_history(record, index)
                            continue
                        if full_rows is None:
                            full_rows = message_rows(self._messages(record), terminal=True)
                        feed.state = state
                        if full_rows != feed.sent:
                            feed.latest = full_rows
                        elif feed.latest is not None:
                            feed.latest = None
                        self._pump_transcript(socket)
                else:
                    if rows is None:
                        rows = message_rows(self._messages(record))
                    self._write(socket, {"event": "state", "state": {**state, "messages": rows}})

    def _drain(self, record):
        queue = self.pending.get(record.key)
        if not queue or record.key in self.loading or record.approval:
            return
        if record.busy and (record.phase != "running" or record.action != "prompt"):
            return
        first = queue[0]
        if first["mode"] == "compact":
            if record.busy or record.queue:
                return
            if first["autoSerial"] != record.auto_compaction_serial:
                self._notice(record, "Skipped queued /compact because the context was automatically compacted.")
            elif not record.file or not self.controller._request_compaction(record, first["text"]):
                self._notice(record, "Could not start queued /compact.")
            accepted = True
        else:
            accepted = self.controller._send(first["text"], terminal_record=record, hold=bool(first.get("hold")))
        if accepted:
            queue.pop(0)
            if queue:
                self._dirty(record)
            else:
                self.pending.pop(record.key, None)

    def _models(self):
        controller = self.controller
        provider_ids = {row["id"] for row in controller.store.data["providers"] if row["api"] != "image"}
        return [{"provider": row["providerID"], "name": row["owned_by"], "model": row["id"],
                 "efforts": ["off", *[level for level in row["reasoningLevels"] if level != "off"]]}
                for row in controller.gateway.models() if row["providerID"] in provider_ids]

    def _select_model(self, record, request):
        c = self.controller
        selected = next((row for row in self._models() if row["model"] == request["model"]), None)
        if selected is None:
            raise ValueError("Unknown model alias")
        leaving_group = record.provider == GROUP_PROVIDER
        if leaving_group and (record.busy or record.subagents_active):
            raise ValueError("Wait for the model group to finish before switching models")
        effort = request.get("effort")
        if effort is not None and effort not in selected["efforts"]:
            raise ValueError("The selected model does not support this reasoning effort")
        selection = (selected["provider"], selected["model"])
        if record.busy:
            record.pending_selection = selection
            record.pending_reasoning_effort = effort
            return
        if selection != (record.provider, record.model):
            record.context_usage = {}
        record.provider, record.model = selection
        if leaving_group:
            record.stale = bool(record.process)
        record.pending_selection = record.pending_reasoning_effort = None
        if effort is not None:
            record.reasoning_effort = effort
            if record.id:
                c.store.data["sessionMeta"].setdefault(record.id, {})["reasoningEffort"] = effort
                c.store.save()
        else:
            c._reconcile_reasoning(record)
        if record.id:
            c._index_record(record)
            c.store.save_sessions(c._sessions)
        if record is c._view:
            c._remember_model_selection(record.provider, record.model)
            c.store.data["ui"]["reasoningEffort"] = record.reasoning_effort
            c.store.save()
            c.changed.emit()
            c.reasoningChanged.emit()

    def _provider(self, operation, request):
        controller = self.controller
        plugins = controller.providerPlugins
        identifier = request.get("provider", "")
        if operation == "providers":
            return [{"id": row["id"], "name": row["name"], "api": row["api"],
                     "plugin": row.get("pluginId"), "version": row.get("pluginVersion")}
                    for row in controller.store.data["providers"]]
        if operation == "packages":
            return plugins.packages
        if operation == "presets":
            return [{"id": row["id"], "name": row.get("label") or row["name"]}
                    for row in controller.commonProviders]
        if operation == "save-preset":
            if not controller.addCommonProvider(request["preset"], request["key"], ""):
                raise ValueError("Could not save the provider. Check the API key and try again.")
            return True
        if operation == "install":
            before = {row["id"] for row in controller.store.data["providers"]}
            if not plugins.importZip(QUrl.fromLocalFile(request["path"]).toString()):
                raise ValueError(plugins.importError.get("message", "Unable to import provider ZIP"))
            return next(row["id"] for row in controller.store.data["providers"] if row["id"] not in before)
        if operation == "save-config":
            return plugins.saveConfig(identifier, encode(request["config"]).decode())
        if operation == "save-models":
            return plugins.saveModels(identifier, encode(request["models"]).decode())
        if operation == "refresh":
            return plugins.refreshModels(identifier)
        if operation == "save-provider":
            return controller.saveProvider(identifier, request["name"], request["api"],
                                           request["baseUrl"], request.get("key", ""),
                                           encode(request["models"]).decode().strip())
        raise ValueError("Unknown provider command")

    def _handle(self, socket, request):
        c = self.controller
        operation = request.get("op")
        if operation == "show":
            c._system_tray.restore()
            return True
        if operation == "ping":
            return True
        if operation == "attach":
            return self._attach(socket, request.get("cwd", ""), request.get("session", ""), request.get("protocol"))
        if operation == "sessions":
            return [{key: row.get(key, "") for key in ("id", "title", "workspace", "model")}
                    for row in c._sessions if row.get("backend") != "dsh"
                    and not c.store.data["sessionMeta"].get(row["id"], {}).get("pluginSession")]
        if operation == "models":
            return self._models()
        if operation == "provider":
            return self._provider(request["action"], request)
        record = self.peers[socket]
        if record is None:
            raise ValueError("Attach a session first")
        if operation == "state":
            return self._state(record, include_messages=socket not in self.tui_peers)
        if operation == "transcript" and socket in self.tui_peers:
            self.transcripts.setdefault(socket, TranscriptFeed())
            self._dirty(record)
            return True
        if operation == "history" and socket in self.tui_peers:
            if self._has_earlier(record) and record.key not in self.loading:
                self.history_error.pop(record.key, None)
                self._read_history(record, self.index_views[record.key], earlier=True)
            return True
        if operation == "efforts":
            return ["off", *[level for level in c._reasoning_levels(record) if level != "off"]]
        if operation == "answer":
            if not record.approval or record.approval["id"] != request.get("approval"):
                raise ValueError("This request has already been answered")
            c._write_pi({"type": "ui_response", "id": record.approval["id"], "value": request.get("value")}, record)
            record.approval = {}
            if c._view is record:
                c.approvalChanged.emit()
        elif operation == "abort":
            self._return_pending(record)
            if record.phase == "loading":
                self.stop_pending.add(record.key)
            else:
                c._stop(record)
        elif operation == "model":
            self._select_model(record, request)
            self._dirty(record)
            return {"model": request["model"], "effort": record.pending_reasoning_effort or record.reasoning_effort,
                    "pending": record.pending_selection is not None}
        elif operation == "effort":
            value = request["effort"]
            if value != "off" and value not in c._reasoning_levels(record):
                raise ValueError("The selected model does not support this reasoning effort")
            record.reasoning_effort = value
            if record.id:
                c.store.data["sessionMeta"].setdefault(record.id, {})["reasoningEffort"] = value
                c.store.save()
            c._pool.write(record, {"type": "reasoning_effort", "value": value})
            if record is c._view:
                c.reasoningChanged.emit()
        elif operation in ("send", "steer", "compact"):
            self._input(record, operation, request.get("text", ""), bool(request.get("hold")))
        else:
            raise ValueError("Unknown terminal operation")
        self._dirty(record)
        return True

    def _input(self, record, operation, text, hold):
        text = text.strip()
        if len(text) > 32_000:
            raise ValueError("Input is too large")
        if record.key in self.history_error and not record.loaded:
            raise ValueError(self.history_error[record.key])
        if record.approval:
            raise ValueError("Answer the pending request first")
        queue = self.pending.get(record.key, [])
        compact_queued = any(item["mode"] == "compact" for item in queue)
        if operation == "compact" and (compact_queued or (record.busy and record.action == "compact")):
            raise ValueError("A /compact is already running or queued.")
        if operation == "steer" and compact_queued:
            if record.phase == "running" and record.action == "prompt" and record.queue and not record.stop_token:
                self.controller._write_pi({"type": "terminal-steer"}, record)
            if not text:
                return
            operation = "send"
        if (operation == "send" and not hold and record.key in self.waiting and text
                and self._steerable([*record.queue, {"text": text}]) and not self.pending.get(record.key)):
            operation = "steer"
        if operation == "steer" and record.phase == "running" and record.action == "prompt" and not record.stop_token:
            if not text:
                self.controller._write_pi({"type": "terminal-steer"}, record)
                return
            if self.controller._send(text, True, terminal_record=record):
                return
        if operation == "steer" and not text:
            return
        if operation != "compact" and not text:
            return
        if not record.model and operation != "compact":
            raise ValueError("Choose or configure a model with /models.")
        if not record.busy and not record.subagents_active and not record.terminal_owned:
            record.terminal_owned = True
            record.stale = bool(record.process)
        queue = self.pending.get(record.key)
        if not queue and record.key not in self.loading:
            if operation == "compact" and not record.busy:
                if record.file and self.controller._request_compaction(record, text):
                    return
                raise ValueError("No session context to compact")
            if operation != "compact" and self.controller._send(text, terminal_record=record, hold=hold):
                return
            if not record.busy:
                raise ValueError(self.controller._last_send_error or "Umeko could not start this turn")
        queue = self.pending.setdefault(record.key, [])
        if len(queue) >= 20:
            raise ValueError("The pending queue is full")
        queue.append({"id": str(time.monotonic_ns()), "text": text, "mode": operation if operation == "compact" else "followUp",
                      "hold": hold, "autoSerial": record.auto_compaction_serial})

    def close(self):
        self.flush.stop()
        self.server.close()
        for socket in tuple(self.peers):
            socket.abort()
