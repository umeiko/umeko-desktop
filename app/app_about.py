"""Background release checks and verified downloads of public application updates."""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from datetime import datetime

from pathlib import Path
from PySide6.QtCore import QObject, Property, Signal, Slot, QUrl, QTimer, QStandardPaths
from PySide6.QtGui import QDesktopServices, QGuiApplication

from .project_info import VERSION, PROJECT_URL, AUTHOR_URL, RELEASES_URL, RELEASE_API, project_info
from .update_download import platform_target, select_asset, download_asset


def version_key(value):
    match = re.fullmatch(r"[vV]?(0|[1-9]\d*)\.(0|[1-9]\d*)(?:\.(0|[1-9]\d*))?(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?", str(value), re.ASCII)
    if not match:
        return None
    major, minor, patch, pre = match.groups()
    prerelease = tuple((0, int(part)) if part.isdigit() else (1, part) for part in pre.split(".")) if pre else ()
    return int(major), int(minor), int(patch or 0), 0 if pre else 1, prerelease


def fetch_latest_release():
    request = urllib.request.Request(RELEASE_API, headers={
        "Accept": "application/vnd.github+json", "User-Agent": "Umeko/" + VERSION,
        "X-GitHub-Api-Version": "2026-03-10",
    })
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError("Oversized release metadata")
        data = json.loads(raw)
        if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
            raise ValueError("Expected a published stable release")
        tag = str(data.get("tag_name", ""))
        latest = version_key(tag)
        if not tag:
            raise ValueError("Missing release tag")
        url = str(data.get("html_url", ""))
        if not url.startswith(PROJECT_URL + "/releases/tag/"):
            url = RELEASES_URL
        if latest is None:
            state, message = "unknown", "发现发布版本 " + tag + "，请前往发布页确认。"
        elif latest > version_key(VERSION):
            state, message = "available", "发现新版本 " + tag
        elif latest == version_key(VERSION):
            state, message = "current", "当前已是最新正式版本。"
        else:
            state, message = "ahead", "当前构建版本高于最新正式版（" + tag + "）。"
        return {"state": state, "message": message, "version": tag, "url": url, "notes": str(data.get("body") or ""),
                "asset": select_asset(data, PROJECT_URL, platform_target())}
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return {"state": "unpublished", "message": "项目暂未发布正式版本，可前往 GitHub 发布页查看。"}
        if error.code in (403, 429):
            return {"state": "error", "message": "GitHub 请求受限，请稍后重试。"}
        return {"state": "error", "message": "GitHub 暂时无法提供版本信息，请稍后重试。"}
    except (OSError, ValueError):
        return {"state": "error", "message": "检查失败，请检查网络后重试，或直接查看 GitHub 发布页。"}


class AppAbout(QObject):
    changed = Signal()
    downloadProgress = Signal(int)

    def __init__(self, controller):
        super().__init__(controller)
        self.controller = controller
        self._info = project_info(controller.root)
        self._busy, self._release, self._checked_at = False, {}, ""
        self._download = {}
        self._automatic = QTimer(self)
        self._automatic.setInterval(6*60*60*1000)
        self._automatic.timeout.connect(self.checkUpdates)
        self.downloadProgress.connect(self._progress)
        controller.jobDone.connect(self._finished)

    @Property("QVariantMap", constant=True)
    def info(self): return self._info

    @Property(bool, notify=changed)
    def busy(self): return self._busy

    @Property("QVariantMap", notify=changed)
    def release(self): return self._release

    @Property(str, notify=changed)
    def checkedAt(self): return self._checked_at

    @Property('QVariantMap', notify=changed)
    def download(self): return self._download

    @Slot()
    def startAutomaticChecks(self):
        if self._automatic.isActive(): return
        self._automatic.start()
        QTimer.singleShot(5000, self, self.checkUpdates)

    @Slot()
    def checkUpdates(self):
        if self._busy or self._download.get('state') == 'downloading': return
        self._busy = True
        if self._release.get('state') != 'available':
            self._release = {"state": "checking", "message": "正在检查 GitHub 最新正式版本…"}
        self.changed.emit()
        self.controller._job("app-update-check", fetch_latest_release)

    def _finished(self, name, result):
        if name == 'app-update-download' and not self.controller._closing:
            self._download = ({'state':'ready', 'path':result['value'], 'progress':100, 'message':'更新包已下载'}
                              if result['ok'] else {'state':'error', 'message':'下载失败，请检查网络后重试'})
            self.changed.emit()
            self.controller.toast.emit(self._download['message'])
            return
        if name != "app-update-check" or self.controller._closing: return
        self._busy = False
        incoming = result["value"] if result["ok"] else {"state": "error", "message": "检查失败，请稍后重试。"}
        if incoming.get('state') != 'error' and incoming.get('asset', {}).get('name') != self._release.get('asset', {}).get('name'):
            self._download = {}
        if incoming.get('state') != 'error' or self._release.get('state') != 'available': self._release = incoming
        self._checked_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
        self.changed.emit()

    @Slot(int)
    def _progress(self, value):
        if self.controller._closing or self._download.get('state') != 'downloading': return
        self._download = {**self._download, 'progress':value}
        self.changed.emit()

    @Slot()
    def downloadUpdate(self):
        if self._busy or self._download.get('state') == 'downloading': return
        asset = self._release.get('asset')
        if not asset:
            self.controller.toast.emit('该版本没有适合当前平台的更新包，请查看发布页')
            return
        self._download = {'state':'downloading', 'progress':0, 'name':asset['name'], 'message':'正在下载更新包…'}
        self.changed.emit()
        directory = Path(QStandardPaths.writableLocation(QStandardPaths.DownloadLocation) or Path.home()/'Downloads')/'Umeko'
        self.controller._job('app-update-download', lambda: download_asset(asset, directory, self.downloadProgress.emit, lambda:self.controller._closing))

    @Slot()
    def showDownloadedUpdate(self):
        if self._download.get('state') == 'ready':
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self._download['path']).parent)))

    @Slot()
    def openProject(self): QDesktopServices.openUrl(QUrl(PROJECT_URL))

    @Slot()
    def openAuthor(self): QDesktopServices.openUrl(QUrl(AUTHOR_URL))

    @Slot()
    def openReleases(self): QDesktopServices.openUrl(QUrl(self._release.get("url", RELEASES_URL)))

    @Slot()
    def copyInfo(self):
        info = self._info
        QGuiApplication.clipboard().setText("\n".join([
            info["name"] + " v" + info["version"], "作者：" + info["author"], info["projectUrl"],
            "构建平台：" + info["buildPlatform"], "构建类型：" + info["buildType"],
            "构建时间：" + info["builtAt"], "提交：" + info["commit"] + ("（含未提交修改）" if info["dirty"] else ""),
        ]))
        self.controller.toast.emit("已复制项目信息")
