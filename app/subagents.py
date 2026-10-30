"""Session-scoped subagent roster and one independently streamed conversation."""
from __future__ import annotations

import copy
import threading
import uuid
from pathlib import Path

from PySide6.QtCore import QObject, Property, QTimer, Signal, Slot

from .chat_model import ChatModel
from .transcripts import preview, tool_view


ACTIVE = {"queued", "running"}
AVATARS = ("lemon-yakishio", "chika-komari", "kaju-nukumizu", "yumeko-shikiya")
NAMES = ("烧盐柠檬", "小鞠知花", "温水佳树", "志喜屋梦子")


class Subagents(QObject):
    changed = Signal()
    contextChanged = Signal()
    requested = Signal()
    messageSent = Signal(str)
    draftRestored = Signal(str)
    queueChanged = Signal()
    loaded = Signal(object)

    def __init__(self, controller):
        super().__init__(controller)
        self.controller = controller
        self.model = ChatModel(self)
        self.messages = []
        self.owner = None
        self.selected_id = ""
        self.loading = False
        self.error = ""
        self.truncated = False
        self._generation = 0
        self._pending = {}
        self._drafts = {}
        self._attachments = {}
        self._queues = {}
        self._projection_cache = {}
        self._deferred = {}
        self._closed = False
        self._stream = QTimer(self)
        self._stream.setSingleShot(True)
        self._stream.setInterval(32)
        self._stream.timeout.connect(self._publish)
        self._save = QTimer(self)
        self._save.setSingleShot(True)
        self._save.setInterval(500)
        self._save.timeout.connect(controller.store.save)
        self._deadline = QTimer(self)
        self._deadline.setInterval(1000)
        self._deadline.timeout.connect(self._expire)
        self._deadline.start()
        self.loaded.connect(self._loaded)
        controller.viewChanged.connect(self._view_changed)
        controller.changed.connect(self._characters_changed)

    def _characters_changed(self):
        self._projection_cache.clear()
        self.changed.emit()

    def _rows(self, record):
        if not record.subagents:
            saved = self.controller.store.data.get("sessionMeta", {}).get(record.id, {}).get("subagents", [])
            for row in saved:
                if isinstance(row, dict) and isinstance(row.get("id"), str):
                    row = dict(row)
                    if row.get("status") in ACTIVE:
                        row["status"] = "stopped"
                    record.subagents[row["id"]] = row
        return record.subagents

    def _projection(self, record):
        rows = self._rows(record)
        cached = self._projection_cache.get(record.key)
        if cached and cached[0] == len(rows): return cached[1]
        def slot(row):
            value = row.get("avatarSlot", 0)
            return value if isinstance(value, int) and 0 <= value < 4 else 0
        totals = [sum(slot(row) == i for row in rows.values()) for i in range(4)]
        counts = [0,0,0,0]
        projected = {}
        for row in rows.values():
            index = slot(row); counts[index] += 1
            name = self.controller.characterNames[index] + (f" · {counts[index]}" if totals[index] > 1 else "")
            projected[row["id"]] = dict(row, avatar=AVATARS[index], name=name, active=row.get("status") in ACTIVE)
        self._projection_cache[record.key] = (len(rows), projected)
        return projected

    @Property("QVariantList", notify=changed)
    def agents(self):
        return list(self._projection(self.controller._view).values())

    @Property("QVariantList", notify=changed)
    def activeAgents(self):
        return [row for row in self.agents if row["active"]]

    @Property(int, notify=changed)
    def activeCount(self):
        return len(self.activeAgents)

    @Property(QObject, constant=True)
    def messageModel(self):
        return self.model

    @Property(int, notify=contextChanged)
    def messageCount(self):
        return self.model.rowCount()

    @Slot(int, result="QVariantMap")
    def displayMessage(self, row):
        return self.model.message(row, synchronous=True)

    @Slot(str)
    def copyChatSelection(self, raw):
        import json
        from .chat_copy import selected_text
        selection = json.loads(raw)
        snapshot, overlay = self.model.snapshot, copy.deepcopy(self.model.rows)
        script = (self.controller.root / "app/qml/markdown.js").read_text(encoding="utf-8")
        self.controller._copy_chat(lambda: selected_text(script, snapshot, overlay, selection["anchor"], selection["cursor"], selection.get("expanded", {})))

    @Property("QVariantMap", notify=changed)
    def selected(self):
        return self._projection(self.owner).get(self.selected_id, {}) if self.owner else {}

    @Property("QVariantMap", notify=contextChanged)
    def context(self):
        key = (self.owner.key, self.selected_id) if self.owner else None
        return {"loading": self.loading, "error": self.error, "truncated": self.truncated,
                "pending": any(item["key"] == key for item in self._pending.values()),
                "draft": self._drafts.get(key, ""),
                "attachments": copy.deepcopy(self._attachments.get(key, []))}

    @Property("QVariantList", notify=queueChanged)
    def queuedMessages(self):
        from .message_attachments import split_attachments
        key = (self.owner.key, self.selected_id) if self.owner else None
        result = []
        for item in self._queues.get(key, []):
            text, attachments = split_attachments(item["text"])
            result.append({**item, "text": text, "attachments": attachments})
        return result

    @Slot(str)
    def copy(self, text):
        self.controller.copy(text)

    def _queue_command(self, action, identifier=None):
        if not self.owner: return False
        if identifier is not None and not any(row["id"] == identifier for row in self.queuedMessages): return False
        return self._command(self.owner, {"action": action, "id": self.selected_id, "queueId": identifier, "requestId": uuid.uuid4().hex})

    @Slot(str)
    def editQueued(self, identifier): self._queue_command("edit-queue", identifier)

    @Slot(str)
    def removeQueued(self, identifier): self._queue_command("delete-queue", identifier)

    @Slot(str)
    def steerQueued(self, identifier): self._queue_command("steer-queued", identifier)

    def merge(self, record, row):
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            return
        rows = self._rows(record)
        old = rows.get(row["id"], {})
        current = {**old, **row}
        if not isinstance(current.get("avatarSlot"), int):
            counts = [sum(r.get("avatarSlot") == i and r.get("status") in ACTIVE for r in rows.values()) for i in range(4)]
            current["avatarSlot"] = counts.index(min(counts)) if current.get("status") in ACTIVE else len(rows) % 4
        rows[row["id"]] = current
        self._projection_cache.pop(record.key, None)
        record.subagents_active = any(r.get("status") in ACTIVE for r in rows.values())
        signature = lambda value: (value.get("status"), value.get("outputFile"), value.get("avatarSlot"))
        if signature(old) != signature(current) and record.id:
            # Persist compact pointers, not partial messages or large results.
            compact = [{k: v for k, v in r.items() if k not in ("result", "error", "activity")} for r in rows.values()]
            self.controller.store.data["sessionMeta"].setdefault(record.id, {})["subagents"] = compact
            self._save.start()
        if record is self.controller._view:
            self.changed.emit()

    def sync(self, record):
        for message in record.messages:
            for tool in message.get("tools", []):
                if tool.get("subagent"):
                    live = record.subagents.get(tool["subagent"]["id"])
                    if not live:
                        self.merge(record, tool["subagent"])

    @Slot()
    def _view_changed(self):
        self.closeView()
        self.sync(self.controller._view)
        self.changed.emit()

    @Slot(str)
    def open(self, agent_id):
        record = self.controller._view
        self.sync(record)
        if agent_id not in self._rows(record):
            self.controller.toast.emit("当前会话中没有这个子代理")
            return
        self.closeView()
        self.owner, self.selected_id = record, agent_id
        self.error, self.loading, self.truncated = "", True, False
        self.changed.emit()
        self.queueChanged.emit()
        self.contextChanged.emit()
        self.requested.emit()
        row = record.subagents[agent_id]
        if record.process:
            if not record.ready and row.get("outputFile"):
                self._load_file(row["outputFile"])
            self._command(record, {"action": "watch", "id": agent_id})
        elif row.get("outputFile"):
            self._load_file(row["outputFile"])
        else:
            if not self._command(record, {"action": "watch", "id": agent_id}):
                self.loading, self.error = False, "暂时无法加载子代理上下文"
                self.contextChanged.emit()

    @Slot()
    def closeView(self):
        if self.owner:
            self._deferred[self.owner.key] = [command for command in self._deferred.get(self.owner.key, []) if command.get("action") != "watch"]
        if self.owner and self.owner.process:
            self.controller._write_pi({"type": "subagent-command", "action": "unwatch"}, self.owner)
        self._generation += 1
        self._stream.stop()
        self.owner, self.selected_id = None, ""
        self.queueChanged.emit()
        self._projection_cache.clear()
        self.messages = []
        self.model.set_snapshot(None)
        self.model.update([])
        self.loading = False
        self.error = ""
        self.changed.emit()
        self.contextChanged.emit()

    def _command(self, record, command):
        switching = record.busy and record.action in ("open", "new", "reload", "fork", "navigate", "subagent-open")
        if record.process and record.ready and not switching:
            self.controller._write_pi({"type": "subagent-command", **command}, record)
            return True
        if record.process:
            self._deferred.setdefault(record.key, []).append(command)
            return True
        if not record.busy:
            return self.controller._command_pi("subagent-open", record, command=command)
        return False

    def process_ready(self, record):
        if not record.ready or record.busy and record.action in ("open", "new", "reload", "fork", "navigate", "subagent-open"):
            return
        for command in self._deferred.pop(record.key, []):
            if command.get("action") == "watch" and (record is not self.owner or command.get("id") != self.selected_id):
                continue
            self.controller._write_pi({"type": "subagent-command", **command}, record)

    @Slot(str)
    def setDraft(self, text):
        if self.owner:
            self._drafts[(self.owner.key, self.selected_id)] = text

    @Slot(str, result=bool)
    def addAttachments(self, raw):
        import json
        if not self.owner or not self.selected_id: return False
        key = (self.owner.key, self.selected_id)
        items = self._attachments.setdefault(key, [])
        accepted = False
        try:
            urls = json.loads(raw)
            if not isinstance(urls, list): return False
            for url in urls:
                if len(items) >= 20:
                    self.controller.toast.emit("一次最多添加 20 个附件"); break
                try:
                    item = self.controller._file_attachment(url, encode_image=False)
                    if item is None: continue
                    if not any(existing["path"] == item["path"] for existing in items): items.append(item)
                    accepted = True
                except (ValueError, OSError):
                    self.controller.toast.emit("无法读取附件")
        except (ValueError, TypeError):
            self.controller.toast.emit("无法读取附件")
        self.contextChanged.emit()
        return accepted

    @Slot(str)
    def removeAttachment(self, identifier):
        if not self.owner: return
        key = (self.owner.key, self.selected_id)
        self._attachments[key] = [item for item in self._attachments.get(key, []) if item["id"] != identifier]
        self.contextChanged.emit()

    @Slot(str, result=bool)
    def send(self, text):
        return self._send(text)

    @Slot(str, result=bool)
    def steer(self, text):
        if not text.strip() and not self.context["attachments"]:
            return bool(self.queuedMessages) and self._queue_command("promote-queue")
        return self._send(text, interrupt=True)

    def _send(self, text, interrupt=False):
        import time
        from .message_attachments import attachment_prompt
        text = text.strip()
        key = (self.owner.key, self.selected_id) if self.owner else None
        attachments = self._attachments.get(key, [])
        if not self.owner or self.loading or (not text and not attachments) or self.context["pending"]:
            return False
        prompt = attachment_prompt(text, attachments)
        if len(prompt) > 65536:
            self.controller.toast.emit("请输入消息，长度不得超过 64K 字符"); return False
        row = self.owner.subagents.get(self.selected_id, {})
        if row.get("status") == "queued":
            self.controller.toast.emit("子代理正在排队，请在开始运行后发送指引")
            return False
        request = uuid.uuid4().hex
        self._pending[request] = {"key": key, "text": text, "attachmentIds": {item["id"] for item in attachments}, "time": time.monotonic()}
        self._drafts[(self.owner.key, self.selected_id)] = text
        if not self._command(self.owner, {"action": "send", "id": self.selected_id, "text": prompt,
                "mode": "interrupt" if interrupt else "followUp", "messageId": request, "requestId": request}):
            self._pending.pop(request)
            self.controller.toast.emit("Pi 尚未就绪，请稍后重试")
            return False
        self.contextChanged.emit()
        return True

    @Slot()
    def stop(self):
        if self.owner:
            self._command(self.owner, {"action": "stop", "id": self.selected_id})

    def handle(self, record, event):
        kind = event.get("type")
        if kind == "subagents":
            for row in event.get("agents", []):
                self.merge(record, row)
        elif kind == "subagent_queue":
            self._queues[(record.key, event["id"])] = copy.deepcopy(event.get("items", []))
            self.queueChanged.emit()
        elif kind in ("subagent_queue_edited", "subagent_queue_returned"):
            items = [event["item"]] if kind == "subagent_queue_edited" else event.get("items", [])
            self._restore_queue(record, event["id"], items)
        elif kind == "subagent_command":
            pending = self._pending.pop(event.get("requestId"), None)
            if not event.get("ok"):
                self.controller.toast.emit(event.get("message") or "子代理操作失败")
                if event.get("action") == "watch" and record is self.owner:
                    self.loading, self.error = False, event.get("message") or "无法加载子代理"
            elif pending and not pending.get("returned"):
                if self._drafts.get(pending["key"], "") == pending["text"]:
                    self._drafts[pending["key"]] = ""
                self._attachments[pending["key"]] = [item for item in self._attachments.get(pending["key"], []) if item["id"] not in pending["attachmentIds"]]
                if self.owner and pending["key"] == (self.owner.key, self.selected_id):
                    self.messageSent.emit(self.selected_id)
            self.contextChanged.emit()
        elif record is self.owner and event.get("id") == self.selected_id:
            if kind == "subagent_context":
                self._generation += 1
                self.error = ""
                if event.get("file"):
                    self._load_file(event["file"])
                else:
                    self.model.set_snapshot(None)
                    self.messages = copy.deepcopy(event.get("messages", []))
                    self.truncated, self.loading = bool(event.get("truncated")), False
                    self._publish()
            elif kind == "subagent_event":
                self._event(event["event"])

    def _restore_queue(self, record, identifier, items):
        from .message_attachments import split_attachments
        key = (record.key, identifier)
        texts = []
        attachments = self._attachments.setdefault(key, [])
        for item in items:
            text, files = split_attachments(item["text"])
            pending = self._pending.get(item.get("id"))
            already_in_editor = pending and pending["key"] == key and self._drafts.get(key, "") == pending["text"]
            if pending and pending["key"] == key: pending["returned"] = True
            if text and not already_in_editor: texts.append(text)
            for file in files:
                if not any(existing["path"] == file["path"] for existing in attachments):
                    attachments.append({**file, "id": uuid.uuid4().hex})
        self._drafts[key] = "\n\n".join(part for part in [self._drafts.get(key, ""), *texts] if part)
        self.contextChanged.emit()
        if self.owner is record and self.selected_id == identifier: self.draftRestored.emit(identifier)

    def _event(self, event):
        kind = event["type"]
        self.loading = False
        if kind == "user_start":
            message = {"role": "user", "text": event.get("text", "")[-131072:], "timestamp": event.get("timestamp")}
            if self.messages and self.messages[-1].get("role") == "user" and event.get("timestamp") is not None and self.messages[-1].get("timestamp") == event["timestamp"]:
                self.messages[-1].update(message)
            else:
                self.messages.append(message)
        elif kind == "assistant_start":
            if not self.messages or self.messages[-1].get("role") != "assistant" or self.messages[-1].get("text") or self.messages[-1].get("tools") or self.messages[-1].get("thinking"):
                self.messages.append({"role": "assistant", "text": "", "timestamp": event.get("timestamp")})
        elif kind in ("delta", "thinking_delta", "message", "tool"):
            if not self.messages or self.messages[-1].get("role") != "assistant":
                self.messages.append({"role": "assistant", "text": ""})
            message = self.messages[-1]
            if kind in ("delta", "thinking_delta"):
                key = "text" if kind == "delta" else "thinking"
                value = message.get(key, "") + event.get("text", "")
                if len(value) > 131072:
                    self.truncated = True
                message[key] = value[-131072:]
            elif kind == "message":
                message.update({key: event[key] for key in ("text", "thinking", "error", "stopReason", "timestamp") if key in event})
                for key in ("text", "thinking"):
                    if len(message.get(key, "")) > 131072:
                        message[key] = message[key][-131072:]
                        self.truncated = True
            else:
                tools = message.setdefault("tools", [])
                tool = next((tool for tool in tools if tool["id"] == event["id"]), None)
                if tool is None:
                    tool = tool_view(event["id"], event["name"], event.get("args", {}), self.owner.workspace)
                    tools.append(tool)
                tool["state"] = event["state"]
                if event.get("result") is not None:
                    tool["result"] = event["result"]
                if len(tools) > 32:
                    del tools[:-32]
                    self.truncated = True
        if len(self.messages) > 200:
            self.messages = self.messages[-200:]
            self.truncated = True
        if not self._stream.isActive():
            self._stream.start()

    def _publish(self):
        # A single very long live turn must not grow the native QML document
        # without bound. Full history is still readable from its native file.
        weight = 0
        for offset, message in enumerate(reversed(self.messages)):
            weight += len(message.get("text", "")) + len(message.get("thinking", ""))
            weight += sum(len(tool.get("result", "")) + 16384 for tool in message.get("tools", []))
            if weight > 1024 * 1024 and offset:
                self.messages = self.messages[-offset:]
                self.truncated = True
                break
        self.model.update(self.messages)
        self.contextChanged.emit()

    def _load_file(self, file):
        self._generation += 1
        generation = self._generation
        self.loading = True
        self.contextChanged.emit()
        def read():
            result = {"generation": generation}
            try:
                if not Path(file).is_file():
                    raise OSError("子代理的会话文件已不存在")
                if self.controller.transcripts.large(file):
                    result["snapshot"] = self.controller.transcripts.open(file, cancelled=lambda: generation != self._generation or self._closed)
                else:
                    result["messages"], _ = preview(file)
            except Exception as error:
                result["error"] = str(error)
            if not self._closed:
                self.loaded.emit(result)
        threading.Thread(target=read, name="subagent-preview", daemon=True).start()

    @Slot(object)
    def _loaded(self, result):
        if self._closed or result["generation"] != self._generation:
            return
        self.loading = False
        self.error = result.get("error", "")
        self.model.set_snapshot(result.get("snapshot"))
        self.messages = result.get("messages", [])
        self._publish()

    def _expire(self):
        import time
        expired = [key for key, item in self._pending.items() if time.monotonic() - item["time"] > 30]
        for key in expired:
            self._pending.pop(key)
        if expired:
            self.controller.toast.emit("子代理暂未确认收到消息，输入内容已保留")
            self.contextChanged.emit()

    def close(self):
        self._closed = True
        self.closeView()
        self._deadline.stop()
        if self._save.isActive():
            self._save.stop()
            self.controller.store.save()
        self.model.close()
