"""Native Windows capsule activation/IMM, with explicitly synthetic composition.

No keyboard layout changes or global input injection. This does not validate an
installed Chinese IME or its candidate UI. Only the CI desktop may run it.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
NATIVE_CI = (sys.platform == 'win32' and os.environ.get('GITHUB_ACTIONS') == 'true'
             and os.environ.get('RUNNER_OS') == 'Windows'
             and os.environ.get('UMEKO_NATIVE_PET_INPUT_TEST') == '1')


def run_native():
    if not NATIVE_CI:
        raise RuntimeError('Requires explicitly enabled Windows CI desktop')
    import ctypes
    from ctypes import wintypes
    from unittest.mock import Mock
    folder = tempfile.TemporaryDirectory(prefix='umeko-native-pet-input-')
    os.environ.update(UMEKO_DATA_DIR=folder.name + '/profile',
                      PI_CODING_AGENT_DIR=folder.name + '/agent',
                      QT_QPA_PLATFORM='windows', QT_QUICK_BACKEND='software',
                      UMEKO_LANGUAGE='zh')
    sys.path.insert(0, str(ROOT))
    from PySide6.QtCore import QObject, Qt
    from PySide6.QtGui import QGuiApplication, QInputMethodEvent
    from PySide6.QtQml import QQmlEngine, QQmlExpression
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QSystemTrayIcon
    QSystemTrayIcon.show = lambda *args: None
    from main import create_application
    import shiboken6

    user = ctypes.WinDLL('user32', use_last_error=True)
    user.GetForegroundWindow.argtypes = []
    user.GetForegroundWindow.restype = wintypes.HWND
    imm = ctypes.WinDLL('imm32', use_last_error=True)
    imm.ImmGetContext.argtypes = [wintypes.HWND]
    imm.ImmGetContext.restype = wintypes.HANDLE
    imm.ImmReleaseContext.argtypes = [wintypes.HWND, wintypes.HANDLE]
    imm.ImmReleaseContext.restype = wintypes.BOOL
    out = ROOT / 'build/native-pet-input'
    out.mkdir(parents=True, exist_ok=True)
    evidence = {'osImeVerified': False, 'compositionMechanism': 'synthetic QInputMethodEvent',
                'doubleClickMechanism': 'QTest to application-owned pet window', 'snapshots': []}
    try:
        app, engine, backend = create_application()
    except Exception as error:
        evidence.update(status='launch_failed', error=str(error))
        (out / 'result.json').write_text(json.dumps(evidence), encoding='utf-8')
        folder.cleanup()
        raise
    main = engine.rootObjects()[0]
    command = Mock(return_value=True)
    backend._command_pi = command
    native = None

    def wait(predicate, message):
        for _ in range(250):
            if predicate():
                return
            QTest.qWait(20)
        raise AssertionError(message)

    def js(obj, code):
        query = QQmlExpression(QQmlEngine.contextForObject(obj), obj, code)
        result = query.evaluate()[0]
        assert not query.hasError(), query.error().toString()
        return result

    try:
        assert app.platformName() == 'windows'
        # Establish whether this runner can foreground any window of this app.
        # Never force the capsule foreground: that is the behavior under test.
        main.requestActivate()
        evidence['phase'] = 'runner_foreground_precondition'
        wait(lambda: int(user.GetForegroundWindow() or 0) == int(main.winId()),
             'Runner cannot foreground the main window; native capability unavailable')
        evidence['mainForegroundAvailable'] = True
        evidence['phase'] = 'capsule_test'
        pet = backend.desktopPlugins.pet
        pet.ui('show', {})
        wait(lambda: pet.assistantStatus.get('bound'), 'Companion not bound')
        petwindow = main.findChild(QObject, 'desktopPetWindow')
        wait(lambda: petwindow and petwindow.mask().boundingRect().height() > 50, 'Pet not loaded')
        composer = petwindow.findChild(QObject, 'desktopPetTaskComposer')
        field = composer.findChild(QObject, 'desktopPetTaskInput')
        before_view = backend._view
        before_view.draft = '主窗口合成草稿'
        identifier = pet.assistantStatus['id']
        backend.desktopPlugins.global_agents.ensure(identifier)
        for cycle in range(2):
            QTest.mouseDClick(petwindow, Qt.LeftButton, Qt.NoModifier,
                              petwindow.mask().boundingRect().center())
            wait(lambda: composer.property('opened'), 'Double-click did not open capsule')
            native = js(composer, 'contentItem.Window.window')
            hwnd = int(native.winId())
            wait(lambda: (QGuiApplication.focusWindow() is native
                          and QGuiApplication.focusObject() is field
                          and int(user.GetForegroundWindow() or 0) == hwnd),
                 'Capsule did not obtain native foreground and Qt editor focus')
            assert bool(QGuiApplication.inputMethod().queryFocusObject(Qt.ImEnabled, None))
            context = imm.ImmGetContext(hwnd)
            assert context, 'Capsule HWND has no IMM context'
            assert imm.ImmReleaseContext(hwnd, context), 'IMM context release failed'
            evidence['snapshots'].append({'cycle': cycle, 'foregroundMatchesCapsule': True,
                                           'qtEditorFocused': True, 'immContextPresent': True})
            def snapshot(label):
                evidence['phase'] = label
                evidence.setdefault('editorEvents', []).append({
                    'order': len(evidence.get('editorEvents', [])), 'cycle': cycle,
                    'phase': label, 'text': field.property('text'),
                    'cursor': field.property('cursorPosition'),
                    'selectionStart': field.property('selectionStart'),
                    'selectionEnd': field.property('selectionEnd'),
                    'composing': field.property('inputMethodComposing'),
                    'dispatchCount': command.call_count})

            # Real Windows input context may consume an actual IME Enter. A
            # QTest key bypasses that path and can insert a paragraph separator.
            # Test its no-dispatch guard separately from exact synthetic commit.
            field.setProperty('text', '')
            snapshot('guard-before-preedit')
            QGuiApplication.sendEvent(native, QInputMethodEvent('合成预编辑', []))
            wait(lambda: field.property('inputMethodComposing'), 'Synthetic preedit not delivered')
            snapshot('guard-preedit-delivered')
            count = command.call_count
            QTest.keyClick(native, Qt.Key_Return)
            snapshot('guard-after-qtest-enter')
            assert command.call_count == count, 'Preedit Enter dispatched a task'
            assert composer.property('visible'), 'Preedit Enter closed the capsule'
            assert field.property('inputMethodComposing'), 'QTest Enter unexpectedly ended synthetic preedit'
            QGuiApplication.sendEvent(native, QInputMethodEvent('', []))
            wait(lambda: not field.property('inputMethodComposing'), 'Synthetic cancellation not delivered')
            snapshot('guard-after-synthetic-cancel')

            # Fresh composition without an intervening key: exact committed text
            # remains a strict assertion, not stripped/normalized or weakened.
            field.setProperty('text', '')
            field.setProperty('cursorPosition', 0)
            snapshot('commit-clean-editor')
            QGuiApplication.sendEvent(native, QInputMethodEvent('合成预编辑', []))
            wait(lambda: field.property('inputMethodComposing'), 'Commit preedit not delivered')
            snapshot('commit-preedit-delivered')
            event = QInputMethodEvent()
            event.setCommitString('中文合成测试')
            QGuiApplication.sendEvent(native, event)
            wait(lambda: not field.property('inputMethodComposing'), 'Synthetic commit not delivered')
            snapshot('commit-delivered-without-key')
            assert field.property('text') == '中文合成测试', repr(field.property('text'))
            assert native.grabWindow().save(str(out / f'capsule-{cycle}.png'))
            QTest.keyClick(native, Qt.Key_Return)
            wait(lambda: not composer.property('visible'), 'Explicit Enter did not close capsule')
            assert command.call_count == count + 1, 'Task not dispatched exactly once'
            assert command.call_args.kwargs['text'] == '(input from pet)\n中文合成测试'
            assert backend._view is before_view and before_view.draft == '主窗口合成草稿'
            assert pet.assistantStatus['id'] == identifier
            QTest.qWait(150)
        evidence['status'] = 'passed'
    except Exception as error:
        evidence['status'] = 'failed'
        evidence['error'] = str(error)
        evidence['foregroundHwnd'] = int(user.GetForegroundWindow() or 0)
        if native is not None:
            evidence['capsuleHwnd'] = int(native.winId())
            native.grabWindow().save(str(out / 'failure-capsule.png'))
        raise
    finally:
        (out / 'result.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
        print('NATIVE_PET_INPUT ' + json.dumps(evidence, ensure_ascii=False), flush=True)
        try:
            backend.close()
        finally:
            try:
                shiboken6.delete(engine)
                app.processEvents()
            finally:
                folder.cleanup()


class WindowsPetInputTests(unittest.TestCase):
    @unittest.skipUnless(NATIVE_CI, 'Requires explicitly enabled Windows CI desktop; not OS IME acceptance')
    def test_native_capsule_focus_context_and_synthetic_commit(self):
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--native'],
                                cwd=ROOT, env=dict(os.environ), capture_output=True,
                                text=True, encoding='utf-8', errors='replace', timeout=90)
        print(result.stdout, end='', flush=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    if '--native' in sys.argv:
        run_native()
    else:
        unittest.main()
