from __future__ import annotations

import copy
import base64
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import urllib.request
import uuid
from pathlib import Path
from dataclasses import replace

from PySide6.QtCore import QObject, Property, QProcess, QProcessEnvironment, QTimer, QUrl, Signal, Slot, QBuffer, QIODevice, QMimeData
from PySide6.QtGui import QGuiApplication, QDesktopServices, QFont, QFontDatabase, QImageReader, QWindow

from .gateway import Gateway, LocalServer, validate_base_url
from .integration import load_adapter, UnconfiguredAdapter
from .pi_runtime import PACKAGE, RELEASE_NAME, CREATE_NO_WINDOW, installed_version, node_executable, npm_command, project_runtime, verify_runtime
from .npm_config import npm_environment
from .storage import Store
from .pi_sessions import PiSessionPool, SessionState, clean_extension_modes, clean_blocked_tools
from .controller_runtime import PiControllerMixin
from .transcripts import preview
from .chat_model import ChatModel
from .transcript_index import TranscriptRepository
from .model_context import context_suggestion
from .provider_models import fetch_model_windows
from .model_capabilities import normalize_model, vision_suggestion
from .provider_plugins import ProviderPlugins
from .api_keys import KeyCatalog, generate_key, key_summary, lan_addresses, make_key
from .pi_management import PiManagement
from .message_attachments import split_attachments
from .app_about import AppAbout
from .themes import BASES, LIMIT as THEME_LIMIT, theme_library, read_theme
from .session_preview import SessionPreview
from .document_preview import DocumentPreview
from .preferences import PreferencesMixin
from .common_providers import CommonProvidersMixin
from .chatbox import media_view
from .subagents import Subagents
from .characters import CharactersMixin


GREETINGS = (
    "来啦？今天想先做点什么？",
    "先把今天的难题解决掉，再去吃点好吃的吧。",
    "我已经准备好了，就等你开口啦。",
    "零食先放一边，陪你把这件事做完。",
    "有点棘手？没关系，我们慢慢拆开看。",
    "今天的计划是什么？我来搭把手。",
    "又见面啦，把想做的事告诉我吧。",
    "先从一小步开始，做完再奖励自己。",
    "这次想写点什么？我已经好奇起来了。",
    "忙了一天了吧？这道难题我们一起看。",
    "工作可以认真，休息和好吃的也不能少。",
    "好啦，开工吧。今天也请多关照。",
)


class Controller(CharactersMixin, CommonProvidersMixin, PreferencesMixin, PiControllerMixin, QObject):
    changed = Signal()
    appearanceChanged = Signal()

    @Property('QVariantList', notify=changed)
    def characterPacks(self):
        return self._characterPacks()

    @Property('QVariantList', notify=changed)
    def subagentCharacterPacks(self):
        return self._characterPacks(True)

    @Property('QVariantMap', notify=changed)
    def characterStyle(self):
        return self._characterStyle()

    @Property('QStringList', notify=changed)
    def characterNames(self):
        return self._characterNames()

    @Property(str, notify=appearanceChanged)
    def language(self):
        return self.store.data['ui']['language']

    @Property(float, notify=appearanceChanged)
    def fontScale(self):
        return self.store.data['ui']['fontScale']

    @Property(str, notify=appearanceChanged)
    def lineSpacing(self):
        return self.store.data['ui']['lineSpacing']

    @Property(bool, constant=True)
    def webviewAvailable(self):
        from .webview import configuration
        return configuration()['available']

    @Slot(str, result=str)
    def normalizeWebUrl(self, raw):
        raw=raw.strip()
        if '://' not in raw: raw='https://'+raw
        url=QUrl(raw,QUrl.StrictMode)
        return url.toString(QUrl.FullyEncoded) if url.isValid() and url.scheme() in ('http','https') and url.host() and not url.userInfo() else ''

    @Property(str, constant=True)
    def userDataDirectory(self):
        return str(self.store.directory)
    chatChanged = Signal()
    messageCountChanged = Signal()
    transcriptChanged = Signal()
    viewChanged = Signal()
    sidebarChanged = Signal()
    layoutChanged = Signal()
    toast = Signal(str)
    webRequested = Signal(str, str)
    documentRequested = Signal(str, str, str)
    taskFinished = Signal(str, str, bool, bool)
    jobDone = Signal(str, object)
    jobStarted = Signal(str)
    piCommandStarted = Signal(object, str)
    approvalRequested = Signal(object)
    approvalChanged = Signal()
    attachmentsChanged = Signal()
    contextUsageChanged = Signal()
    reasoningChanged = Signal()
    retryChanged = Signal()

    @Property("QVariantMap", notify=retryChanged)
    def networkRetry(self):
        return self._view.network_retry
    proxyKeysChanged = Signal()
    editorText = Signal(str)

    def __init__(self, root: Path, parent=None):
        super().__init__(parent)
        self.root = root
        self._app_about = AppAbout(self)
        self.store = Store()
        self._init_characters()
        self.transcripts = TranscriptRepository(self.store.directory / 'cache/chat-index')
        self.store.data["themes"] = theme_library(self.store.data.get("themes"))
        if self.store.data["theme"] not in BASES and not any("custom:" + row["id"] == self.store.data["theme"] for row in self.store.data["themes"]):
            self.store.data["theme"] = "dark" if self.store.data["dark"] else "light"
        self._proxy_keys = KeyCatalog(self.store.data["server"]["keys"])
        self._created_proxy_key = {}
        self._proxy_usage_timer = QTimer(self)
        self._proxy_usage_timer.setInterval(2000)
        self._proxy_usage_timer.timeout.connect(self._sync_proxy_usage)
        self._proxy_usage_timer.start()
        self._appearance_save = QTimer(self)
        self._appearance_save.setSingleShot(True)
        self._appearance_save.setInterval(250)
        self._appearance_save.timeout.connect(self.store.save)
        self.adapter = load_adapter(self.store.directory)
        self._provider_plugins = ProviderPlugins(self)
        self.gateway = Gateway(self.store, self.adapter, self._provider_plugins)
        self.private_token = secrets.token_urlsafe(40)
        self.private_server = LocalServer(self.gateway, 0, self.private_token, private=True)
        self.public_server = None
        self._sessions = self.store.load_sessions()
        self._welcome_greetings, self._welcome_portraits = [], []
        self._pool = PiSessionPool(self)
        self._view = self._new_view()
        self._pool.touch(self._view, current=True)
        self._pool.event.connect(self._handle_pi_event)
        self._chat_model = ChatModel(self)
        self._streaming_timer = QTimer(self)
        self._streaming_timer.setSingleShot(True)
        self._streaming_timer.setInterval(24)
        self._streaming_timer.timeout.connect(self._publish_stream)
        self._last_sidebar_rows = None
        self._stream_projection = False
        self.chatChanged.connect(self._update_chat_model)
        self.chatChanged.connect(self._refresh_sidebar)
        self._project_drafts = {self._view.workspace: self._view}
        self._chat_visible = True
        self._management_jobs = set()
        self._mcp_jobs = {}
        self._model_refresh_jobs = {}
        self._closing = False
        self._copy_request = 0
        self._session_preview = SessionPreview(self)
        from .conversation_search import ConversationSearch
        self._chat_search = ConversationSearch(self)
        self._document_preview = DocumentPreview(self, store=self.store)
        self._subagents = Subagents(self)
        self._view.id = ""
        self._view.messages = []
        self._view.history = []
        self._view.busy = False
        self._view.process = None
        self._view.buffer = b""
        self._view.tool_status = ""
        self._view.resources = {"tools": [], "skills": [], "extensions": [], "diagnostics": []}
        self._view.file = ""
        self._view.tree = []
        self._view.attachments = []
        self._collapsed_projects = set()
        self._show_archived = False
        for session in self._sessions:
            if session.get("workspace"):
                self._ensure_project(session["workspace"])
        self._kernel_busy = False
        self._last_send_error = ""
        self._latest = ""
        self._kernel_status = "就绪"
        self._view.approval = {}
        self._release = root / "runtime/releases" / RELEASE_NAME
        active = self.store.directory / "kernels/active.json"
        if active.exists():
            try:
                saved = json.loads(active.read_text(encoding="utf-8"))
                version = saved["version"]
                name = saved.get("directory", "coding-" + version)
                kernels = self.store.directory / "kernels"
                candidate = kernels / name
                if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[\w.-]+)?", version) or not re.fullmatch(r"(?:coding|factory)-[\w.-]+", name) or candidate.resolve().parent != kernels.resolve():
                    raise ValueError("内核路径无效")
                verify_runtime(candidate, self.root / "runtime/bridge.mjs")
                self._release = candidate
            except (OSError, RuntimeError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
                self._kernel_status = "已使用内置内核，可在此恢复配置"
        self.jobDone.connect(self._on_job_done)
        self._pi_management = PiManagement(self)
        from .umeko_control import UmekoControl
        self._umeko_control = UmekoControl(self)
        from .desktop_plugins import DesktopPlugins
        self._desktop_plugins = DesktopPlugins(self)

    @Property(QObject, constant=True)
    def piManagement(self):
        return self._pi_management

    @Property(QObject, constant=True)
    def sessionPreview(self):
        return self._session_preview

    @Property(QObject, constant=True)
    def chatSearch(self):
        return self._chat_search

    @Property(QObject, constant=True)
    def documentPreview(self):
        return self._document_preview

    @Property(QObject, constant=True)
    def subagents(self):
        return self._subagents

    @Property(QObject, constant=True)
    def providerPlugins(self):
        return self._provider_plugins

    @Property(QObject, constant=True)
    def desktopPlugins(self):
        return self._desktop_plugins

    def _new_view(self, workspace=None):
        if not self._welcome_greetings:
            self._welcome_greetings = list(GREETINGS)
            secrets.SystemRandom().shuffle(self._welcome_greetings)
        if not self._welcome_portraits:
            self._welcome_portraits = list(range(12))
            secrets.SystemRandom().shuffle(self._welcome_portraits)
        return SessionState(workspace=self.store.data["workspace"] if workspace is None else workspace,
            reasoning_effort=self.store.data["ui"].get("reasoningEffort", "off") if self.store.data["ui"].get("reasoningEffort") in ("low", "high", "max") else "off",
            model=self.store.data["selectedModel"], provider=self.store.data["selectedProvider"], greeting=self._welcome_greetings.pop(), portrait=self._welcome_portraits.pop())

    def _activate(self, record):
        self._streaming_timer.stop()
        self._view = record
        self.viewChanged.emit()
        self._pool.touch(record, current=True)
        if record.workspace:
            project = self._ensure_project(record.workspace, reopen=True)
            self.store.data.update(workspace=project["path"], activeProject=project["id"])
        else:
            self.store.data.update(workspace="", activeProject="")
        # The index can name a deleted supplier or a retired pre-plugin model.
        # Keep a valid historical selection; otherwise use the current selection.
        available = [(p["id"], m["alias"]) for p in self.store.data["providers"]
                     if p["api"] != "internal" or getattr(self.gateway.adapter, "ready", True)
                     for m in p["models"]]
        historical = (record.provider, record.model)
        current = (self.store.data["selectedProvider"], self.store.data["selectedModel"])
        selected = historical if historical in available else current if current in available else next(iter(available), ("", ""))
        if not record.busy and historical != selected:
            record.provider, record.model = selected
            record.context_usage = {}
        if (record.provider, record.model) in available:
            self.store.data.update(selectedModel=record.model, selectedProvider=record.provider)
        self._mark_read(record)
        self.store.save()
        self.changed.emit()
        self.chatChanged.emit()
        self.attachmentsChanged.emit()
        self.approvalChanged.emit()
        self.editorText.emit(record.draft)
        self.contextUsageChanged.emit()
        self.reasoningChanged.emit()
        self.retryChanged.emit()

    def _refresh_sidebar(self):
        rows = self.projectRows
        if rows != self._last_sidebar_rows:
            self._last_sidebar_rows = rows
            self.sidebarChanged.emit()

    @Property(QObject, constant=True)
    def messageModel(self):
        return self._chat_model

    def _update_chat_model(self):
        count = self._chat_model.rowCount()
        active = frozenset({self._view.compaction_event_id}) if self._view.process and self._view.compaction_running else frozenset()
        if self._view.transcript and self._view.transcript.active_compactions != active:
            self._view.transcript = replace(self._view.transcript, active_compactions=active)
        self._chat_model.set_snapshot(self._view.transcript)
        dirty = self._view.projection_dirty_from
        if dirty is None and self._stream_projection:
            dirty = max(0, len(self._view.messages) - 1)
        self._chat_model.update(self._view.messages, dirty_from=dirty)
        self._view.projection_dirty_from = None
        if count != self._chat_model.rowCount():
            self.messageCountChanged.emit()

    @Property(int, notify=messageCountChanged)
    def messageCount(self):
        return self._chat_model.rowCount()

    @Property(float, notify=viewChanged)
    def scrollPosition(self):
        return self._view.scroll_y

    @Property(int, notify=viewChanged)
    def scrollAnchor(self):
        return self._view.scroll_index

    @Property(bool, notify=viewChanged)
    def followTail(self):
        return self._view.follow_tail

    @Slot(int, float, bool)
    def saveViewport(self, index, position, follow):
        self._view.scroll_index, self._view.scroll_y, self._view.follow_tail = index, position, follow

    def _mark_read(self, record):
        if record.id and self._chat_visible:
            self.store.data["sessionMeta"].setdefault(record.id, {})["unread"] = False

    @Slot(bool)
    def setConversationVisible(self, visible):
        self._chat_visible = visible
        if visible:
            self._mark_read(self._view)
            self.store.save()
            self.chatChanged.emit()

    @Slot(str)
    def setDraft(self, text):
        self._view.draft = text

    @Property(str, notify=chatChanged)
    def greeting(self):
        return self._view.greeting

    @Property(int, notify=chatChanged)
    def portrait(self):
        return self._view.portrait

    @Property("QVariantList", notify=chatChanged)
    def queuedMessages(self):
        result = []
        for row in self._view.queue:
            text, attachments = split_attachments(row["text"])
            result.append({**row, "text": text, "attachments": attachments})
        return result

    @Property(bool, notify=chatChanged)
    def loading(self):
        return self._view.busy and self._view.phase != "running"

    @Property(bool, notify=chatChanged)
    def running(self):
        return self._view.phase == "running" or (self._view.busy and self._view.action in ('prompt', 'widget-notify') and self._view.prompt_started is not None)

    @Property("QVariantMap", notify=chatChanged)
    def turnStatus(self):
        return self._turn_status(self._view)

    @Property(int, notify=chatChanged)
    def runningCount(self):
        return sum(record.phase == "running" for record in self._pool.records.values())

    def _session_flags(self, session_id):
        record = self._pool.find(session_id)
        meta = self.store.data["sessionMeta"].get(session_id, {})
        status = self._turn_status(record) if record else meta.get('lastTurn', {})
        return {"running": bool(record and (record.phase == "running" or status.get('state') in ('running', 'stopping'))), "loading": bool(record and record.phase in ("loading", "working")),
            "waiting": bool(record and record.approval), "unread": bool(meta.get("unread")),
            "outcome": status.get('state', '') or ('unread' if meta.get('unread') else ''),
            "busy": bool(record and record.busy) or session_id in self._management_jobs}

    def _models_busy(self, provider_id=None):
        return any(record.busy and (provider_id is None or record.provider == provider_id) for record in self._pool.records.values())

    @Property("QVariantMap", notify=changed)
    def config(self):
        data = copy.deepcopy(self.store.data)
        data["hasPassword"] = bool(data.pop("password"))
        data.pop("employeeId", None)
        if isinstance(self.adapter, UnconfiguredAdapter):
            data["providers"] = [p for p in data["providers"] if p["api"] != "internal"]
            if data["selectedProvider"] == "internal":
                data.update(selectedProvider="", selectedModel="")
        data["server"].pop("keys", None)
        for provider in data["providers"]:
            provider["hasKey"] = bool(provider.pop("key", ""))
            for model in provider["models"]:
                model.update(normalize_model(model))
        return data

    @Property(int, notify=layoutChanged)
    def sidebarWidth(self):
        return self.store.data["ui"]["sidebarWidth"]

    @Property(bool, notify=layoutChanged)
    def sidebarCollapsed(self):
        return self.store.data["ui"]["sidebarCollapsed"]

    @Slot(int, bool, result=bool)
    def saveSidebarLayout(self, width, collapsed):
        old = self.store.data["ui"]
        new = {**old, "sidebarWidth": max(200, min(480, width)), "sidebarCollapsed": collapsed}
        if old == new:
            return True
        self.store.data["ui"] = new
        try:
            self.store.save()
        except (OSError, RuntimeError):
            self.store.data["ui"] = old
            self.toast.emit("侧栏布局保存失败，请检查本机设置存储")
            return False
        self.layoutChanged.emit()
        return True

    @Slot(str, result="QVariantMap")
    def contextWindowSuggestion(self, model_name):
        return context_suggestion(model_name)

    @Slot(str, result="QVariantMap")
    def visionSuggestion(self, model_name):
        return vision_suggestion(model_name)

    @Property("QVariantList", notify=chatChanged)
    def messages(self):
        return self._view.messages

    @Property("QVariantList", notify=chatChanged)
    def displayMessages(self):
        return self._chat_model.rows

    @Slot(int, result='QVariantMap')
    def displayMessage(self, row):
        return self._chat_model.message(row, synchronous=True)

    @Slot(int)
    def copyDisplayMessage(self, row):
        model = self._chat_model
        if model.snapshot and row < model.base_count:
            snapshot = model.snapshot
            self._copy_chat(lambda: snapshot.copy_text(row))
            return
        message = model.message(row)
        if message.get('_chunked'):
            index = row - model.base_count
            first = model._source_starts[index]
            end = next((value for value in model._source_starts[index + 1:] if value > first), len(model._source))
            parts = ChatModel.project(model._source[first:end])
        else:
            parts = [message]
        pieces = []
        for value in parts:
            prose = '\n\n'.join(step['text'] for step in value.get('activity', []) if step['kind'] == 'text')
            pieces.extend([prose or value.get('text', ''), *(item.get('name', '') for item in value.get('attachments', []))])
        self.copy('\n'.join(piece for piece in pieces if piece))

    @Slot(str)
    def copyChatSelection(self, raw):
        from .chat_copy import selected_text
        selection = json.loads(raw)
        model = self._chat_model
        snapshot, overlay = model.snapshot, list(model.rows)
        script = (self.root / 'app/qml/markdown.js').read_text(encoding='utf-8')
        self._copy_chat(lambda: selected_text(script, snapshot, overlay, selection['anchor'], selection['cursor'], selection.get('expanded', {})))

    def _copy_chat(self, job):
        self._copy_request += 1
        self._job(f'copy-chat:{self._copy_request}', job)

    @Slot()
    def openChatDirectory(self):
        path = Path(self._view.workspace or self.store.data["workspace"])
        if path.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))
        else:
            self.toast.emit("当前会话目录不存在")

    @Slot(str, bool)
    def openChatboxPath(self, raw, reveal):
        path = Path(raw)
        if not path.is_absolute() or not path.exists():
            self.toast.emit("文件已移动或不存在")
            return
        try:
            if reveal and path.is_file() and sys.platform == "win32":
                subprocess.Popen(["explorer.exe", "/select,", str(path)], creationflags=CREATE_NO_WINDOW)
            elif reveal and path.is_file() and sys.platform == "darwin":
                subprocess.Popen(["/usr/bin/open", "-R", str(path)])
            else:
                target = path.parent if reveal and path.is_file() else path
                if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(target))):
                    self.toast.emit("无法打开，请检查文件关联")
        except OSError:
            self.toast.emit("无法打开文件或文件夹")

    @Slot(str, result="QVariantMap")
    def chatboxFileInfo(self, raw):
        path = Path(raw)
        if not path.is_absolute() or not path.exists():
            return {}
        kind = "folder" if path.is_dir() else "image" if QImageReader(str(path)).canRead() else "file"
        items = media_view([{"path": str(path), "kind": kind}])
        return items[0] if items else {}

    @Slot(str)
    def attachChatboxFile(self, raw):
        path = Path(raw)
        if not path.is_absolute() or not path.exists():
            self.toast.emit("文件已移动或不存在")
            return
        self.addAttachments(json.dumps([QUrl.fromLocalFile(str(path)).toString()]))

    @Slot(str)
    def attachChatboxUrl(self, raw):
        if self._view.busy and self._view.phase != "running":
            return self.toast.emit("Pi 加载完成后可添加附件")
        url = self.normalizeWebUrl(raw)
        if not url or any(item["path"] == url for item in self._view.attachments):
            return
        if len(self._view.attachments) >= 20:
            return self.toast.emit("一次最多添加 20 个附件")
        self._view.attachments.append({"id": uuid.uuid4().hex, "name": QUrl(url).host(),
                                       "kind": "web", "path": url, "url": url})
        self.attachmentsChanged.emit()

    @Slot()
    def activateChatWindow(self):
        window = next((w for w in QGuiApplication.topLevelWindows() if w.objectName() == "mainWindow"), None)
        if window is None:
            return
        if window.visibility() == QWindow.Minimized:
            window.showNormal()
        window.raise_()
        window.requestActivate()
        if sys.platform == "win32" and QGuiApplication.platformName() == "windows":
            import ctypes
            handle = ctypes.c_void_p(int(window.winId()))
            ctypes.windll.user32.BringWindowToTop(handle)
            ctypes.windll.user32.SetForegroundWindow(handle)
            ctypes.windll.user32.GetForegroundWindow.restype = ctypes.c_void_p
            foreground = ctypes.windll.user32.GetForegroundWindow()
            if foreground and foreground != handle.value:
                # Explorer can retain the input queue after an OLE drop. Join
                # it only for activation, then immediately detach again.
                thread = ctypes.windll.kernel32.GetCurrentThreadId()
                other = ctypes.windll.user32.GetWindowThreadProcessId(ctypes.c_void_p(foreground), None)
                attached = other != thread and ctypes.windll.user32.AttachThreadInput(thread, other, True)
                try:
                    if attached:
                        ctypes.windll.user32.BringWindowToTop(handle)
                        ctypes.windll.user32.SetForegroundWindow(handle)
                finally:
                    if attached: ctypes.windll.user32.AttachThreadInput(thread, other, False)

    @Slot(str)
    def copyChatboxFile(self, raw):
        path = Path(raw)
        if not path.is_absolute() or not path.exists():
            self.toast.emit("文件已移动或不存在")
            return
        url = QUrl.fromLocalFile(str(path))
        mime = QMimeData()
        mime.setUrls([url])
        mime.setData('application/x-qt-windows-mime;value="Preferred DropEffect"', b'\x01\x00\x00\x00')
        mime.setData('x-special/gnome-copied-files', b'copy\n' + bytes(url.toEncoded()))
        mime.setData('application/x-kde-cutselection', b'0')
        QGuiApplication.clipboard().setMimeData(mime)
        self.toast.emit("文件已复制")

    @Property("QVariantList", notify=chatChanged)
    def sessions(self):
        return [{"id": s["id"], "title": s["title"]} for s in self._sessions]

    def _ensure_project(self, path, reopen=False):
        resolved = str(Path(path).expanduser().resolve())
        key = os.path.normcase(resolved)
        project_id = hashlib.sha256(key.encode()).hexdigest()[:16]
        if project_id in self.store.data["removedProjects"]:
            if not reopen:
                return None
            self.store.data["removedProjects"].remove(project_id)
        project = next((p for p in self.store.data["projects"] if os.path.normcase(p["path"]) == key), None)
        if not project:
            project = {"id": project_id, "name": Path(resolved).name or resolved, "path": resolved}
            self.store.data["projects"].append(project)
        return project

    @Property("QVariantList", notify=sidebarChanged)
    def projectRows(self):
        rows, grouped = [], set()
        metadata = self.store.data["sessionMeta"]
        visible_sessions = []
        for session in self._sessions:
            workspace = session.get("workspace", "")
            if workspace:
                key = os.path.normcase(str(Path(workspace).resolve()))
                if hashlib.sha256(key.encode()).hexdigest()[:16] in self.store.data["removedProjects"]:
                    continue
            meta = metadata.get(session["id"], {})
            if bool(meta.get("archived")) == self._show_archived:
                visible_sessions.append({**session, "pinned": bool(meta.get("pinned")), "archived": bool(meta.get("archived"))})
        visible_sessions.sort(key=lambda s: not s["pinned"])
        for project in sorted(self.store.data["projects"], key=lambda p: not p.get("pinned", False)):
            children = [s for s in visible_sessions if s.get("workspace") and os.path.normcase(str(Path(s["workspace"]).resolve())) == os.path.normcase(project["path"])]
            if self._show_archived and not children:
                continue
            collapsed = project["id"] in self._collapsed_projects
            rows.append({**project, "kind": "project", "title": project["name"], "collapsed": collapsed, "pinned": bool(project.get("pinned")),
                         "selected": project["id"] == self.store.data["activeProject"]})
            for session in children:
                grouped.add(session["id"])
                if not collapsed:
                    rows.append({"id": session["id"], "title": session["title"], "kind": "session", "pinned": session["pinned"], "archived": session["archived"], "selected": self._view.id == session["id"], **self._session_flags(session["id"])})
        ungrouped = [s for s in visible_sessions if s["id"] not in grouped]
        if ungrouped:
            rows.append({"id": "ungrouped", "kind": "label", "title": "其他会话", "selected": False})
            rows.extend({"id": s["id"], "title": s["title"], "kind": "session", "pinned": s["pinned"], "archived": s["archived"], "selected": self._view.id == s["id"], **self._session_flags(s["id"])} for s in ungrouped)
        return rows

    @Property(bool, notify=chatChanged)
    def showArchived(self):
        return self._show_archived

    @Slot()
    def toggleArchived(self):
        self._show_archived = not self._show_archived
        self.chatChanged.emit()

    @Slot(str, str)
    def togglePinned(self, kind, item_id):
        item = next((p for p in self.store.data["projects"] if p["id"] == item_id), None) if kind == "project" else self.store.data["sessionMeta"].setdefault(item_id, {})
        if item is not None:
            item["pinned"] = not item.get("pinned", False)
            self.store.save()
            self.chatChanged.emit()

    def _clear_current(self):
        record = self._new_view()
        self._project_drafts[record.workspace] = record
        self._activate(record)

    @Slot(str, bool)
    def archiveSession(self, session_id, archived):
        if not any(s["id"] == session_id for s in self._sessions):
            return
        self.store.data["sessionMeta"].setdefault(session_id, {})["archived"] = archived
        if archived and self._view.id == session_id:
            self._clear_current()
        self.store.save()
        self.chatChanged.emit()

    @Slot(str, bool)
    def archiveProject(self, project_id, archived):
        project = next((p for p in self.store.data["projects"] if p["id"] == project_id), None)
        if not project:
            return
        ids = [s["id"] for s in self._sessions if s.get("workspace") and os.path.normcase(str(Path(s["workspace"]).resolve())) == os.path.normcase(project["path"])]
        for session_id in ids:
            self.store.data["sessionMeta"].setdefault(session_id, {})["archived"] = archived
        if archived and self._view.id in ids:
            self._clear_current()
        self.store.save()
        self.chatChanged.emit()

    @Slot(str)
    def removeProject(self, project_id):
        if not any(p["id"] == project_id for p in self.store.data["projects"]):
            return
        self.store.data["projects"] = [p for p in self.store.data["projects"] if p["id"] != project_id]
        if project_id not in self.store.data["removedProjects"]:
            self.store.data["removedProjects"].append(project_id)
        if self.store.data["activeProject"] == project_id:
            self.store.data.update(activeProject="", workspace="")
            self._clear_current()
        self.store.save()
        self.changed.emit()
        self.chatChanged.emit()

    @Slot(str)
    def revealProject(self, project_id):
        project = next((p for p in self.store.data["projects"] if p["id"] == project_id), None)
        if project:
            QDesktopServices.openUrl(QUrl.fromLocalFile(project["path"]))

    @Slot(str, str)
    def renameProject(self, project_id, title):
        title = title.strip()
        if not title or len(title) > 120:
            return self.toast.emit("项目名称需为 1–120 个字符")
        project = next((p for p in self.store.data["projects"] if p["id"] == project_id), None)
        if project:
            project["name"] = title
            self.store.save()
            self.changed.emit()
            self.chatChanged.emit()

    @Slot(str, str)
    def renameSession(self, session_id, title):
        title = title.strip()
        record = self._pool.find(session_id)
        if (record and record.busy) or not title or len(title) > 120:
            return self.toast.emit("请等待任务结束，并填写 1–120 个字符的名称")
        if record and record.process:
            self._command_pi("rename", record=record, title=title)
        else:
            self._session_action("rename", session_id, title=title)

    @Slot(str, str)
    def exportSession(self, session_id, url):
        if QUrl(url).isLocalFile():
            self._session_action("export", session_id, outputFile=QUrl(url).toLocalFile())

    @Slot(str)
    def forkSessionById(self, session_id):
        source = self._pool.find(session_id)
        if source and source.busy:
            return self.toast.emit("此会话结束后可创建分支")
        session = next((s for s in self._sessions if s["id"] == session_id), None)
        if session:
            record = self._new_view(session.get("workspace") or self.store.data["workspace"])
            record.history = copy.deepcopy(session.get("history", []))
            record.model = session.get("model") or record.model
            record.provider = session.get("provider") or record.provider
            self._activate(record)
            self._command_pi("fork", targetFile=session.get("file", ""))

    def _session_action(self, action, session_id, **values):
        session = next((s for s in self._sessions if s["id"] == session_id), None)
        if not session:
            return
        payload = {"action": action, "sessionFile": session.get("file"), "history": session.get("history", []),
            "cwd": session.get("workspace") or self.store.data["workspace"] or str(self.store.directory),
            "sessionDir": str(self.store.directory / "pi/sessions"), **values}
        if session_id in self._management_jobs:
            return
        self._management_jobs.add(session_id)
        self.chatChanged.emit()
        def execute():
            result = subprocess.run([node_executable(), str(self._release / "bridge.mjs"), "--session-action"],
                input=json.dumps(payload), capture_output=True, text=True, encoding="utf-8", timeout=30, creationflags=CREATE_NO_WINDOW)
            output = json.loads(result.stdout)
            if result.returncode or not output.get("ok"):
                raise RuntimeError(output.get("error", "会话操作失败"))
            return {"oldId": session_id, "action": action, "session": output["session"]}
        self._job("session-action:" + session_id, execute)

    @Property("QVariantList", notify=attachmentsChanged)
    def attachments(self):
        return [{k: v for k, v in item.items() if k not in ("data",)} for item in self._view.attachments]

    @Slot(str)
    def toggleProject(self, project_id):
        if project_id in self._collapsed_projects:
            self._collapsed_projects.remove(project_id)
        else:
            self._collapsed_projects.add(project_id)
        self.chatChanged.emit()

    @Slot(str)
    def openProject(self, project_id):
        project = next((p for p in self.store.data["projects"] if p["id"] == project_id), None)
        if project:
            self.setWorkspace(QUrl.fromLocalFile(project["path"]).toString())

    @Slot(str)
    def dropProjects(self, raw):
        try:
            paths = [Path(QUrl(url).toLocalFile()) for url in json.loads(raw) if QUrl(url).isLocalFile()]
            folders = [path for path in paths if path.is_dir()]
            for path in folders:
                self._ensure_project(path, reopen=True)
            if folders:
                self.store.save()
                self.setWorkspace(QUrl.fromLocalFile(str(folders[0])).toString())
            else:
                self.toast.emit("把文件夹拖到这里即可打开项目")
        except (ValueError, OSError):
            self.toast.emit("无法打开拖入的目录")

    @Slot(str, result=bool)
    def addAttachments(self, raw):
        if self._view.busy and self._view.phase != "running":
            self.toast.emit("Pi 加载完成后可添加附件")
            return False
        accepted = False
        try:
            for url in json.loads(raw):
                parsed = QUrl(url)
                if not parsed.isLocalFile():
                    continue
                item = self._file_attachment(url)
                if item is None: continue
                if any(existing["path"] == item["path"] for existing in self._view.attachments):
                    accepted = True
                    continue
                if len(self._view.attachments) >= 20:
                    self.toast.emit("一次最多添加 20 个附件")
                    break
                self._view.attachments.append(item)
                accepted = True
        except (ValueError, OSError):
            self.toast.emit("无法读取附件")
        self.attachmentsChanged.emit()
        return accepted

    def _file_attachment(self, url, *, encode_image=True):
        parsed = QUrl(url)
        if not parsed.isLocalFile(): return None
        path = Path(parsed.toLocalFile()).resolve(strict=True)
        if not path.is_file() and not path.is_dir(): return None
        kind = "folder" if path.is_dir() else "file"
        image = None
        if path.is_file() and path.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"):
            if path.stat().st_size > 20 * 1024 * 1024:
                self.toast.emit("图片不能超过 20 MB")
                return None
            reader = QImageReader(str(path))
            size = reader.size()
            if size.isValid() and size.width() * size.height() > 40_000_000:
                self.toast.emit("图片尺寸过大")
                return None
            image = reader.read()
            if image.isNull():
                return None
        item = {"id": uuid.uuid4().hex, "name": path.name, "path": str(path), "kind": kind}
        if image is not None:
            item.update(kind="image", preview=QUrl.fromLocalFile(str(path)).toString())
            if encode_image:
                item.update(data=self._image_data(image), mime="image/png")
        return item

    @staticmethod
    def _image_data(image):
        if max(image.width(), image.height()) > 2560:
            from PySide6.QtCore import Qt
            image = image.scaled(2560, 2560, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        buffer = QBuffer()
        buffer.open(QIODevice.WriteOnly)
        image.save(buffer, "PNG")
        return base64.b64encode(bytes(buffer.data())).decode()

    @Slot(result=bool)
    def pasteAttachments(self):
        if self._view.busy and self._view.phase != "running":
            return False
        mime = QGuiApplication.clipboard().mimeData()
        if mime is None:
            return False
        urls = [url for url in mime.urls() if url.isLocalFile()]
        # IDEs can advertise URI/image formats alongside code. Only a text
        # representation of the copied files themselves should prefer files.
        file_texts = {
            "\n".join(url.toString() for url in urls),
            "\n".join(url.toLocalFile() for url in urls),
            "\n".join(os.path.normpath(url.toLocalFile()) for url in urls),
        }
        clipboard_text = mime.text()
        text = clipboard_text.replace("\r\n", "\n").rstrip("\n")
        if clipboard_text and (not urls or text not in file_texts):
            return False
        if urls and self.addAttachments(json.dumps([url.toString() for url in urls])):
            return True
        if mime.hasImage():
            folder = self.store.directory / "attachments"
            folder.mkdir(exist_ok=True)
            path = folder / ("clipboard-" + uuid.uuid4().hex[:12] + ".png")
            image = QGuiApplication.clipboard().image()
            if not image.isNull() and image.save(str(path)):
                return self.addAttachments(json.dumps([QUrl.fromLocalFile(str(path)).toString()]))
        return False

    @Slot(str)
    def removeAttachment(self, attachment_id):
        self._view.attachments = [item for item in self._view.attachments if item["id"] != attachment_id]
        self.attachmentsChanged.emit()

    @Property(str, notify=chatChanged)
    def activeSession(self):
        return self._view.id

    @Property(str, notify=viewChanged)
    def conversationToken(self):
        return self._view.key

    @Property(str, notify=chatChanged)
    def sessionTitle(self):
        return next((s["title"] for s in self._sessions if s["id"] == self._view.id), "新会话")

    @Property(bool, notify=chatChanged)
    def busy(self):
        return self._view.busy

    @Property(str, notify=chatChanged)
    def toolStatus(self):
        return self._view.tool_status

    @Property(bool, notify=chatChanged)
    def compactionAvailable(self):
        return bool(self._view.id and self._view.file and self._view.model and not self._kernel_busy)

    @Property(bool, notify=chatChanged)
    def compacting(self):
        return self._view.compaction_running or (self._view.busy and self._view.action == "compact")

    @Property(str, notify=reasoningChanged)
    def reasoningEffort(self):
        return self._view.reasoning_effort

    @Slot(str, result=bool)
    def setReasoningEffort(self, value):
        if value not in ("off", "low", "high", "max"): return False
        record = self._view
        record.reasoning_effort = value
        self.store.data["ui"]["reasoningEffort"] = value
        if record.id:
            self.store.data["sessionMeta"].setdefault(record.id, {})["reasoningEffort"] = value
        self.store.save()
        self._pool.write(record, {"type": "reasoning_effort", "value": value})
        self.reasoningChanged.emit()
        return True

    @Property(bool, notify=changed)
    def serverRunning(self):
        return self.public_server is not None

    @Property("QVariantList", notify=proxyKeysChanged)
    def proxyKeys(self):
        return [key_summary(row) for row in self.store.data["server"]["keys"]]

    @Property("QStringList", notify=changed)
    def proxyAddresses(self):
        return ["127.0.0.1"] + (lan_addresses() if self.store.data["server"]["lan"] else [])

    @Slot()
    def refreshProxyAddresses(self):
        self.changed.emit()

    @Slot(result=str)
    def generateProxyKey(self):
        return generate_key()

    @Slot(result="QVariantMap")
    def takeCreatedProxyKey(self):
        value, self._created_proxy_key = self._created_proxy_key, {}
        return value

    def _sync_proxy_usage(self):
        usage, updated = self._proxy_keys.usage(), False
        for row in self.store.data["server"]["keys"]:
            value = usage.get(row["id"], row.get("lastUsedAt", ""))
            if value != row.get("lastUsedAt", ""):
                row["lastUsedAt"], updated = value, True
        if updated:
            self.proxyKeysChanged.emit()

    def _commit_proxy_keys(self, rows):
        old = self.store.data["server"]["keys"]
        self.store.data["server"]["keys"] = rows
        try:
            self.store.save()
        except (OSError, RuntimeError) as exc:
            self.store.data["server"]["keys"] = old
            self.toast.emit("Key 保存失败：" + str(exc))
            return False
        self._proxy_keys.update(rows)
        self.proxyKeysChanged.emit()
        self.changed.emit()
        return True

    @Slot(str, str, str, result=bool)
    def saveProxyKey(self, key_id, name, value):
        self._created_proxy_key = {}
        try:
            self._sync_proxy_usage()
            rows = copy.deepcopy(self.store.data["server"]["keys"])
            existing = next((row for row in rows if row["id"] == key_id), None)
            if key_id and existing is None:
                raise ValueError("Key 已不存在")
            if not existing and len(rows) >= 100:
                raise ValueError("最多保存 100 个 Key")
            fresh = value.strip() or (generate_key() if existing is None else "")
            row = make_key(name, fresh) if fresh else {**existing, "name": name.strip()}
            if not row["name"] or len(row["name"]) > 80 or any(ord(c) < 32 for c in row["name"]):
                raise ValueError("Key 名称需为 1–80 个字符")
            if any(item["id"] != key_id and (item["digest"] == row["digest"] or item["name"] == row["name"]) for item in rows):
                raise ValueError("Key 名称和 Key 值不能与现有条目重复")
            if existing:
                existing.update(name=row["name"], digest=row["digest"], hint=row["hint"])
            else:
                rows.append(row)
            if self._commit_proxy_keys(rows):
                if fresh:
                    self._created_proxy_key = {"id": existing["id"] if existing else row["id"], "key": fresh}
                self.toast.emit("Key 已保存，对新请求生效")
                return True
        except ValueError as exc:
            self.toast.emit(str(exc))
        return False

    @Slot(str, bool)
    def setProxyKeyEnabled(self, key_id, enabled):
        self._sync_proxy_usage()
        rows = copy.deepcopy(self.store.data["server"]["keys"])
        row = next((row for row in rows if row["id"] == key_id), None)
        if row is None:
            return self.toast.emit("Key 已不存在")
        row["enabled"] = enabled
        if self._commit_proxy_keys(rows):
            self.toast.emit("Key 已启用" if enabled else "Key 已停用")

    @Slot(str)
    def revokeProxyKey(self, key_id):
        self._sync_proxy_usage()
        rows = [row for row in self.store.data["server"]["keys"] if row["id"] != key_id]
        if self._commit_proxy_keys(rows):
            self.toast.emit("Key 已撤销，对新请求生效")

    @Property(str, notify=changed)
    def kernelVersion(self):
        try:
            return installed_version(self._release)
        except (FileNotFoundError, KeyError):
            return "未安装"

    @Property(QObject, constant=True)
    def appAbout(self): return self._app_about

    @Property(bool, notify=changed)
    def kernelBusy(self):
        return self._kernel_busy

    @Property(str, notify=changed)
    def lastSendError(self):
        return self._last_send_error

    @Property(str, notify=changed)
    def kernelStatus(self):
        return self._kernel_status

    @Property(str, notify=changed)
    def latestVersion(self):
        return self._latest

    @Property(str, notify=changed)
    def workspaceName(self):
        project = next((p for p in self.store.data["projects"] if p["id"] == self.store.data["activeProject"]), None)
        return project["name"] if project else Path(self.store.data["workspace"]).name if self.store.data["workspace"] else "选择工作目录"

    @Property("QVariantMap", notify=approvalChanged)
    def pendingApproval(self):
        return self._view.approval

    @Property("QVariantMap", notify=changed)
    def agentResources(self):
        return self._view.resources

    @Property("QVariantMap", notify=contextUsageChanged)
    def contextUsage(self):
        usage = self._view.context_usage
        return usage if usage.get("model") == self._view.model else {}

    @Property("QVariantList", notify=chatChanged)
    def sessionTree(self):
        return self._view.tree

    @Slot(bool)
    def respondApproval(self, allowed):
        value = allowed if self._view.approval.get("method") == "confirm" else None
        self._write_pi({"type": "ui_response", "id": self._view.approval.get("id"), "value": value})
        self._view.approval = {}
        self.approvalChanged.emit()

    @Slot(str)
    def respondPiDialog(self, value):
        self._write_pi({"type": "ui_response", "id": self._view.approval.get("id"), "value": value})
        self._view.approval = {}
        self.approvalChanged.emit()

    @Slot(str)
    def setToolPermissionMode(self, mode):
        """Apply the user's tool permission choice without interrupting sessions."""
        if mode not in ("auto", "ask"):
            return self.toast.emit("工具执行权限模式无效")
        agent = self.store.data["agent"]
        previous = agent.get("toolPermissionMode", "auto")
        if mode == previous:
            return
        agent["toolPermissionMode"] = mode
        try:
            self.store.save()
        except (OSError, RuntimeError) as exc:
            agent["toolPermissionMode"] = previous
            return self.toast.emit("工具执行权限保存失败：" + str(exc))
        self.changed.emit()
        payload = {"type": "tool_permission_mode", "mode": mode,
                   "language": self.language, "dataDir": str(self.store.directory)}
        for record in self._pool.records.values():
            if record.process is not None:
                self._pool.write(record, payload)

    @Slot(str)
    def saveAgent(self, raw):
        if self._view.busy:
            return self.toast.emit("请先停止当前任务")
        try:
            values = json.loads(raw)
            for key, low, high in (("maxTokens", 256, 32768),):
                if not low <= int(values[key]) <= high:
                    raise ValueError(f"{key} 范围为 {low}–{high}")
                values[key] = int(values[key])
            if len(values["instructions"]) > 16000:
                raise ValueError("自定义指令不能超过 16000 字符")
            values["agentDir"] = str(Path(values.get("agentDir") or Path.home() / ".pi/agent").expanduser().resolve())
            for key in ("skillPaths", "extensionPaths"):
                values[key] = [str(Path(p.strip()).expanduser().resolve()) for p in values.get(key, []) if p.strip()]
            self.store.data["agent"].update({k: values[k] for k in ("maxTokens", "instructions", "autoCompaction", "agentDir", "skillPaths", "extensionPaths")})
            self.store.save()
            self._restart_pi()
            self.changed.emit()
            self.toast.emit("Pi 设置已保存，下次加载生效")
        except (ValueError, KeyError, TypeError) as exc:
            self.toast.emit(str(exc))

    @Slot(str)
    def openPiFolder(self, kind):
        base = Path(self.store.data["agent"].get("agentDir") or Path.home() / ".pi/agent")
        path = base / kind if kind in ("skills", "extensions") else base
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    @Slot()
    def openPiGithub(self):
        QDesktopServices.openUrl(QUrl("https://github.com/earendil-works/pi"))

    def _mcp_path(self, scope, workspace=None):
        if scope == "global":
            return Path(self.store.data["agent"].get("agentDir") or Path.home() / ".pi/agent") / "mcp.json"
        workspace = self.store.data["workspace"] if workspace is None else workspace
        if scope == "project" and workspace:
            return Path(workspace) / ".pi/mcp.json"
        raise ValueError("请先打开项目目录")

    @Slot(str, result=str)
    def readMcp(self, scope):
        try:
            path = self._mcp_path(scope)
            return path.read_text(encoding="utf-8") if path.exists() else '{\n  "mcpServers": {}\n}'
        except (ValueError, OSError) as error:
            self.toast.emit(str(error))
            return '{\n  "mcpServers": {}\n}'

    @Slot(str, result=str)
    def mcpConfigPath(self, scope):
        try:
            return str(self._mcp_path(scope))
        except ValueError:
            return "请先打开项目"

    @Slot(str, str)
    def saveMcp(self, scope, raw):
        if self._view.busy:
            return self.toast.emit("请等待当前任务结束")
        try:
            path = self._mcp_path(scope)
            data = json.loads(raw)
            if not isinstance(data, dict) or not isinstance(data.get("mcpServers", {}), dict):
                raise ValueError('请粘贴包含 "mcpServers" 对象的 JSON')
            if len(raw) > 1_000_000:
                raise ValueError("MCP 配置过大")
        except (ValueError, OSError) as error:
            return self.toast.emit(str(error))
        record = self._view
        record.operation = True
        job_name = "mcp-save:" + record.key
        self._mcp_jobs[job_name] = (record, scope, record.workspace)
        self.chatChanged.emit()
        global_raw = raw if scope == "global" else self.readMcp("global")
        project_raw = raw if scope == "project" else self.readMcp("project") if self.store.data["workspace"] else '{"mcpServers":{}}'
        def save():
            result = subprocess.run([node_executable(), str(self._release / "bridge.mjs"), "--check-mcp"],
                input=json.dumps({"global": global_raw, "project": project_raw}), capture_output=True,
                text=True, encoding="utf-8", timeout=25, creationflags=CREATE_NO_WINDOW)
            checked = json.loads(result.stdout)
            if not checked.get("ok"):
                raise ValueError(checked.get("error", "Pi 未接受此 MCP 配置"))
            path.parent.mkdir(parents=True, exist_ok=True)
            target = path.with_suffix(".json.tmp")
            target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            target.replace(path)
            return scope
        self._job(job_name, save)

    def _mcp_environment(self, workspace=None):
        names = set()
        for scope in ("global", "project"):
            try:
                path = self._mcp_path(scope, workspace)
                if path.is_file():
                    names.update(re.findall(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", path.read_text(encoding="utf-8")))
            except (ValueError, OSError):
                pass
        return {name: os.environ[name] for name in names if name in os.environ}

    @Slot()
    def pollCapabilities(self):
        if self._view.process and not self._view.busy:
            self._write_pi({"type": "resources"})

    @Slot()
    def loadCapabilities(self):
        if not self._view.busy:
            if self._view.process:
                self.pollCapabilities()
            else:
                self._command_pi("inspect")

    @Slot(str)
    def reconnectMcp(self, name):
        if re.fullmatch(r"[A-Za-z0-9_-]+", name) and not self._view.busy:
            self._command_pi("mcp-command", text="/mcp reconnect " + name)

    @Slot()
    def refreshAgent(self):
        if not self._view.busy:
            self._pool.retire(self._view)
            return self._command_pi("inspect")
        return False

    @Slot(str)
    def copy(self, value):
        self._copy_request += 1
        QGuiApplication.clipboard().setText(value)
        self.toast.emit("已复制到剪贴板")

    @Slot(str)
    def setWorkspace(self, url):
        path = QUrl(url).toLocalFile()
        if Path(path).is_dir():
            self.store.data["workspace"] = str(Path(path).resolve())
            project = self._ensure_project(path, reopen=True)
            self.store.data["activeProject"] = project["id"]
            self._collapsed_projects.discard(project["id"])
            record = self._project_drafts.get(project["path"])
            if record is None or record.messages or record.busy:
                record = self._new_view(project["path"])
                self._project_drafts[project["path"]] = record
            self._activate(record)

    @Slot(bool)
    def setDark(self, value):
        self.setTheme("dark" if value else "light")

    @Slot(str)
    def setTheme(self, value):
        custom = next((row for row in self.customThemes if row["id"] == value), None)
        if value not in BASES and not custom:
            return
        self.store.data.update(theme=value, dark=(custom["base"] if custom else value) == "dark")
        self.store.save()
        self.changed.emit()

    @Slot(str)
    def setFontFamily(self, name):
        self.store.data["fontFamily"] = "" if name == "系统默认" else name
        self.store.save()
        app = QGuiApplication.instance()
        family = self.store.data["fontFamily"]
        if isinstance(app, QGuiApplication):
            if family:
                font = app.font()
                font.setFamily(family)
            else:
                font = QFont("Microsoft YaHei UI", 10) if os.name == "nt" else QFontDatabase.systemFont(QFontDatabase.GeneralFont)
            app.setFont(font)
        self.changed.emit()

    @Property('QVariantList', notify=changed)
    def availableFonts(self):
        if not isinstance(QGuiApplication.instance(), QGuiApplication):
            return ["系统默认"]
        from PySide6.QtGui import QFontDatabase
        installed = set(QFontDatabase.families())
        curated = ["Noto Sans CJK SC", "Noto Sans SC", "Microsoft YaHei UI", "WenQuanYi Micro Hei",
                   "WenQuanYi Zen Hei", "PingFang SC", "SimSun", "sans-serif", "serif"]
        return ["系统默认"] + [f for f in curated if f in installed or f in ("sans-serif", "serif")]

    @Property('QVariantList', notify=changed)
    def customThemes(self):
        return [dict(row, id='custom:' + row['id']) for row in theme_library(self.store.data.get('themes'))]

    @Property('QVariantMap', notify=changed)
    def themeStyle(self):
        return next((row for row in self.customThemes if row['id'] == self.store.data['theme']), {})

    @Slot(str, result=bool)
    def importTheme(self, url):
        previous = dict(self.store.data)
        try:
            item = read_theme(QUrl(url).toLocalFile() or url)
            rows = theme_library(self.store.data.get('themes'))
            if not any(row['id'] == item['id'] for row in rows) and len(rows) >= THEME_LIMIT:
                raise ValueError('最多保存 32 个自定义主题，请先删除不需要的主题')
            self.store.data.update(themes=[row for row in rows if row['id'] != item['id']] + [item], theme='custom:' + item['id'], dark=item['base'] == 'dark')
            self.store.save()
        except (OSError, ValueError, RuntimeError) as error:
            self.store.data = previous
            self.toast.emit('主题导入失败：' + str(error))
            return False
        self.changed.emit()
        self.toast.emit('主题已导入并应用')
        return True

    @Slot(str)
    def removeTheme(self, theme_id):
        item = next((row for row in self.customThemes if row['id'] == theme_id), None)
        if not item:
            return
        previous = dict(self.store.data)
        self.store.data['themes'] = [row for row in theme_library(self.store.data.get('themes')) if 'custom:' + row['id'] != theme_id]
        if self.store.data['theme'] == theme_id:
            self.store.data.update(theme=item['base'], dark=item['base'] == 'dark')
        try:
            self.store.save()
        except (OSError, RuntimeError):
            self.store.data = previous
            return self.toast.emit('无法保存主题设置')
        self.changed.emit()

    @Slot()
    def copyThemePrompt(self):
        self.copy((self.root / 'app/theme-prompt.txt').read_text(encoding='utf-8'))

    @Slot(str, str)
    def selectModel(self, provider, model):
        if self._view.busy:
            return self.toast.emit("请等待当前任务结束后切换模型")
        self.gateway.resolve(model, provider)
        if (model, provider) != (self._view.model, self._view.provider):
            self._view.context_usage = {}
        self.store.data.update(selectedProvider=provider, selectedModel=model)
        self._view.model, self._view.provider = model, provider
        self.store.save()
        self.changed.emit()
        self.contextUsageChanged.emit()

    def _validate_model_mappings(self, rows, previous_models, taken, *, plugin=False):
        """Share the mapping editor's alias rules with the provider editor."""
        if not isinstance(rows, list):
            raise ValueError("模型映射必须是数组")
        by_upstream = {model["upstream"]: model for model in previous_models}
        by_alias = {model["alias"]: model for model in previous_models}
        models = []
        for row in rows:
            upstream = row["upstream"].strip()
            requested_alias = row.get("alias", "").strip()
            previous = by_alias.get(requested_alias) or by_upstream.get(upstream)
            alias = requested_alias or (previous or {}).get("alias", upstream)
            if not upstream or not alias or alias in taken or any(c.isspace() for c in alias):
                raise ValueError("模型 ID 不能为空；别名不能重复或包含空白")
            taken.add(alias)
            settings = self._provider_plugins.modelSettings(row, previous) if plugin else normalize_model(row, previous or {})
            models.append({"upstream": upstream, "alias": alias, **settings})
        return models

    @Slot(str, str, str, str, str, str, result=bool)
    def saveProvider(self, provider_id, name, api, base_url, key, model_names):
        try:
            if provider_id and self._models_busy(provider_id):
                raise ValueError("该供应商仍有会话运行，结束后可修改连接")
            base_url = validate_base_url(base_url)
            rows = json.loads(model_names) if model_names.strip().startswith("[") else [{"upstream": m.strip(), "alias": ""} for m in re.split(r"[,，\n]", model_names) if m.strip()]
            names = [r["upstream"].strip() for r in rows]
            if not name.strip() or not names or api not in ("openai", "anthropic"):
                raise ValueError("请完整填写名称、协议和至少一个模型名")
            existing = self.gateway.provider(provider_id) if provider_id else None
            if existing and existing["api"] not in ("openai", "anthropic"):
                raise ValueError("请在对应供应商卡片中配置")
            kept_key = key or (existing or {}).get("key", "")
            if not kept_key:
                raise ValueError("请输入 API Key")
            provider_id = provider_id or uuid.uuid4().hex[:12]
            taken = {m["alias"] for p in self.store.data["providers"] if p["id"] != provider_id for m in p["models"]}
            models = self._validate_model_mappings(rows, (existing or {}).get("models", []), taken)
            provider = {**(existing or {}), "id": provider_id, "name": name.strip(), "api": api, "baseUrl": base_url, "key": kept_key, "models": models,
                        "proxy": (existing or {}).get('proxy', {'mode':'system', 'url':''})}
            self.store.data["providers"] = [provider if p["id"] == provider_id else p for p in self.store.data["providers"]]
            if not existing:
                self.store.data["providers"].append(provider)
            if self.store.data["selectedProvider"] == provider_id:
                current = self.store.data["selectedModel"]
                self.store.data["selectedModel"] = current if current in [m["alias"] for m in models] else models[0]["alias"]
            self._provider_plugins.repair_selection(provider_id)
            self.store.save()
            self._restart_pi()
            self.changed.emit()
            self.toast.emit("供应商配置已保存")
            return True
        except (ValueError, KeyError, TypeError) as exc:
            self.toast.emit(str(exc))
            return False

    @Slot(str)
    def refreshProviderModels(self, provider_id):
        provider = self.gateway.provider(provider_id)
        if not provider or provider["api"] not in ("openai", "anthropic"):
            return self.toast.emit("请在账号页刷新插件模型 / Refresh plugin models on the account page")
        if self._models_busy(provider_id):
            return self.toast.emit("请等待当前任务结束后刷新模型 / Wait for the current task before refreshing models")
        if provider_id in self._model_refresh_jobs:
            return
        snapshot = copy.deepcopy(provider)
        self._model_refresh_jobs[provider_id] = snapshot
        self.toast.emit("正在获取供应商模型信息 / Fetching provider model information")
        self._job("model-windows:" + provider_id, lambda: fetch_model_windows(snapshot))

    @Slot(str)
    def removeProvider(self, provider_id):
        provider = self.gateway.provider(provider_id)
        if provider and provider["api"] == "plugin":
            return self._provider_plugins.remove(provider_id)
        if self._models_busy(provider_id):
            return self.toast.emit("该供应商仍有会话运行，结束后可移除")
        self.store.data["providers"] = [p for p in self.store.data["providers"] if p["id"] != provider_id]
        self._provider_plugins.repair_selection()
        self.store.save()
        self._restart_pi()
        self.changed.emit()

    @Slot(str, result=bool)
    def saveMappings(self, raw):
        try:
            if self._models_busy():
                raise ValueError("会话正在使用模型映射，结束后可修改")
            rows = json.loads(raw)
            providers = copy.deepcopy(self.store.data["providers"])
            seen = set()
            for p in providers:
                if p["api"] == "internal" and isinstance(self.adapter, UnconfiguredAdapter):
                    continue
                if p["api"] == "plugin":
                    self._provider_plugins._idle(p["id"])
                models = self._validate_model_mappings([row for row in rows if row["provider"] == p["id"]],
                    p["models"], seen, plugin=p["api"] == "plugin")
                if not models and p["models"]:
                    raise ValueError("已有模型的供应商至少需要一个模型映射")
                if p["api"] == "plugin" and {m["upstream"] for m in models} != {m["upstream"] for m in p["models"]}:
                    raise ValueError("插件的模型 ID 请在账号页通过刷新获取")
                p["models"] = models
            self.store.data["providers"] = providers
            self._provider_plugins.repair_selection()
            self.store.save()
            self._restart_pi()
            self.changed.emit()
            self.toast.emit("模型映射已保存")
            return True
        except (ValueError, KeyError, TypeError, StopIteration) as exc:
            self.toast.emit(str(exc))
            return False

    def _new_proxy_listener(self, settings):
        return LocalServer(self.gateway, settings["port"], host="0.0.0.0" if settings["lan"] else "127.0.0.1",
                           protocols={"openai": settings["openai"], "anthropic": settings["anthropic"]},
                           authenticator=self._proxy_keys.authorized)

    def _replace_proxy_listener(self, settings):
        old = self.public_server
        if old is None:
            return
        host = "0.0.0.0" if settings["lan"] else "127.0.0.1"
        if old.host == host and old.port == settings["port"]:
            old.protocols = {"openai": settings["openai"], "anthropic": settings["anthropic"]}
            return
        if old.port != settings["port"]:
            new = self._new_proxy_listener(settings)
            old.close()
            self.public_server = new
            return
        # Switching a wildcard/loopback listener on the same port requires closing
        # the old socket first. Restore its exact binding if the replacement fails.
        restore = {"port": old.port, "lan": old.host == "0.0.0.0", **old.protocols}
        old.close()
        self.public_server = None
        try:
            self.public_server = self._new_proxy_listener(settings)
        except OSError:
            try:
                self.public_server = self._new_proxy_listener(restore)
            except OSError:
                pass
            raise

    @Slot(int, bool, bool, result=bool)
    @Slot(int, bool, bool, bool, result=bool)
    def saveServer(self, port, openai, anthropic, lan=False):
        if not 1024 <= port <= 65535 or not (openai or anthropic):
            self.toast.emit("端口范围为 1024–65535，至少启用一种协议")
            return False
        old = self.store.data["server"]
        new = {**old, "port": port, "openai": openai, "anthropic": anthropic, "lan": lan}
        try:
            self.store.data["server"] = new
            self.store.save()
        except (OSError, RuntimeError) as exc:
            self.store.data["server"] = old
            self.toast.emit("代理设置保存失败：" + str(exc))
            return False
        try:
            self._replace_proxy_listener(new)
        except OSError:
            self.store.data["server"] = old
            try:
                self.store.save()
            except (OSError, RuntimeError):
                self.toast.emit("监听失败且设置无法恢复保存，请检查本机凭据存储")
            self.changed.emit()
            self.toast.emit("监听失败，请检查端口或网络权限；原服务已恢复" if self.public_server else "监听失败，请检查端口或网络权限后重新启动")
            return False
        self.changed.emit()
        self.toast.emit("API 代理服务设置已保存")
        return True

    @Slot()
    def toggleServer(self):
        try:
            if self.public_server:
                self.public_server.close()
                self.public_server = None
            else:
                server = self.store.data["server"]
                if not any(row["enabled"] for row in server["keys"]):
                    return self.toast.emit("请先创建并启用至少一个 API Key")
                self.public_server = self._new_proxy_listener(server)
            self.changed.emit()
        except OSError:
            self.toast.emit("无法启动代理，请检查端口占用和网络权限")

    @Slot()
    def newSession(self):
        self._clear_current()

    @Slot(str)
    def openSession(self, session_id):
        session = next((s for s in self._sessions if s["id"] == session_id), None)
        if not session:
            return
        record = self._pool.find(session_id)
        stale = record and record.transcript and not record.busy and not record.transcript.matches_source()
        if (record and (not record.loaded or stale)) or (record is None and session.get('file') and self.transcripts.large(session['file'])):
            self._session_preview.open_direct(session_id)
            return
        if record is None:
            record = self._new_view(session.get("workspace", ""))
            record.id, record.file, record.title = session_id, session.get("file", ""), session["title"]
            record.extension_modes = clean_extension_modes(self.store.data["sessionMeta"].get(session_id, {}).get("extensionModes"))
            record.blocked_tools = clean_blocked_tools(self.store.data["sessionMeta"].get(session_id, {}).get("blockedTools"))
            effort = self.store.data["sessionMeta"].get(session_id, {}).get("reasoningEffort", record.reasoning_effort)
            record.reasoning_effort = effort if effort in ("off", "low", "high", "max") else "off"
            record.history = copy.deepcopy(session.get("history", []))
            record.messages = copy.deepcopy(session.get("messages", []))
            record.model, record.provider = session.get("model") or record.model, session.get("provider") or record.provider
            if record.file:
                try:
                    record.messages, record.tree = preview(record.file)
                except OSError:
                    self.toast.emit("原生会话文件暂时无法读取")
        self._activate(record)
        if record.model and not record.process and not record.busy and not record.transcript:
            # QProcess.start() is asynchronous; the transcript is already visible.
            self._command_pi("inspect", record=record)

    @Slot(str)
    def deleteSession(self, session_id):
        record = self._pool.find(session_id)
        if (record and record.busy) or session_id in self._management_jobs:
            return self.toast.emit("此会话正在运行，请先停止该会话")
        session = next((s for s in self._sessions if s["id"] == session_id), {})
        file = Path(session["file"]) if session.get("file") else None
        if file:
            base = (self.store.directory / "pi/sessions").resolve()
            if not file.resolve().is_relative_to(base):
                return self.toast.emit("只能删除 Umeko 会话目录中的文件")
            if record:
                self._pool.retire(record)
            file.unlink(missing_ok=True)
            self._job('discard-chat-index', lambda: self.transcripts.discard(file))
        if record:
            self._pool.records.pop(record.key, None)
        self._sessions = [s for s in self._sessions if s["id"] != session_id]
        self.store.data["sessionMeta"].pop(session_id, None)
        self.store.save()
        self.store.save_sessions(self._sessions)
        if self._view.id == session_id:
            self.newSession()
        self.chatChanged.emit()

    @Slot()
    def forkSession(self):
        if self._view.id and not self._view.busy:
            self.forkSessionById(self._view.id)

    @Slot()
    def compactSession(self):
        self._request_compaction()

    @Slot(str)
    def navigateSession(self, entry_id):
        if not self._view.busy:
            self._command_pi("navigate", entryId=entry_id)

    def _save_session(self):
        # UI index only. Native Pi JSONL is the sole transcript and tree store.
        self.store.save_sessions(self._sessions)

    def loadNativeIndex(self):
        directory = self.store.directory / "pi/sessions"
        if not directory.is_dir():
            return
        def load():
            result = subprocess.run([node_executable(), str(self._release / "bridge.mjs"), "--list-sessions", str(directory)],
                capture_output=True, text=True, encoding="utf-8", timeout=25, creationflags=CREATE_NO_WINDOW)
            if result.returncode:
                raise RuntimeError("原生会话索引暂时无法读取")
            return json.loads(result.stdout)["sessions"]
        self._job("index", load)

    @Slot(str, result=bool)
    def send(self, text):
        return self._send(text)

    @Slot(str, result=bool)
    def steer(self, text):
        if not text.strip() and not self._view.attachments:
            if self._view.phase == "running" and self._view.queue:
                self._write_pi({"type": "promote-queue"})
                return True
            return False
        return self._send(text, steering=True)

    @Slot(str)
    def editQueued(self, item_id):
        if any(row.get("id") == item_id for row in self._view.queue):
            self._write_pi({"type": "edit-queue", "id": item_id})

    @Slot(str)
    def steerQueued(self, item_id):
        if any(row.get("id") == item_id for row in self._view.queue):
            self._write_pi({"type": "steer-queued", "id": item_id})

    @Slot(str)
    def removeQueued(self, item_id):
        if any(row.get("id") == item_id for row in self._view.queue):
            self._write_pi({"type": "delete-queue", "id": item_id})

    @Slot()
    def stop(self):
        self._stop()

    def _job(self, name, fn):
        self.jobStarted.emit(name)
        def run():
            try:
                self.jobDone.emit(name, {"ok": True, "value": fn()})
            except Exception as exc:
                self.jobDone.emit(name, {"ok": False, "value": str(exc)[:250]})
        threading.Thread(target=run, daemon=True).start()

    def _on_job_done(self, name, result):
        if self._closing:
            return
        if name.startswith("model-windows:"):
            provider_id = name.split(":", 1)[1]
            snapshot = self._model_refresh_jobs.pop(provider_id, None)
            provider = self.gateway.provider(provider_id)
            if not result["ok"]:
                self.toast.emit(str(result["value"]))
                return
            if not snapshot or provider != snapshot or self._models_busy(provider_id):
                self.toast.emit("配置已变化或会话已开始，请重新刷新模型 / Configuration changed or a task started; refresh models again")
                return
            try:
                models = copy.deepcopy(provider["models"])
                windows = result["value"]
                for row in models:
                    if row["upstream"] not in windows:
                        continue
                    limit = windows[row["upstream"]]
                    row.pop("providerContextWindow", None)
                    if limit is not None:
                        row["providerContextWindow"] = limit
                    row.update(normalize_model(row))
                previous = provider["models"]
                provider["models"] = models
                try:
                    self.store.save()
                except (OSError, RuntimeError):
                    provider["models"] = previous
                    raise
                self._restart_pi()
                self.changed.emit()
                self.toast.emit("供应商模型信息已更新 / Provider model information updated")
            except (ValueError, OSError, RuntimeError) as exc:
                self.toast.emit(str(exc))
            return
        if name.startswith('copy-chat:'):
            if int(name.split(':', 1)[1]) != self._copy_request:
                return
            if result['ok']:
                self.copy(result['value'])
            else:
                self.toast.emit('暂时无法复制所选内容，请重新选择后再试')
            return
        if name.startswith('transcript:'):
            key = name.split(':', 1)[1]
            record = self._pool.records.get(key)
            if not record:
                return
            record.index_running = False
            if result['ok'] and result['value']['request'] == record.index_request and result['value']['file'] == record.file:
                value = result['value']
                snapshot, captured = value['snapshot'], value['captured']
                self._chat_model.viewportAboutToChange.emit() if record is self._view else None
                record.transcript = snapshot
                record.messages = [message for message in record.messages if id(message) not in captured]
                record.history, record.tree, record.loaded = [], [], True
                record.tail_characters = sum(len(message.get('text', '')) + len(message.get('thinking', '')) for message in record.messages)
                record.body_dirty = True
                if record is self._view:
                    self.chatChanged.emit()
                    self._chat_model.viewportChanged.emit()
                self._pool.trim_bodies()
            elif not result['ok'] and not self._closing:
                self.toast.emit('聊天索引暂时无法更新，当前内容仍可继续浏览')
            pending, record.index_pending = record.index_pending, None
            if pending:
                self._queue_transcript_index(record, *pending)
            return
        elif name.startswith("pi-admin:"):
            return
        if name.startswith("mcp-save:"):
            record, scope, workspace = self._mcp_jobs.pop(name)
            record.operation = False
            if result["ok"]:
                for cached in self._pool.records.values():
                    if scope == "global" or cached.workspace == workspace:
                        if cached.busy:
                            cached.stale = True
                        else:
                            self._pool.retire(cached)
                if record is self._view and not record.busy:
                    self._command_pi("inspect", record=record)
                self.toast.emit("MCP 配置已保存，正在由 Pi 重新加载")
            else:
                self.toast.emit(str(result["value"]))
            self.chatChanged.emit()
        elif name.startswith("session-action:"):
            self._management_jobs.discard(name.split(":", 1)[1])
            if result["ok"]:
                value = result["value"]
                old_id, session = value["oldId"], value["session"]
                previous = next((s for s in self._sessions if s["id"] == old_id), {})
                session = {**previous, **session}
                self._sessions = [session] + [s for s in self._sessions if s["id"] not in (old_id, session["id"])]
                if old_id != session["id"]:
                    meta = self.store.data["sessionMeta"].pop(old_id, {})
                    self.store.data["sessionMeta"][session["id"]] = meta
                cached = self._pool.find(old_id)
                if cached:
                    cached.id, cached.file, cached.title = session["id"], session.get("file", ""), session["title"]
                self.store.save()
                self._save_session()
                self.toast.emit("会话已导出" if value["action"] == "export" else "会话已重命名")
            else:
                self.toast.emit(str(result["value"]))
            self.chatChanged.emit()
        elif name == "index":
            if result["ok"]:
                native = result["value"]
                self._merge_native_sessions(native)
                for session in native:
                    if session.get("workspace"):
                        self._ensure_project(session["workspace"])
                self.store.save()
                self._save_session()
                self.chatChanged.emit()
        elif name == "check":
            self._kernel_busy = False
            if result["ok"]:
                self._latest = result["value"]
                self._kernel_status = "已是最新版本" if self._latest == self.kernelVersion else "发现可用版本 " + self._latest
            else:
                self._kernel_status = "检查失败，当前内核可继续使用"
                self.toast.emit("无法访问 npm 软件源，请检查网络")
        elif name == "update":
            self._kernel_busy = False
            if result["ok"]:
                self._restart_pi()
                self._release = Path(result["value"])
                self._kernel_status = "内核更新完成，兼容性验证通过"
            else:
                self._kernel_status = "更新失败，原有内核保持可用"
                self.toast.emit(str(result["value"]))
        self.changed.emit()

    @Slot()
    def checkKernel(self):
        if self._kernel_busy or self._view.busy:
            return self.toast.emit("请等待当前任务结束")
        self._kernel_busy, self._kernel_status = True, "正在检查 Pi 内核版本…"
        self.changed.emit()
        def check():
            result = subprocess.run([*npm_command(), "view", PACKAGE, "version", "--json"],
                env=npm_environment(self.store.data["agent"]), cwd=self._view.workspace or self.store.directory,
                capture_output=True, text=True, encoding="utf-8", timeout=45, creationflags=CREATE_NO_WINDOW)
            if result.returncode: raise RuntimeError("无法访问 npm 软件源，请检查 Pi 的 npm 配置")
            version = json.loads(result.stdout)
            if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+(?:-[\w.-]+)?", version):
                raise RuntimeError("npm 返回的 Pi 版本无效")
            return version
        self._job("check", check)

    @Slot()
    def updateKernel(self):
        if self._kernel_busy or self._view.busy:
            return self.toast.emit("请等待当前任务结束")
        if not self._latest:
            return self.checkKernel()
        if self._latest == self.kernelVersion:
            return self.toast.emit("当前 Pi 内核已是最新版本")
        if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[\w.-]+)?", self._latest):
            return self.toast.emit("版本号无效")
        version = self._latest
        self._kernel_busy, self._kernel_status = True, "下载并验证内核，完成后切换…"
        self.changed.emit()
        def update():
            npm = npm_command()
            kernels = self.store.directory / "kernels"
            kernels.mkdir(exist_ok=True)
            stage = kernels / ("staging-" + uuid.uuid4().hex)
            stage.mkdir()
            (stage / "package.json").write_text(json.dumps({"private": True, "dependencies": {PACKAGE: version}}))
            result = subprocess.run([*npm, "install", "--prefix", str(stage), "--ignore-scripts", "--no-audit", "--no-fund"],
                                    env=npm_environment(self.store.data["agent"]), cwd=self._view.workspace or self.store.directory,
                                    capture_output=True, timeout=180, creationflags=CREATE_NO_WINDOW)
            if result.returncode:
                raise RuntimeError("内核下载失败；原有版本未改变")
            release = kernels / ("candidate-" + uuid.uuid4().hex)
            project_runtime(stage, release)
            verify_runtime(release, self.root / "runtime/bridge.mjs")
            final = kernels / ("coding-" + version)
            if final.exists():
                verify_runtime(final, self.root / "runtime/bridge.mjs")
            else:
                release.rename(final)
            pointer = kernels / "active.tmp"
            pointer.write_text(json.dumps({"version": version}))
            pointer.replace(kernels / "active.json")
            return str(final)
        self._job("update", update)

    def close(self):
        self._chat_search.close()
        self.piManagement.cancelInstall()
        if self._closing:
            return
        self._closing = True
        self._desktop_plugins.close()
        self._appearance_save.stop()
        self._streaming_timer.stop()
        self._session_preview.cancel()
        self._chat_model.close()
        self._document_preview.close()
        self._subagents.close()
        self._proxy_usage_timer.stop()
        self._pool.close()
        if self.public_server:
            self.public_server.close()
        self._sync_proxy_usage()
        try:
            self.store.save()
        except (OSError, RuntimeError):
            pass  # Closing must still release the private listener and adapters.
        self._created_proxy_key = {}
        self.private_server.close()
        self._provider_plugins.close()
        if hasattr(self.adapter, "close"):
            self.adapter.close()
