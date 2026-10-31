"""Route native Pi events to their owning session, independently of the view."""
import copy
import re
import time
import uuid
from pathlib import Path

from .pi_runtime import node_executable
from .webview import configuration as webview_configuration
from .transcripts import tool_view, compaction_view, compaction_status
from .message_attachments import attachment_prompt, split_attachments


class PiControllerMixin:
    def _queue_transcript_index(self, record, leaf=None, canonical=False, captured=None):
        if not record.file or self._closing:
            return
        captured = list(record.messages) if captured is None else captured
        record.index_request += 1
        if record.index_running:
            record.index_pending = (leaf, canonical, captured)
            return
        record.index_running = True
        file = record.file
        request = record.index_request
        focus = record.scroll_index if not record.follow_tail else -1
        def build():
            snapshot = self.transcripts.open(file, leaf=leaf, cancelled=lambda: self._closing, focus=focus)
            entries = snapshot.covered_ids(message.get('entryId') for message in captured)
            covered = {id(message) for message in captured if canonical or message.get('entryId') in entries}
            return {'snapshot':snapshot, 'captured':covered, 'file':file, 'request':request}
        self._job('transcript:' + record.key, build)

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
        if record.global_agent:
            record.id=info["id"]; record.file=info.get("file") or record.file
            return
        old_id = record.id
        record.id = info["id"]
        self.store.data["sessionMeta"].setdefault(record.id, {})["reasoningEffort"] = record.reasoning_effort
        self.store.data["sessionMeta"].setdefault(record.id, {})["extensionModes"] = record.extension_modes
        self.store.data["sessionMeta"].setdefault(record.id, {})["skillModes"] = record.skill_modes
        record.file = info.get("file") or record.file
        record.title = info.get("title") or record.title
        record.workspace = info.get("workspace") or record.workspace
        if old_id and old_id != record.id:
            self._sessions = [session for session in self._sessions if session["id"] != old_id]
            metadata = self.store.data["sessionMeta"].pop(old_id, {})
            self.store.data["sessionMeta"].setdefault(record.id, {}).update(metadata)
        if record.file or record.action == "prompt":
            self._index_record(record)
            if record.extension_modes or record.skill_modes: self.store.save()

    def _index_record(self, record):
        if record.global_agent: return
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
        record.pet_activity = 'thinking'
        record.prompt_started = time.monotonic() if action in ('prompt','widget-notify') else None
        record.phase = "loading" if not record.process else "running" if action in ("prompt", "compact", "widget-notify") else "working"
        record.tool_status = "正在加载 Pi" if record.phase == "loading" else "正在压缩上下文" if action == "compact" else "正在生成" if record.phase == "running" else "正在处理"
        payload = {"type": action, "model": record.model or self.store.data["selectedModel"], "reasoningEffort": record.reasoning_effort, **values}
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
                    sessionExtensions={path: mode == "session" for path, mode in record.extension_modes.items()},
                    sessionSkills=record.skill_modes,
                    docsDir=str(self.store.directory / "agent-docs"),
                    legacyHistory=record.history, models=self.gateway.models(), agent=agent,
                    permissionMode=agent.get("toolPermissionMode", "auto"), language=self.language,
                    dataDir=str(self.store.directory),
                    mcpEnv=self._mcp_environment(record.workspace), webview=webview_configuration(), loopReview=True)
                if record.global_agent:
                    service=self._desktop_plugins.global_agents
                    payload.update(globalCoordinator=True, mcpEnv={}, agentDir=str(service.root/"agent"), sessionDir=str(service.root/"sessions"/record.global_agent),
                        agent={**agent,"safeMode":True,"instructions":service.prompt(record)})
                self._pool.start(record, node_executable(), bridge, payload)
        except (RuntimeError, OSError) as error:
            record.phase, record.failed = "idle", True
            record.prompt_started = None
            self.toast.emit(str(error))
            if record.messages and not record.messages[-1]["text"] and record.messages[-1].get("customType") != "umeko-compaction":
                record.messages[-1].update(text=str(error), error=True)
            self.chatChanged.emit()
            return False
        self.chatChanged.emit()
        self.piCommandStarted.emit(record, action)
        return True

    def _send(self, text, steering=False):
        record = self._view
        text = text.strip()
        self._last_send_error = ""
        if self._kernel_busy:
            self._last_send_error = "Pi 内核检查或更新正在进行；完成后即可再次发送消息。"
            self.toast.emit(self._last_send_error)
            self.changed.emit()
            return False
        if (not text and not record.attachments) or (record.busy and record.phase != "running"):
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
        if not record.messages and not record.transcript:
            record.title = " ".join(text.split())[:28]
        record.messages.extend([{"role": "user", "text": text, "error": False}, {"role": "assistant", "text": "", "error": False}])
        record.body_dirty = True
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

    def _request_compaction(self):
        record = self._view
        if self._kernel_busy:
            self.toast.emit("请等待 Pi 内核操作结束 / Wait for the Pi runtime operation to finish")
            return False
        if not record.id:
            self.toast.emit("当前会话没有可压缩内容 / This conversation has no context to compact")
            return False
        if record.busy:
            return False
        if not self._command_pi("compact", record=record):
            return False
        return True

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

    def _publish_stream(self):
        if not self._closing:
            self._stream_projection = True
            try:
                self.chatChanged.emit()
            finally:
                self._stream_projection = False
            self.transcriptChanged.emit()

    def _handle_pi_event(self, record, event):
        if self._closing:
            return
        kind, visible = event.get("type"), record is self._view
        if kind=='widget_delivery':return  # WidgetChannel observes the same pool event.
        if kind in ("subagents", "subagent_context", "subagent_event", "subagent_command", "subagent_queue", "subagent_queue_edited", "subagent_queue_returned"):
            self._subagents.handle(record, event)
            return
        if kind == 'umeko_request':
            result = self._umeko_control.execute({'operation': event.get('operation'), 'arguments': event.get('arguments', {})}, record)
            self._write_pi({'type': 'umeko_response', 'id': event.get('id'), 'result': result}, record)
            return
        transcript = False
        dirty = max(0, len(record.messages) - 2)
        if kind == 'native_entry':
            record.search_leaf = event['entryId']
            for message in reversed(record.messages):
                if message.get('role') == event.get('role') and message.get('timestamp') == event.get('timestamp'):
                    message['entryId'] = event['entryId']
                    break
            return
        elif kind == 'history_checkpoint':
            record.search_leaf = event.get('leafId', '')
            if record.file and (len(record.messages) > 256 or record.tail_characters > 1024 * 1024):
                self._queue_transcript_index(record, event.get('leafId'))
            return
        elif kind == "ready":
            record.ready = True
            self._subagents.process_ready(record)
            record.phase = "running" if record.action in ("prompt", "compact", "widget-notify") else "working"
            record.tool_status = "正在压缩上下文" if record.action == "compact" else "正在生成" if record.phase == "running" else "正在处理"
            if event.get("session"):
                self._record_info(record, event["session"])
        elif kind == "session":
            self._record_info(record, event["session"])
        elif kind in ("delta", "thinking_delta"):
            record.pet_activity = 'thinking' if kind == 'thinking_delta' else 'working'
            if not record.messages or (record.messages[-1]["role"] != "assistant" or record.messages[-1].get("customType") == "umeko-compaction"):
                record.messages.append({"role": "assistant", "text": "", "error": False})
            field = "thinking" if kind == "thinking_delta" else "text"
            record.messages[-1][field] = record.messages[-1].get(field, "") + event["text"]
            record.tail_characters += len(event['text'])
            transcript = True
        elif kind == "user_start":
            text = event["text"]
            if record.optimistic_user:
                record.optimistic_user = False
            else:
                record.messages.extend([{"role": "user", "text": text, "error": False}, {"role": "assistant", "text": "", "error": False}])
                transcript = True
            if event.get("timestamp"):
                for message in reversed(record.messages):
                    if message["role"] == "user":
                        message["timestamp"] = event["timestamp"]
                        transcript = True
                        break
        elif kind == "assistant_start":
            if event.get("retry") and record.messages and (record.messages[-1]["role"] == "assistant" and record.messages[-1].get("customType") != "umeko-compaction") and not record.messages[-1].get("tools"):
                record.messages[-1] = {"role": "assistant", "text": "", "error": False}
                transcript = True
            if not record.messages or (record.messages[-1]["role"] != "assistant" or record.messages[-1].get("customType") == "umeko-compaction") or record.messages[-1]["text"] or record.messages[-1].get("thinking") or record.messages[-1].get("tools"):
                record.messages.append({"role": "assistant", "text": "", "error": False})
                transcript = True
            if record.messages and event.get("timestamp"):
                record.messages[-1]["timestamp"] = event["timestamp"]
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
        elif kind == "compaction_event":
            row = compaction_view({"type": "custom", "customType": "umeko-compaction",
                "data": event, "id": event.get("entryId"), "timestamp": event.get("timestamp")})
            if row:
                found = next((i for i, message in enumerate(record.messages)
                    if message.get("compaction", {}).get("eventId") == event.get("eventId")), None)
                if found is None:
                    record.messages.append(row)
                else:
                    record.messages[found]["compaction"] = row["compaction"]
                    dirty = min(dirty, found)
                record.compaction_running = event.get("state") == "running"
                record.compaction_event_id = event.get("eventId", "") if record.compaction_running else ""
                record.tool_status = "正在压缩上下文" if record.compaction_running else ""
                transcript = True
        elif kind == "message" and event.get("role") == "assistant":
            if event.get('error') or event.get('stopReason') == 'error': record.failed = True
            if record.messages and (record.messages[-1]["role"] == "assistant" and record.messages[-1].get("customType") != "umeko-compaction"):
                record.messages[-1].update(text=event.get("text") or event.get("error") or record.messages[-1]["text"], error=bool(event.get("error")), stopReason=event.get("stopReason", ""))
                if event.get("timestamp"): record.messages[-1]["timestamp"] = event["timestamp"]
                if "thinking" in event:
                    record.messages[-1]["thinking"] = event["thinking"]
                transcript = True
        elif kind == "tool":
            record.pet_activity = 'working'
            if isinstance(event.get("subagent"), dict):
                self._subagents.merge(record, event["subagent"])
                previous = next((tool for message in record.messages for tool in message.get("tools", []) if tool["id"] == event["id"]), None)
                # Live progress belongs to the independent side pane. Keep the
                # main transcript card stable until its state changes.
                if previous and previous.get("state") == event["state"]:
                    return
            record.tool_status = event["name"] + (" · 运行中" if event["state"] == "running" else " · 失败" if event["state"] == "error" else " · 完成")
            found = next(((i, tool) for i in range(len(record.messages) - 1, -1, -1) for tool in record.messages[i].get("tools", []) if tool["id"] == event["id"]), None)
            tool = found[1] if found else None
            if found:
                dirty = found[0]
            if tool is None:
                if not record.messages or (record.messages[-1]["role"] != "assistant" or record.messages[-1].get("customType") == "umeko-compaction"):
                    record.messages.append({"role": "assistant", "text": "", "error": False})
                tool = tool_view(event["id"], event["name"], event.get("args", {}), record.workspace)
                record.messages[-1].setdefault("tools", []).append(tool)
            if isinstance(event.get("subagent"), dict):
                tool["subagent"] = dict(event["subagent"])
                if isinstance(event.get("args"), dict):
                    tool["arguments"] = dict(event["args"])
            tool["state"] = event["state"]
            if event.get("media"):
                tool["media"] = event["media"]
                if visible and event.get('name')=='submit_to_chatbox' and event.get('state')=='done':
                    for item in event['media']:
                        if self.webviewAvailable and item.get('kind')=='web' and item.get('presentation')=='webview':
                            url=self.normalizeWebUrl(item.get('url',''))
                            if url: self.webRequested.emit(url,item.get('title',''))
                        from .document_preview import document_kind
                        path = item.get('path', '')
                        document = document_kind(path, item.get('kind', ''))
                        if document and Path(path).is_absolute(): self.documentRequested.emit(path, item.get('title', ''), document)
            if event.get("result") is not None:
                tool["result"] = event["result"]
            transcript = True
        elif kind == "network_retry":
            record.network_retry = event if event.get("active") else {}
            if visible:
                self.retryChanged.emit()
            return
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
            message = event["message"]
            if record.action == "compact":
                marker = re.search(r'\[Umeko:[a-f0-9-]{36}\]', message)
                if marker:
                    message = "压缩失败：供应商请求失败，请查看请求详情 / Compaction failed: provider request failed " + marker[0]
                record.tool_status = ""
            elif record.messages and not record.messages[-1]["text"] and record.messages[-1].get("customType") != "umeko-compaction":
                record.messages[-1].update(text=message, error=True)
                transcript = True
            if visible:
                self.toast.emit(message)
        elif kind == "state":
            record.search_leaf = event.get('leafId', '')
            self._record_info(record, event["session"])
            if event.get('indexedHistory'):
                # Keep the already visible live tail while its durable index is
                # prepared. The complete history never crosses into the UI.
                self._queue_transcript_index(record, event['indexedHistory'].get('leafId'), canonical=True)
            else:
                active = {record.compaction_event_id} if record.process and record.compaction_running else set()
                record.messages = [compaction_status(message, active) for message in event["messages"]]
                record.history, record.tree = [], event["tree"]
                record.transcript, record.loaded = None, True
            record.resources = event["resources"]
            self._subagents.sync(record)
            record.context_usage = event.get("contextUsage") or {}
            if visible:
                self.contextUsageChanged.emit()
            if not record.global_agent: self._merge_native_sessions(event["sessions"])
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
            # Pi alone writes JSONL. Resolve an unfinished live transition here;
            # cold readers derive the same failure from its missing terminal entry.
            for index, row in enumerate(record.messages):
                resolved = compaction_status(row)
                if resolved is not row:
                    record.messages[index] = resolved
                    dirty = min(dirty, index)
                    transcript = True
            if record.compaction_running:
                record.failed = True
            record.compaction_running = False
            record.compaction_event_id = ""
            record.network_retry = {}
            if visible:
                self.retryChanged.emit()
            was_busy = record.busy
            long_running = record.prompt_started is not None and time.monotonic() - record.prompt_started > 180
            record.prompt_started = None
            if record.queue:
                self._restore_queued(record, [row["text"] for row in record.queue])
                record.queue = []
            record.phase, record.tool_status, record.approval = "idle", "", {}
            if kind == "done":
                self._subagents.process_ready(record)
            if kind == "exit":
                for child in list(record.subagents.values()):
                    if child.get("status") in ("queued", "running"):
                        self._subagents.merge(record, {**child, "status": "stopped"})
                record.ready = False
                if was_busy:
                    record.failed = True
                    message = event.get("message") or "Pi 内核已退出，原生会话保存在本机"
                    if record.messages and not record.messages[-1]["text"] and record.messages[-1].get("customType") != "umeko-compaction":
                        record.messages[-1].update(text=message, error=True)
                        transcript = True
                    if visible:
                        self.toast.emit(message)
            if was_busy and not record.global_agent and record.action == "prompt" and not record.cancelled and record.id:
                self.store.data["sessionMeta"].setdefault(record.id, {})["unread"] = not (visible and self._chat_visible)
                self.store.save()
                self.taskFinished.emit(record.id, record.title, kind == 'done' and not record.failed, long_running)
            if visible:
                self.approvalChanged.emit()
            if record.stale or (kind == "done" and not record.ready):
                self._pool.retire(record)
            self._pool.trim()
        else:
            return
        if transcript:
            record.body_dirty = True
            record.projection_dirty_from = min(dirty, record.projection_dirty_from) if record.projection_dirty_from is not None else dirty
        if visible and kind in ("delta", "thinking_delta"):
            if not self._streaming_timer.isActive(): self._streaming_timer.start()
            return
        if visible:
            self._streaming_timer.stop()
        if visible or kind in ("ready", "session", "state", "done", "exit", "ui_request"):
            self.chatChanged.emit()
        if transcript and visible:
            self.transcriptChanged.emit()

    def _stop(self):
        record = self._view
        if record.phase == "running":
            record.cancelled = True
            record.network_retry = {}
            self.retryChanged.emit()
            self._pool.write(record, {"type": "abort"})
            record.approval = {}
            self.approvalChanged.emit()
