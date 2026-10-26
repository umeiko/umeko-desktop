"""Build the optional Linux engine ZIP, or stage only the tiny Qt WebView frontend."""
import argparse, hashlib, json, os, platform, shutil, sys, tempfile, urllib.request, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QT = '6.10.2'
FRONTEND_LAYOUT = 2
ID = 'qt-webengine-' + QT + '-linux-x64-v1'

def digest(file):
    sha = hashlib.sha256()
    with file.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''): sha.update(block)
    return sha.hexdigest()

def frontend(name):
    return ('QtWebView' in name or 'Qt6WebView' in name or 'WebView2Loader' in name or '/webview/' in name) and 'webengine' not in name.lower() and not any(x in name for x in ('/include/', '/lib/cmake/', '/metatypes/', '/typesystems/')) and not name.endswith(('.prl', '.pyi'))

def stage_frontend(output, qt_root=None):
    marker=output/'frontend-manifest.json'
    if not qt_root and marker.is_file():
        cached=json.loads(marker.read_text())
        if cached.get('layout')==FRONTEND_LAYOUT and cached.get('qt')==QT and cached.get('platform')==sys.platform and cached.get('files') and all((output/name).is_file() and digest(output/name)==sha for name,sha in cached['files'].items()): return
    def stamp():
        files={file.relative_to(output).as_posix():digest(file) for file in output.rglob('*') if file.is_file() and file!=marker}
        marker.write_text(json.dumps({'layout':FRONTEND_LAYOUT,'qt':QT,'platform':sys.platform,'files':files},sort_keys=True)+'\n')
    if output.exists(): shutil.rmtree(output)
    output.mkdir(parents=True)
    if qt_root:
        for prefix in ['lib', 'bin', 'qml', 'plugins']:
            for source in (qt_root / prefix).rglob('*'):
                name = source.relative_to(qt_root).as_posix()
                if source.is_file() and frontend('/' + name):
                    target = output / name; target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(source, target)
        stamp()
        return
    # Build dependency only: extract the WebView frontend rather than installing or shipping all Addons.
    metadata = json.load(urllib.request.urlopen('https://pypi.org/pypi/PySide6_Addons/' + QT + '/json', timeout=60))
    wheel_marker = 'win_amd64' if sys.platform == 'win32' else 'macosx_' if sys.platform == 'darwin' else 'manylinux_2_34_x86_64'
    wheel = next(item for item in metadata['urls'] if wheel_marker in item['filename'])
    with tempfile.TemporaryDirectory(prefix='umeko-webview-wheel-') as temporary:
        archive = Path(temporary) / wheel['filename']
        with urllib.request.urlopen(wheel['url'],timeout=60) as response, archive.open('wb') as stream: shutil.copyfileobj(response,stream)
        if digest(archive) != wheel['digests']['sha256']: raise RuntimeError('Qt wheel checksum mismatch')
        with zipfile.ZipFile(archive) as stream:
            for entry in stream.infolist():
                name = entry.filename
                if name.startswith('PySide6/Qt/'):
                    relative = name.removeprefix('PySide6/Qt/')
                elif sys.platform == 'win32' and name.startswith('PySide6/'):
                    # Windows wheels put qml/ and plugins/ directly in PySide6,
                    # alongside root DLLs. Preserve module metadata and paths.
                    relative = name.removeprefix('PySide6/')
                    if relative.startswith(('qml/', 'plugins/')): pass
                    elif '/' not in relative and relative.endswith('.dll'): relative = 'bin/' + relative
                    else: continue
                else: continue
                if frontend('/' + relative) and not entry.is_dir():
                    target = output / relative; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(stream.read(entry))
    stamp()

def strip_linux_engine(root):
    # Native Linux packages carry only the WebView frontend. Engine files live in the optional ZIP.
    for prefix in ['qml/QtWebEngine','qml/QtWebChannel','qml/QtPositioning','qml/QtWebSockets','qml/QtPdf','qml/QtQuick/Pdf','plugins/webview','translations/qtwebengine_locales']:
        shutil.rmtree(root/prefix,ignore_errors=True)
    for prefix, patterns in [('lib',['libQt6WebEngine*','libQt6WebChannel*','libQt6Positioning*','libQt6WebSockets*','libQt6Pdf*']),('libexec',['QtWebEngineProcess','webenginedriver']),('resources',['qtwebengine*','icudtl.dat','v8_context_snapshot.bin'])]:
        for pattern in patterns:
            for file in (root/prefix).glob(pattern):
                if file.is_file() or file.is_symlink(): file.unlink()
    if any((root/'lib').glob('libQt6WebEngine*')): raise RuntimeError('Engine leaked into base package')

def engine_package(qt_root, output, registry):
    if sys.platform != 'linux' or platform.machine() not in ('x86_64', 'AMD64'): raise RuntimeError('Build this component on Linux x64')
    files = {}
    # Qt base/Quick remain in the app. These are the engine-specific runtime dependencies.
    for module in ['WebEngineCore', 'WebEngineQuick', 'WebChannel', 'WebChannelQuick', 'Positioning', 'WebSockets', 'OpenGL', 'QuickWidgets', 'PrintSupport']:
        source = qt_root / ('lib/libQt6' + module + '.so.6')
        if source.exists(): files['lib/' + source.name] = source
    for prefix in ['qml/QtWebEngine', 'qml/QtWebChannel', 'qml/QtPositioning', 'qml/QtWebSockets', 'resources', 'translations/qtwebengine_locales']:
        for file in (qt_root / prefix).rglob('*'):
            if file.is_file() and file.suffix not in ('.prl', '.debug'): files[file.relative_to(qt_root).as_posix()] = file
    for name in ['libexec/QtWebEngineProcess', 'plugins/webview/libqtwebview_webengine.so']:
        source = qt_root / name
        if not source.exists(): raise RuntimeError('Missing Qt runtime: ' + str(source))
        files[name] = source
    licenses = ROOT / 'licenses'
    for file in licenses.rglob('*'):
        if file.is_file(): files['licenses/' + file.relative_to(licenses).as_posix()] = file
    for source in (qt_root/'sbom').glob('*.spdx.json'):
        if any(name in source.name for name in ('qtwebengine','qtwebview','qtwebchannel','qtpositioning','qtwebsockets')):
            files['licenses/Qt-SBOM/'+source.name]=source
    notice = ROOT / 'THIRD_PARTY_NOTICES.md'
    files['licenses/THIRD_PARTY_NOTICES.md'] = notice
    manifest = {'id':ID, 'qt':QT, 'platform':'linux-x64', 'files':{name:digest(file) for name,file in sorted(files.items())}}
    output.mkdir(parents=True, exist_ok=True)
    archive = output / ('Umeko-' + ID + '.zip')
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as stream:
        def entry(name, raw, executable=False):
            info=zipfile.ZipInfo(name, (2026,1,1,0,0,0));info.create_system=3;info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=(0o100755 if executable else 0o100644)<<16
            stream.writestr(info, raw, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        entry('manifest.json', (json.dumps(manifest,sort_keys=True,indent=2)+'\n').encode())
        for name,file in sorted(files.items()): entry(name,file.read_bytes(),name.startswith('libexec/'))
    sha=digest(archive);url='https://github.com/umeiko/umeko-desktop-cpp/releases'
    spec={'id':ID,'qt':QT,'platform':'linux-x64','filename':archive.name,'bytes':archive.stat().st_size,'sha256':sha,'releaseUrl':url+'/tag/'+ID,'url':url+'/download/'+ID+'/'+archive.name}
    archive.with_suffix('.zip.sha256').write_text(sha+'  '+archive.name+'\n')
    (output/'webview-component.json').write_text(json.dumps(spec,indent=2)+'\n')
    if registry: registry.write_text(json.dumps(spec,indent=2)+'\n')
    print(json.dumps({'archive':str(archive),'bytes':spec['bytes'],'expandedBytes':sum(f.stat().st_size for f in files.values()),'sha256':sha}))

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--qt-root',type=Path);parser.add_argument('--frontend',type=Path);parser.add_argument('--engine',type=Path);parser.add_argument('--registry',type=Path)
    args=parser.parse_args()
    if args.frontend: stage_frontend(args.frontend,args.qt_root)
    if args.engine: engine_package(args.qt_root,args.engine,args.registry)
