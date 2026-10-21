"""Route native Pi events to their owning session, independently of the view."""
import copy
import uuid
from pathlib import Path

from .pi_runtime import node_executable
from .transcripts import tool_view
from .message_attachments import attachment_prompt, split_attachments


class PiControllerMixin:
    def _write_pi(self, payload, record=None):
        self._pool.write(record or self._view, payload)

    def _restart_pi(self):
        for record in self._pool.records.values():
            if not record.busy:
                record.context_usage = {}
        self._pool.invalidate()
        self.contextUsageChanged.emit()

    def _merge_native_sessions(self, native):
        existing = {session["id"]: session for session in self._sessions}
        for session in native:
            if session["id"] in existing:
                existing[session["id"]].update(session)
            else:
                row = dict(session)
                self._sessions.append(row)
                existing[session["id"]] = row
            if session.get("workspace"):
                self._ensure_project(session["workspace"])

    def _record_info(self, record, info):
        old_id = record.id
        record.id = info["id"]
        record.file = info.get("file") or record.file
        record.title = info.get("title") or record.title
        record.workspace = info.get("workspace") or record.workspace
        if old_id and old_id != record.id:
            self._sessions = [session for session in self._sessions if session["id"] != old_id]
            metadata = self.store.data["sessionMeta"].pop(old_id, {})
            self.store.data["sessionMeta"].setdefault(record.id, {}).update(metadata)
        if record.file or record.action == "prompt":
            self._index_record(record)

    def _index_record(self, record):
        row = next((s for s in self._sessions if s["id"] == record.id), None)
        values = {"id": record.id, "file": record.file, "workspace": record.workspace, "title": record.title,
            "model": record.model, "provider": record.provider}
        if row is None:
            self._sessions.insert(0, values)
        else:
            row.update(values)

    def _command_pi(self, action, record=None, **values):
        record = record or self._view
        if record.busy or self._kernel_busy:
            return False
        if record.stale or (record.process and not record.ready):
            self._pool.retire(record)
        record.action, record.failed, record.cancelled = action, False, False
        record.phase = "loading" if not record.process else "running" if action in ("prompt", "compact") else "working"
        record.tool_status = "正在加载 Pi" if record.phase == "loading" else "正在生成" if record.phase == "running" else "正在处理"
        payload = {"type": action, "model": record.model or self.store.data["selectedModel"], **values}
        try:
            if record.process:
                self._pool.write(record, payload)
                self._pool.touch(record)
            else:
                bridge = self._release / "bridge.mjs"
                if not bridge.is_file():
                    raise RuntimeError("Pi 内核未安装")
                default_cwd = self.store.directory / "workspace"
                default_cwd.mkdir(exist_ok=True)
                agent = self.store.data["agent"]
                payload.update(gateway=f"http://127.0.0.1:{self.private_server.port}/", token=self.private_token,
                    workspace=record.workspace, defaultCwd=str(default_cwd),
                    agentDir=agent.get("agentDir") or str(Path.home() / ".pi/agent"),
                    sessionDir=str(self.store.directory / "pi/sessions"), sessionFile=record.file,
                    legacyHistory=record.history, models=self.gateway.models(), agent=agent,
                    mcpEnv=self._mcp_environment(record.workspace))
                self._pool.start(record, node_executable(), bridge, payload)
        except (RuntimeError, OSError) as error:
            record.phase, record.failed = "idle", True
            self.toast.emit(str(error))
            if record.messages and not record.messages[-1]["text"]:
                record.messages[-1].update(text=str(error), error=True)
            self.chatChanged.emit()
            return False
        self.chatChanged.emit()
        return True

    def _send(self, text, steering=False):
        record = self._view
        text = text.strip()
        if (not text and not record.attachments) or (record.busy and record.phase != "running") or self._kernel_busy:
            return False
        images = [{"type": "image", "data": item["data"], "mimeType": item["mime"]} for item in record.attachments if item["kind"] == "image"]
        model = record.model if record.phase == "running" else self.store.data["selectedModel"]
        provider = record.provider if record.phase == "running" else self.store.data["selectedProvider"]
        attachments = record.attachments
        if images and not self.gateway.supports_vision(model, provider):
            self.toast.emit("未启用视觉，降级为普通文件路径")
            images = []
            attachments = [{**item, "kind": "file" if item["kind"] == "image" else item["kind"]} for item in attachments]
        text = attachment_prompt(text, attachments)
        if record.phase == "running":
            self._write_pi({"type": "steer" if steering else "follow-up", "text": text, "images": images}, record)
            record.attachments, record.draft = [], ""
            self.attachmentsChanged.emit()
            self.editorText.emit("")
            return True
        record.model, record.provider = self.store.data["selectedModel"], self.store.data["selectedProvider"]
        if not record.id:
            record.id = "pending-" + record.key
        if not record.messages:
            record.title = " ".join(text.split())[:28]
        record.messages.extend([{"role": "user", "text": text, "error": False}, {"role": "assistant", "text": "", "error": False}])
        record.optimistic_user = True
        self._index_record(record)
        self.store.data["sessionMeta"].setdefault(record.id, {})["unread"] = False
        if self._command_pi("prompt", text=text, images=images):
            record.attachments, record.draft = [], ""
            self.attachmentsChanged.emit()
            self.editorText.emit("")
            self._save_session()
            self.transcriptChanged.emit()
            return True
        return False

    def _restore_queued(self, record, texts, images=None):
        drafts = [record.draft] if record.draft else []
        media = iter(images or [])
        for raw in texts:
            text, attachments = split_attachments(raw)
            if text: drafts.append(text)
            for item in attachments:
                if len(record.attachments) >= 20: break
                if not any(existing["path"] == item["path"] for existing in record.attachments):
                    image = next(media, None) if item["kind"] == "image" else None
                    record.attachments.append({**item, "id": uuid.uuid4().hex,
                        "kind": "image" if image else "file" if item["kind"] == "image" else item["kind"],
                        **({"data": image["data"], "mime": image["mimeType"]} if image else {})})
        record.draft = "\n\n".join(drafts)
        if record is self._view:
            self.attachmentsChanged.emit()
            self.editorText.emit(record.draft)

    def _handle_pi_event(self, record, event):
        if self._closing:
            return
        kind, visible = event.get("type"), record is self._view
        transcript = False
        if kind == "ready":
            record.ready = True
            record.phase = "running" if record.action in ("prompt", "compact") else "working"
            record.tool_status = "正在生成" if record.phase == "running" else "正在处理"
            if event.get("session"):
                self._record_info(record, event["session"])
        elif kind == "session":
            self._record_info(record, event["session"])
        elif kind in ("delta", "thinking_delta"):
            if not record.messages or record.messages[-1]["role"] != "assistant":
                record.messages.append({"role": "assistant", "text": "", "error": False})
            field = "thinking" if kind == "thinking_delta" else "text"
            record.messages[-1][field] = record.messages[-1].get(field, "") + event["text"]
            transcript = True
        elif kind == "user_start":
            text = event["text"]
            if record.optimistic_user:
                record.optimistic_user = False
            else:
                record.messages.extend([{"role": "user", "text": text, "error": False}, {"role": "assistant", "text": "", "error": False}])
                transcript = True
        elif kind == "assistant_start":
            if not record.messages or record.messages[-1]["role"] != "assistant" or record.messages[-1]["text"] or record.messages[-1].get("thinking") or record.messages[-1].get("tools"):
                record.messages.append({"role": "assistant", "text": "", "error": False})
                transcript = True
        elif kind == "queue":
            record.queue = event.get("items", [{"text": text, "mode": "steering"} for text in event.get("steering", [])] + [{"text": text, "mode": "followUp"} for text in event.get("followUp", [])])
        elif kind == "queue_edited":
            self._restore_queued(record, [event["text"]], event.get("images"))
        elif kind == "queue_rejected":
            self._restore_queued(record, [event.get("text", "")])
            if visible:
                self.toast.emit(event["message"])
        elif kind == "queue_returned":
            self._restore_queued(record, [*event.get("steering", []), *event.get("followUp", [])])
        elif kind == "message" and event.get("role") == "assistant":
            if record.messages and record.messages[-1]["role"] == "assistant":
                record.messages[-1].update(text=event.get("text") or event.get("error") or record.messages[-1]["text"], error=bool(event.get("error")))
                if "thinking" in event:
                    record.messages[-1]["thinking"] = event["thinking"]
                transcript = True
        elif kind == "tool":
            record.tool_status = event["name"] + (" · 运行中" if event["state"] == "running" else " · 失败" if event["state"] == "error" else " · 完成")
            tool = next((tool for message in reversed(record.messages) for tool in message.get("tools", []) if tool["id"] == event["id"]), None)
            if tool is None:
                if not record.messages or record.messages[-1]["role"] != "assistant":
                    record.messages.append({"role": "assistant", "text": "", "error": False})
                tool = tool_view(event["id"], event["name"], event.get("args", {}), record.workspace)
                record.messages[-1].setdefault("tools", []).append(tool)
            tool["state"] = event["state"]
            if event.get("media"):
                tool["media"] = event["media"]
            if event.get("result") is not None:
                tool["result"] = event["result"]
            transcript = True
        elif kind == "status":
            record.tool_status = event["text"]
        elif kind == "notice":
            if visible:
                self.toast.emit(event["message"])
        elif kind == "editor":
            record.draft = event["text"]
            if visible:
                self.editorText.emit(record.draft)
        elif kind == "ui_request":
            record.approval = event
            if visible:
                self.approvalChanged.emit()
            else:
                self.toast.emit(record.title + " · 等待你的确认")
        elif kind == "resources":
            record.resources = event["resources"]
            if visible:
                self.changed.emit()
            return
        elif kind == "context_usage":
            record.context_usage = event.get("usage") or {}
            if visible:
                self.contextUsageChanged.emit()
            return
        elif kind == "error":
            record.failed = True
            if record.messages and not record.messages[-1]["text"]:
                record.messages[-1].update(text=event["message"], error=True)
                transcript = True
            if visible:
                self.toast.emit(event["message"])
        elif kind == "state":
            self._record_info(record, event["session"])
            record.messages, record.history, record.tree = event["messages"], [], event["tree"]
            record.resources = event["resources"]
            record.context_usage = event.get("contextUsage") or {}
            if visible:
                self.contextUsageChanged.emit()
            self._merge_native_sessions(event["sessions"])
            # A stale list captured by another process must not overwrite a live view.
            for live in self._pool.records.values():
                if live.id and (live.file or live.messages):
                    self._index_record(live)
            self.store.save()
            self._save_session()
            if visible:
                self.changed.emit()
            transcript = True
        elif kind in ("done", "exit"):
            was_busy = record.busy
            if record.queue:
                self._restore_queued(record, [row["text"] for row in record.queue])
                record.queue = []
            record.phase, record.tool_status, record.approval = "idle", "", {}
            if kind == "exit":
                record.ready = False
                if was_busy:
                    record.failed = True
                    message = event.get("message") or "Pi 内核已退出，原生会话保存在本机"
                    if record.messages and not record.messages[-1]["text"]:
                        record.messages[-1].update(text=message, error=True)
                        transcript = True
                    if visible:
                        self.toast.emit(message)
            if was_busy and record.action == "prompt" and not record.cancelled and record.id:
                self.store.data["sessionMeta"].setdefault(record.id, {})["unread"] = not (visible and self._chat_visible)
                self.store.save()
            if visible:
                self.approvalChanged.emit()
            if record.stale or (kind == "done" and not record.ready):
                self._pool.retire(record)
            self._pool.trim()
        else:
            return
        if visible or kind in ("ready", "session", "state", "done", "exit", "ui_request"):
            self.chatChanged.emit()
        if transcript and visible:
            self.transcriptChanged.emit()

    def _stop(self):
        record = self._view
        if record.phase == "running":
            record.cancelled = True
            self._pool.write(record, {"type": "abort"})
            record.approval = {}
            self.approvalChanged.emit()
