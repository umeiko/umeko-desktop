"""Native file clipboard and application chooser after scoped plugin host events."""
import os,struct,subprocess,sys,threading

def copy_files(paths,cut=False):
    from PySide6.QtCore import QMimeData,QUrl
    from PySide6.QtGui import QGuiApplication
    data=QMimeData();data.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
    data.setData('application/x-qt-windows-mime;value="Preferred DropEffect"',struct.pack('<I',2 if cut else 1))
    data.setData('x-special/gnome-copied-files',(('cut' if cut else 'copy')+'\n'+'\n'.join(QUrl.fromLocalFile(str(path)).toString() for path in paths)).encode('utf-8'))
    QGuiApplication.clipboard().setMimeData(data)

def open_with(path):
    if os.name=='nt':
        def choose():
            import ctypes
            from ctypes import wintypes
            class OpenAsInfo(ctypes.Structure):
                _fields_=[('file',wintypes.LPCWSTR),('fileClass',wintypes.LPCWSTR),('flags',wintypes.DWORD)]
            initialized=ctypes.windll.ole32.CoInitializeEx(None,2)>=0
            try:
                show=ctypes.windll.shell32.SHOpenWithDialog
                show.argtypes=[wintypes.HWND,ctypes.POINTER(OpenAsInfo)];show.restype=ctypes.c_long
                show(None,ctypes.byref(OpenAsInfo(str(path),None,4)))
            finally:
                if initialized:ctypes.windll.ole32.CoUninitialize()
        threading.Thread(target=choose,daemon=True).start()
    else:
        from PySide6.QtWidgets import QFileDialog
        application,_=QFileDialog.getOpenFileName(None,'选择打开此文件的应用','/Applications' if sys.platform=='darwin' else '/usr/bin')
        if application:subprocess.Popen(['/usr/bin/open','-a',application,str(path)] if sys.platform=='darwin' else [application,str(path)])
