"""Keep Windows IMM placement current between compositions as well as within one.

Qt 6.10.2 cursorRectChanged() skips its IMM writes without a composition HWND.
Reuse its CFS_FORCE_POSITION/CFS_EXCLUDE geometry on the current focus window.
This module neither starts compositions nor changes input-method association.
"""
import ctypes
from ctypes import wintypes
import sys

from .ime_trace import native_rectangle


class CompositionForm(ctypes.Structure):
    _fields_ = [("style", wintypes.DWORD), ("point", wintypes.POINT), ("area", wintypes.RECT)]


class CandidateForm(ctypes.Structure):
    _fields_ = [("index", wintypes.DWORD), ("style", wintypes.DWORD),
                ("point", wintypes.POINT), ("area", wintypes.RECT)]


def _imm32():
    imm = ctypes.WinDLL("imm32", use_last_error=True)
    imm.ImmGetContext.argtypes = [wintypes.HWND]
    imm.ImmGetContext.restype = wintypes.HANDLE
    imm.ImmReleaseContext.argtypes = [wintypes.HWND, wintypes.HANDLE]
    imm.ImmReleaseContext.restype = wintypes.BOOL
    imm.ImmSetCompositionWindow.argtypes = [wintypes.HANDLE, ctypes.POINTER(CompositionForm)]
    imm.ImmSetCompositionWindow.restype = wintypes.BOOL
    imm.ImmSetCandidateWindow.argtypes = [wintypes.HANDLE, ctypes.POINTER(CandidateForm)]
    imm.ImmSetCandidateWindow.restype = wintypes.BOOL
    return imm


class WindowsImePosition:
    @classmethod
    def install(cls, app):
        # Never access native Windows windows/IMM on offscreen, including the
        # local Windows regression suite, or on any other platform.
        if sys.platform != "win32" or app.platformName() != "windows":
            return None
        return cls()

    def __init__(self, imm=None):
        self._imm = _imm32() if imm is None else imm

    def publish(self, window, rectangle):
        if not rectangle.isValid():
            return None
        factor = window.devicePixelRatio()
        native = native_rectangle(rectangle, factor)
        x, y, width, height = native.x(), native.y(), native.width(), native.height()
        hwnd = int(window.winId())
        context = self._imm.ImmGetContext(hwnd)
        if not context:
            return None
        composition = CompositionForm(style=0x20, point=wintypes.POINT(x, y))
        candidate = CandidateForm(index=0, style=0x80, point=wintypes.POINT(x, y + height),
                                  area=wintypes.RECT(x, y, x + width, y + height))
        try:
            composition_set = bool(self._imm.ImmSetCompositionWindow(context, ctypes.byref(composition)))
            candidate_set = bool(self._imm.ImmSetCandidateWindow(context, ctypes.byref(candidate)))
        finally:
            self._imm.ImmReleaseContext(hwnd, context)
        return dict(dpr=factor, native=[x, y, width, height],
                    composition=[x, y], candidate=[x, y + height],
                    exclude=[x, y, x + width, y + height],
                    compositionSet=composition_set, candidateSet=candidate_set)
