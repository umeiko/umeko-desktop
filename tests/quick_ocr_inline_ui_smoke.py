"""Real Qt composer + local Quick OCR. Pass an isolated evidence directory."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.update(QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software')

from PySide6.QtCore import QPoint, QProcess, QUrl, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtTest import QTest
from app.quick_ocr_component import ready
from main import create_application


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_photo(path):
    photo = QImage(1150, 410, QImage.Format_RGB32)
    photo.fill(QColor('white'))
    painter = QPainter(photo)
    painter.setPen(QColor('#151522'))
    painter.setFont(QFont('Noto Sans CJK SC', 38))
    painter.drawText(QPoint(50, 100), '快速识别验收')
    painter.drawText(QPoint(50, 205), '订单编号：A12345')
    painter.drawText(QPoint(50, 310), '应付金额：128.50元')
    painter.end()
    assert photo.save(str(path))


def test(args):
    output = args.evidence.resolve()
    output.mkdir(parents=True, exist_ok=True)
    data = output / 'profile'
    if args.mode != 'reuse':
        assert not data.exists(), 'First-run tests require a fresh evidence directory'
    os.environ.update(UMEKO_DATA_DIR=str(data), PI_CODING_AGENT_DIR=str(output / 'agent'))
    app, engine, backend = create_application()
    window = engine.rootObjects()[0]
    window.resize(1280, 820)
    backend.setLanguage('zh')
    ocr = backend._quick_ocr
    ocr.asset_cache = args.asset_cache
    cowork = backend.cowork

    def wait(condition, label, timeout=18):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            QTest.qWait(30)
            if condition():
                return
        raise AssertionError(label)

    def find(name):
        pending = [window.contentItem()]
        hidden = None
        while pending:
            row = pending.pop()
            if row.objectName() == name:
                if row.isVisible():
                    return row
                hidden = row
            pending.extend(row.childItems())
        return hidden

    def text_lines(text):
        pending = [window.contentItem()]
        while pending:
            row = pending.pop()
            if row.isVisible() and row.property('text') == text and row.property('lineCount') == 3:
                return True
            pending.extend(row.childItems())
        return False

    def click(name):
        wait(lambda: find(name) and find(name).isVisible() and find(name).isEnabled(), name)
        row = find(name)
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, row.mapToScene(row.boundingRect().center()).toPoint())

    def send(text='', photo=None):
        if photo is not None:
            assert backend.addAttachments(json.dumps([QUrl.fromLocalFile(str(photo)).toString()]))
            assert 'data' not in backend._view.attachments[0]
        find('promptInput').setProperty('text', text)
        click('sendButton')

    def done(record, description, timeout=25):
        wait(lambda: not record.busy and record.messages and record.messages[-1]['role'] == 'assistant', description, timeout)
        return record.messages[-1]['text']

    def screenshot(filename):
        QTest.mouseMove(window, QPoint(360, 120))
        QTest.qWait(360)
        assert window.grabWindow().save(str(output / filename))

    photo = output / '原始图片.png'
    if args.mode != 'reuse':
        make_photo(photo)
    original = digest(photo)
    try:
        if args.mode != 'reuse':
            assert not ready(ocr.target, ocr.fingerprint)
            assert backend.saveDesktopSettings('{"coworkEnabled":true}')
        with patch.object(backend, '_start_pi', side_effect=AssertionError('OCR unexpectedly started Pi')):
            click('openCoworkButton')
            if args.mode != 'reuse':
                click('coworkCard_ocr')
                click('coworkInstanceConfirm')
            wait(lambda: backend.localQuickOcr, 'local OCR route')
            record = backend._view
            assert not find('modelSelector').isVisible()
            assert not find('composerPermissionStatus').isVisible()
            if args.mode == 'reuse':
                wait(lambda: record.transcript and backend.messageCount >= 4, 'OCR transcript reopened')
                prior = record.transcript.count
                assert ready(ocr.target, ocr.fingerprint) and ocr.installer is None
                send('再识别一次', photo)
                assert 'A12345' in done(record, 'recognition using existing component')
                assert ocr.installer is None and backend.messageCount >= prior + 2
                snapshot = backend.transcripts.open(record.file)
                assert snapshot.count >= prior + 2
                assert any('RapidOCR' in row.get('text', '') for row in snapshot.page(0).values())
                print('QUICK_OCR_RESTART_REUSED_AND_RECOGNIZED', flush=True)
                return
            # A rejected fixture can already have finished before Qt lays out the view.
            if args.mode != 'retry':
                wait(lambda: ocr.installer is not None, 'background setup started when choosing role')
            send('提取这张原图中的文字', photo)
            wait(lambda: find('userAttachment_0_0') is not None, 'original image chip in the existing chat')
            if args.mode == 'close-pending':
                stage = ocr.preparation
                assert stage is not None and record.busy
                process = ocr.installer
                backend.close()
                assert process.state() == QProcess.ProcessState.NotRunning and not stage.exists()
                assert not ready(ocr.target, ocr.fingerprint)
                assert not record.busy and '本次识别已取消' in record.messages[-1]['text']
                print('QUICK_OCR_CLOSE_PENDING_CLEAN', flush=True)
                return
            if args.mode in ('online', 'cache'):
                wait(lambda: '下载和准备' in (find('composerStatus').property('text') or ''), 'visible in-chat preparation')
                screenshot('quick-ocr-installing.png')
                result = done(record, 'local recognition after initial download', timeout=270)
                assert all(expected in result for expected in ('快速识别验收', 'A12345', '128.50')), result
                assert ready(ocr.target, ocr.fingerprint)
                wait(lambda: text_lines(result), 'recognition rendered in three visible lines')
                screenshot('quick-ocr-recognized.png')
                menu = find('copyMessage_1')
                assert menu is not None
                QTest.mouseMove(window, menu.mapToScene(menu.boundingRect().center()).toPoint())
                click('copyMessage_1')
                assert app.clipboard().text() == result
                send('你用的是什么 OCR 模型？')
                info = done(record, 'local model identity')
                assert 'PP-OCRv6 small' in info and 'RapidOCR 3.10.0' in info and '不调用云端' in info
                screenshot('quick-ocr-engine.png')
                assert record.messages[-1]['plainText']
                assert digest(photo) == original and Path(record.file).is_file()
                print(f'QUICK_OCR_{args.mode.upper()}_OK {record.id}: {result!r}', flush=True)
            elif args.mode == 'retry':
                assert args.retry_cache is not None
                first = done(record, 'missing or corrupted asset', timeout=40)
                assert '组件准备失败' in first and not ready(ocr.target, ocr.fingerprint)
                assert not list(ocr.component.glob('.prepare-*'))
                ocr.asset_cache = args.retry_cache
                send('本次识别取消测试', photo)
                assert record.busy
                click('sendButton')  # Same running composer action now means Stop.
                assert '已取消' in done(record, 'cancel during setup')
                assert not record.busy
                send('准备好后重新识别', photo)
                click('openCoworkButton')
                wait(lambda: backend._view is not record and not backend.localQuickOcr, 'switched away while waiting')
                assert 'A12345' in done(record, 'retry from verified cached assets', timeout=120)
                assert not any('A12345' in row['text'] for row in backend._view.messages)
                click('openCoworkButton')
                wait(lambda: backend._view is record, 'reopen original OCR conversation')
                assert ready(ocr.target, ocr.fingerprint) and digest(photo) == original
                assert sum(row['role']=='assistant' for row in record.messages) == 3
                print('QUICK_OCR_FAILURE_CANCEL_RETRY_OK', flush=True)
    finally:
        backend.close()
        window.close()
        QTest.qWait(100)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('online', 'cache', 'retry', 'reuse', 'close-pending'))
    parser.add_argument('evidence', type=Path)
    parser.add_argument('--asset-cache', type=Path)
    parser.add_argument('--retry-cache', type=Path)
    test(parser.parse_args())
