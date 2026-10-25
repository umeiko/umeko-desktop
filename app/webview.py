"""Load Qt WebView before QApplication, with a separately installed Linux engine."""
import ctypes
import json
import os
import sys
from pathlib import Path
from PySide6.QtCore import QCoreApplication, QLibraryInfo, qVersion

_configuration = {"available": False}
_libraries = []

def component_directory():
    return Path(os.environ.get('UMEKO_WEBVIEW_COMPONENT_DIR') or Path(os.environ.get('XDG_DATA_HOME') or Path.home()/'.local/share')/'umeko/components')

def configuration():
    return {**_configuration, 'directory':str(component_directory()), 'qt':qVersion()}

def configure(root):
    global _configuration
    _configuration = {'available':False}
    support = root/'webview-support' if getattr(sys, 'frozen', False) else root/'build/webview-support'
    if sys.platform.startswith('linux'):
        try:
            spec=json.loads((root/'runtime/webview-component.json').read_text())
            active=json.loads((component_directory()/'active.json').read_text())
            folder=active['directory']
            if active['id']!=spec['id'] or active['sha256']!=spec['sha256'] or Path(folder).name!=folder or '..' in folder: return
            component=component_directory()/folder
            manifest=json.loads((component/'manifest.json').read_text())
            if manifest['qt']!=qVersion() or manifest['id']!=spec['id']: return
            if not all((component/file).is_file() for file in ('lib/libQt6WebEngineCore.so.6','libexec/QtWebEngineProcess','plugins/webview/libqtwebview_webengine.so')): return
            QCoreApplication.addLibraryPath(str(component/'plugins'))
            os.environ['QTWEBENGINEPROCESS_PATH']=str(component/'libexec/QtWebEngineProcess')
            os.environ['QTWEBENGINE_RESOURCES_PATH']=str(component/'resources')
            os.environ['QTWEBENGINE_LOCALES_PATH']=str(component/'translations/qtwebengine_locales')
            _configuration['qmlPath']=str(component/'qml')
            os.environ['LD_LIBRARY_PATH']=str(component/'lib')+':'+QLibraryInfo.path(QLibraryInfo.LibrariesPath)+':'+os.environ.get('LD_LIBRARY_PATH','')
        except (OSError, ValueError, KeyError, TypeError): return
    QCoreApplication.addLibraryPath(str(support/'plugins'))
    _configuration['frontendQmlPath']=str(support/'qml')
    if sys.platform=='win32':
        library=support/'bin/Qt6WebView.dll'
        if library.parent.is_dir(): _libraries.append(os.add_dll_directory(str(library.parent)))
    elif sys.platform=='darwin': library=support/'lib/QtWebView.framework/Versions/A/QtWebView'
    else: library=support/'lib/libQt6WebView.so.6'
    try:
        _libraries.append(ctypes.CDLL(str(library), mode=getattr(ctypes,'RTLD_GLOBAL',0)))
        if sys.platform.startswith('linux'):
            _libraries.append(ctypes.CDLL(str(support/'lib/libQt6WebViewQuick.so.6'), mode=ctypes.RTLD_GLOBAL))
        _configuration['available']=True
    except OSError as error: _configuration['error']=str(error)

def configure_engine(engine):
    for key in ('frontendQmlPath','qmlPath'):
        if _configuration.get(key): engine.addImportPath(_configuration[key])
