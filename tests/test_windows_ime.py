"""Offscreen tests of IMM arguments; no native window or OS input is used."""
import ctypes
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import QRectF

from app.windows_ime import CandidateForm, CompositionForm, WindowsImePosition


class Imm:
    def __init__(self, context=22):
        self.context = context
        self.calls = []

    def ImmGetContext(self, hwnd):
        self.calls.append(("get", hwnd))
        return self.context

    def ImmSetCompositionWindow(self, context, pointer):
        form = ctypes.cast(pointer, ctypes.POINTER(CompositionForm)).contents
        self.calls.append(("composition", context, form.style, form.point.x, form.point.y))
        return True

    def ImmSetCandidateWindow(self, context, pointer):
        form = ctypes.cast(pointer, ctypes.POINTER(CandidateForm)).contents
        self.calls.append(("candidate", context, form.index, form.style, form.point.x, form.point.y,
                           form.area.left, form.area.top, form.area.right, form.area.bottom))
        return False

    def ImmReleaseContext(self, hwnd, context):
        self.calls.append(("release", hwnd, context))


class Window:
    def devicePixelRatio(self): return 1.5
    def winId(self): return 11


class WindowsImeTests(unittest.TestCase):
    def test_native_arguments_use_qt_rounding_and_preserve_api_results(self):
        imm = Imm()
        result = WindowsImePosition(imm).publish(Window(), QRectF(1.1, 2.1, 1, 10))
        self.assertEqual(imm.calls, [("get", 11), ("composition", 22, 0x20, 2, 3),
                                    ("candidate", 22, 0, 0x80, 2, 18, 2, 3, 3, 18),
                                    ("release", 11, 22)])
        self.assertEqual(result, dict(dpr=1.5, native=[2, 3, 1, 15], composition=[2, 3],
                                      candidate=[2, 18], exclude=[2, 3, 3, 18],
                                      compositionSet=True, candidateSet=False))

    def test_missing_context_and_invalid_rectangle_do_not_set_positions(self):
        imm = Imm(context=0)
        publisher = WindowsImePosition(imm)
        self.assertIsNone(publisher.publish(Window(), QRectF()))
        self.assertEqual(imm.calls, [])
        self.assertIsNone(publisher.publish(Window(), QRectF(1, 2, 1, 10)))
        self.assertEqual(imm.calls, [("get", 11)])

    def test_context_is_released_when_a_native_call_raises(self):
        imm = Imm()
        with patch.object(imm, "ImmSetCandidateWindow", side_effect=OSError("native call failed")):
            with self.assertRaises(OSError):
                WindowsImePosition(imm).publish(Window(), QRectF(1, 2, 1, 10))
        self.assertEqual(imm.calls[-1], ("release", 11, 22))

    def test_offscreen_and_other_platforms_never_load_imm(self):
        with patch("app.windows_ime._imm32") as load:
            with patch("app.windows_ime.sys.platform", "win32"):
                self.assertIsNone(WindowsImePosition.install(Mock(platformName=lambda: "offscreen")))
            with patch("app.windows_ime.sys.platform", "linux"):
                self.assertIsNone(WindowsImePosition.install(Mock(platformName=lambda: "windows")))
            load.assert_not_called()


if __name__ == "__main__":
    unittest.main()
