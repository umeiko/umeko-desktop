"""Run built-in Quick OCR through the normal chat, without Pi or model traffic."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
from tempfile import mkdtemp
import time
import uuid

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, QUrl

from .message_attachments import attachment_prompt
from .quick_ocr_component import cleaned_env, interpreter, paths, ready


IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.bmp', '.webp', '.tif', '.tiff'}
ENGINE_ZH = '快速 OCR 在本机使用 RapidOCR 3.10.0 + PP-OCRv6 small（ONNX Runtime CPU），不调用云端模型。'
ENGINE_EN = 'Quick OCR uses RapidOCR 3.10.0 + PP-OCRv6 small (ONNX Runtime CPU) locally. It does not call a cloud model.'


class QuickOcr(QObject):
    def __init__(self, backend):
        super().__init__(backend)
        self.b = backend
        self.root = backend.root
        self.component = backend.store.directory.resolve() / 'quick-ocr'
        try:
            self.spec, self.fingerprint, self.target = paths(self.root, self.component)
        except (OSError, ValueError, KeyError):
            self.spec, self.fingerprint, self.target = None, "", self.component / "unavailable"
        self.asset_cache = None  # A test may supply identical, hash-checked original assets.
        self.installer = None
        self.preparation = None
        self.pending = {}
        self.active = None
        self.closed = False
        self.timeout = QTimer(self, singleShot=True, interval=45_000)
        self.timeout.timeout.connect(lambda: self._cancel_worker('识别超时。', 'Recognition timed out.'))

    def applies(self, record):
        return bool(record and self.b.cowork.profiles.get(record.cowork, {}).get('typeId') == 'ocr')

    def t(self, zh, en):
        return en if self.b.language == 'en' else zh

    def on_view(self, record):
        if self.applies(record):
            self.prepare()

    def _process(self, command, args, *, external=False):
        process = QProcess(self)
        process.setProgram(command)
        process.setArguments(list(args))
        process.setWorkingDirectory(str(self.root))
        process.setStandardInputFile(QProcess.nullDevice())
        env = QProcessEnvironment.systemEnvironment()
        if external:
            env = QProcessEnvironment()
            for key, value in cleaned_env().items():
                env.insert(key, value)
        elif getattr(sys, 'frozen', False):
            env.insert('PYINSTALLER_RESET_ENVIRONMENT', '1')
        process.setProcessEnvironment(env)
        return process

    def prepare(self):
        if self.closed or self.spec is None or self.installer or ready(self.target, self.fingerprint):
            return
        try:
            self.component.mkdir(exist_ok=True)
            stage = Path(mkdtemp(prefix='.prepare-', dir=self.component))
            (stage / 'requested').write_text(stage.name, encoding='ascii')
        except OSError:
            return
        self.preparation = stage
        arguments = ['--umeko-quick-ocr-install', str(stage)]
        if self.asset_cache is not None:
            arguments += ['--asset-cache', str(self.asset_cache)]
        if not getattr(sys, 'frozen', False):
            arguments.insert(0, str(self.root / 'main.py'))
        process = self._process(sys.executable, arguments)
        self.installer = process
        process.finished.connect(lambda code, _status: self._installed(process, code))
        process.errorOccurred.connect(lambda error: self._installed(process, 1) if error == QProcess.ProcessError.FailedToStart else None)
        process.start()

    def _installed(self, process, code):
        if process is not self.installer:
            return
        self.installer = None
        self.preparation = None
        if code and sys.stderr:
            diagnostic = bytes(process.readAllStandardError())[:240].decode('ascii', errors='replace').strip()
            if diagnostic:
                print(diagnostic, file=sys.stderr, flush=True)
        process.deleteLater()
        if self.closed:
            return
        if not ready(self.target, self.fingerprint):
            for key in list(self.pending):
                self._reply(key, self.t('快速 OCR 组件准备失败。请检查网络和磁盘空间，重新发送图片可重试。',
                                        'Quick OCR setup failed. Check network access and disk space, then resend the image to retry.'))
        else:
            self._pump()

    @staticmethod
    def attachment(url):
        path = Path(QUrl(url).toLocalFile()).resolve(strict=True)
        if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES or any(ch in str(path) for ch in '\r\n'):
            return None
        if path.stat().st_size > 20 * 1024 * 1024:
            return None
        return {'id': uuid.uuid4().hex, 'name': path.name, 'kind': 'image', 'path': str(path),
                'preview': QUrl.fromLocalFile(str(path)).toString()}

    @staticmethod
    def _file_identity(path):
        stat = path.stat()
        return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns

    def send(self, record, text):
        if self.closed or record.busy:
            return False
        message = text.strip()
        attachments = record.attachments
        if not attachments and not message:
            return False
        if len(attachments) > 1:
            self.b.toast.emit(self.t('快速 OCR 一次只处理一张图片。', 'Quick OCR accepts one image per message.'))
            return False
        file = Path(attachments[0]['path']) if attachments else None
        identity = None
        if file:
            try:
                identity = self._file_identity(file)
            except OSError:
                pass
        now = datetime.now(timezone.utc)
        if not record.file:
            record.id = str(uuid.uuid4())
            parent = self.b.cowork.session_directory(record.cowork)
            record.file = str(parent / (record.id + '.jsonl'))
            record.title = (message or file.name)[:80]
            if self.b.language == 'zh' and not message and file is None:
                record.title = '快速 OCR'
            try:
                parent.mkdir(parents=True, exist_ok=True)
                with Path(record.file).open('x', encoding='utf-8') as stream:
                    stream.write(json.dumps({'type': 'session', 'version': 3, 'id': record.id,
                                             'timestamp': now.isoformat(), 'cwd': record.workspace}) + '\n')
            except OSError:
                record.id, record.file = '', ''
                self.b.toast.emit(self.t('无法保存快速 OCR 会话。', 'Cannot save the Quick OCR conversation.'))
                return False
        if not self._append(record, 'user', attachment_prompt(message, attachments)):
            return False
        record.attachments, record.draft = [], ''
        self.b._index_record(record)
        self.b._save_session(record)
        self.b.cowork.refresh_rows()
        self.b.attachmentsChanged.emit()
        self.b.editorText.emit('')
        self.pending[record.key] = (record, file, identity)
        record.phase = 'running'
        record.action = 'quick-ocr'
        record.prompt_started = time.monotonic()
        record.cancelled = False
        if not file:
            engine_question = re.search(r'(什么.*(模型|引擎)|((模型|引擎).*(什么|哪个))|用的.*什么|\b(model|engine|rapidocr)\b)', message, re.I)
            if engine_question:
                info = self.t(ENGINE_ZH, ENGINE_EN)
                if self.spec is None:
                    info += self.t(' 此平台暂无可用组件。', ' The optional component is not available on this platform.')
                elif not ready(self.target, self.fingerprint):
                    info += self.t(' 组件尚未就绪。', ' The component is not ready yet.')
                self._reply(record.key, info)
            else:
                self._reply(record.key, self.t('请附上一张本地图片，再在本对话里发送。', 'Attach a local image and send it in this conversation.'))
            return True
        if identity is None:
            self._reply(record.key, self.t('原图片已移动或不能读取。', 'The original image was moved or is unreadable.'))
        elif self.spec is None:
            self._reply(record.key, self.t('此平台暂不支持本地快速 OCR，图片未上传。', 'Local Quick OCR is unavailable on this platform. The image was not uploaded.'))
        elif ready(self.target, self.fingerprint):
            self._pump()
        else:
            self.prepare()
            if self.installer is not None:
                record.tool_status = self.t('正在下载和准备快速 OCR 组件…', 'Downloading and preparing Quick OCR…')
                self._changed(record)
            else:
                self._reply(record.key, self.t('无法准备快速 OCR 组件，重新发送可重试。', 'Quick OCR setup could not start. Resend to retry.'))
        return True

    def _append(self, record, role, text, *, stopped=False):
        identifier = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc)
        message = {'role': role, 'content': [{'type': 'text', 'text': text}], 'timestamp': int(now.timestamp() * 1000)}
        if role == 'assistant':
            message.update(api='openai-completions', provider='local', model='quick-ocr',
                           usage={'input':0,'output':0,'cacheRead':0,'cacheWrite':0,'totalTokens':0,
                                  'cost':{'input':0,'output':0,'cacheRead':0,'cacheWrite':0,'total':0}},
                           stopReason='aborted' if stopped else 'stop')
        parent_id = record.tree[-1]['id'] if record.tree else (record.transcript.leaf if record.transcript else None)
        entry = {'type': 'message', 'id': identifier, 'parentId': parent_id or None,
                 'timestamp': now.isoformat(), 'message': message}
        try:
            with Path(record.file).open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(entry, ensure_ascii=False) + '\n')
        except OSError:
            self.b.toast.emit(self.t('无法保存快速 OCR 消息。', 'Cannot save the Quick OCR message.'))
            return False
        record.tree.append({'id': identifier, 'role': role, 'text': text[:80]})
        record.projection_dirty_from = len(record.messages)
        record.messages.append({'role': role, 'text': text, 'entryId': identifier, 'timestamp': message['timestamp'],
                                **({'stopReason': message['stopReason'], 'plainText': True} if role == 'assistant' else {})})
        return True

    def _changed(self, record):
        if record is self.b._view and not self.closed:
            self.b._update_chat_model()
            self.b.chatChanged.emit()

    def _pump(self):
        if self.closed or self.active or not self.pending:
            return
        key = next(iter(self.pending))
        record, file, identity = self.pending[key]
        try:
            if self._file_identity(file) != identity:
                raise OSError
        except OSError:
            self._reply(key, self.t('原图片已移动或变更，请重新附加。', 'The original image moved or changed. Attach it again.'))
            return
        worker = self.root / 'app/quick_ocr_worker.py'
        process = self._process(str(interpreter(self.target)), ['-I', str(worker), str(self.target/'site'), str(file), '0'], external=True)
        self.active = (key, process)
        record.tool_status = self.t('正在本地识别图片…', 'Recognizing the image locally…')
        self._changed(record)
        process.finished.connect(lambda code, _status: self._recognized(process, code))
        process.errorOccurred.connect(lambda error: self._recognized(process, 1) if error == QProcess.ProcessError.FailedToStart else None)
        process.start()
        self.timeout.start()

    def _recognized(self, process, code):
        if not self.active or process is not self.active[1]:
            return
        key, _ = self.active
        self.active = None
        self.timeout.stop()
        try:
            result = json.loads(bytes(process.readAllStandardOutput())) if not code else {}
        except (ValueError, UnicodeError):
            result = {}
        process.deleteLater()
        record, file, identity = self.pending[key]
        try:
            if self._file_identity(file) != identity:
                raise OSError
        except OSError:
            self._reply(key, self.t('原图片已移动或变更，请重新附加。', 'The original image moved or changed. Attach it again.'))
            return
        if result.get('ok') and isinstance(result.get('text'), str):
            text = result['text'] or self.t('未识别到可读文字。', 'No readable text was found.')
            if result.get('truncated'):
                text += self.t('\n\n（达到输出上限，内容已截断。）', '\n\n(Output was truncated.)')
        else:
            text = self.t('本地识别失败。请检查图片格式，重新发送可重试。',
                          'Local recognition failed. Check the image format and resend to retry.')
        self._reply(key, text)

    def _reply(self, key, text, *, stopped=False):
        entry = self.pending.pop(key, None)
        if not entry:
            return
        record, _file, _identity = entry
        self._append(record, 'assistant', text, stopped=stopped)
        record.phase, record.action, record.tool_status = 'idle', '', ''
        record.prompt_started = None
        self._changed(record)
        if not self.closed and self.pending and ready(self.target, self.fingerprint):
            QTimer.singleShot(0, self._pump)

    def _cancel_worker(self, zh, en):
        if not self.active:
            return
        key, process = self.active
        self.active = None
        self.timeout.stop()
        process.kill()
        process.waitForFinished(2500)
        process.deleteLater()
        if not self.closed:
            self._reply(key, self.t(zh, en), stopped=True)

    def stop(self, record):
        if self.active and self.active[0] == record.key:
            self._cancel_worker('已取消本次识别。', 'Recognition canceled.')
        elif record.key in self.pending:
            self._reply(record.key, self.t('已取消本次识别。组件仍会在后台准备。', 'Recognition canceled. Component setup continues in the background.'), stopped=True)

    def close(self):
        self.closed = True
        self._cancel_worker('', '')
        for key in list(self.pending):
            self._reply(key, self.t('应用已关闭，本次识别已取消。', 'Recognition canceled when the app closed.'), stopped=True)
        if self.installer:
            process, stage = self.installer, self.preparation
            try:
                (stage / 'cancel').touch(exist_ok=True)
            except OSError:
                pass
            if not process.waitForFinished(15_500):
                process.kill()
                process.waitForFinished(1500)
