"""Run the real standalone installer UI and worker with isolated tiny bundles."""
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
import zipfile
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
os.environ.setdefault('QT_QUICK_CONTROLS_STYLE', 'Basic')
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow
from PySide6.QtTest import QTest
from app.update import UpdateInstaller

app = QGuiApplication([])
app.setQuitOnLastWindowClosed(False)

def run_case(bad_hash):
    with tempfile.TemporaryDirectory(prefix='umeko-installer-ui-') as temp:
        base = Path(temp); target = base / 'installed'; target.mkdir()
        exe = 'Umeko.exe' if os.name == 'nt' else 'Umeko'
        executable = target / exe; executable.write_bytes(b'old app')
        archive = base / 'update.zip'
        metadata = dict(version='0.3.0',system=platform.system(),architecture=platform.machine())
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
            for name, body in {exe:b'new app', '_internal/build-info.json':json.dumps(metadata).encode(),
                              '_internal/runtime/update-engine.mjs':b'// worker',
                              '_internal/runtime/node/' + ('node.exe' if os.name == 'nt' else 'bin/node'):b'node'}.items():
                z.writestr('Umeko/' + name, body)
        # A reaped PID makes the wait deterministic, without signalling any process.
        child = subprocess.Popen([sys.executable, '-c', 'pass']); child.wait()
        job = dict(installDir=str(target),executable=str(executable),archive=str(archive),
                   sha256='0'*64 if bad_hash else hashlib.sha256(archive.read_bytes()).hexdigest(),
                   version='v0.3.0',payloadRelative='Umeko',resourceRelative='_internal',parentPid=child.pid)
        job_file = base / 'job.json'; job_file.write_text(json.dumps(job))
        Path(str(job_file)+'.commit').write_text('{}')
        installer = UpdateInstaller(ROOT, str(job_file))
        engine = QQmlApplicationEngine(); warnings = []
        engine.warnings.connect(lambda errors: warnings.extend(str(e) for e in errors))
        engine.rootContext().setContextProperty('installer', installer)
        engine.load(QUrl.fromLocalFile(str(ROOT / 'app/qml/Installer.qml')))
        assert engine.rootObjects()
        window = engine.rootObjects()[0]
        QTest.qWait(100)
        def find(name):
            stack=[window.contentItem()]
            while stack:
                item=stack.pop()
                if item.objectName()==name:return item
                stack.extend(item.childItems())
            raise AssertionError(name)
        assert find('installerMascot').property('source').toString().endswith('yanami-installing.png')
        assert not window.close(), 'Closing during installation must be blocked'
        installer.begin()
        for _ in range(500):
            QTest.qWait(20)
            if installer.status['state'] in ('complete','error'): break
        assert installer.status['state'] == ('error' if bad_hash else 'complete'), installer.status
        assert find('installerMascot').property('source').toString().endswith('yanami-installer.png')
        assert Path(str(job_file)+'.ready').is_file()
        assert executable.read_bytes() == (b'old app' if bad_hash else b'new app')
        if not bad_hash:
            QTest.qWait(100)
            out = ROOT / 'artifacts/screenshots'; out.mkdir(parents=True, exist_ok=True)
            assert window.grabWindow().save(str(out/'installer-complete.png'))
            assert (base / 'job.json.result').is_file()
            if sys.platform == 'linux':
                # Finish launches the actual installed executable and exits the helper.
                launched = base / 'launched'
                executable.write_text('#!/bin/sh\nprintf launched > ' + str(launched) + '\n')
                executable.chmod(0o755)
                with patch('app.update.QGuiApplication.instance') as application:
                    installer.finish()
                    application.return_value.quit.assert_called_once()
                for _ in range(100):
                    QTest.qWait(10)
                    if launched.exists(): break
                assert launched.read_text() == 'launched'
        assert not warnings, warnings
        assert window.close()
        import shiboken6
        shiboken6.delete(engine)

run_case(False)
run_case(True)
print('INSTALLER_UI_OK: independent UI, worker handshake, ZIP installation, SHA failure, close protection, progress and completion')
