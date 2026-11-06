"""Capture the displayed Windows client surface after real QML theme clicks.

Native mode is CI-only. --offscreen is explicitly weaker diagnostic evidence.
No production service, provider request, repaint, or grabWindow is used in native mode.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
import math
import os
import operator
from pathlib import Path
import struct
import sys
import tempfile
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
THEME_WALK = ("white", "light", "white", "dark", "white", "yanami",
              "light", "dark", "light", "yanami", "dark", "yanami", "white")


def ci_display_mode():
    """Temporarily choose an enumerated desktop mode; never persist settings."""
    user = ctypes.windll.user32
    user.EnumDisplaySettingsW.argtypes = [ctypes.c_wchar_p, wintypes.DWORD, ctypes.c_void_p]
    user.ChangeDisplaySettingsExW.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p,
                                            ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]
    user.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT,
                                         ctypes.c_void_p, wintypes.UINT]
    user.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    user.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
    user.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
    user.FindWindowW.restype = ctypes.c_void_p
    user.IsWindowVisible.argtypes = [ctypes.c_void_p]
    user.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
    old_dpi = user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    if not old_dpi:
        raise RuntimeError("Cannot enter PerMonitorV2 display measurement context")
    def work_area():
        value = wintypes.RECT()
        if not user.SystemParametersInfoW(0x0030, 0, ctypes.byref(value), 0):
            raise RuntimeError("SPI_GETWORKAREA failed")
        return [value.left, value.top, value.right, value.bottom]
    # DEVMODEW is 220 bytes. dmSize, dmPelsWidth/Height are fixed SDK offsets.
    def mode(index):
        value = ctypes.create_string_buffer(220)
        struct.pack_into("H", value, 68, 220)
        if not user.EnumDisplaySettingsW(None, index, value):
            return None
        return value
    changed = False
    taskbar = None
    shell_modified = False
    restored = False
    info = {}
    def prepare_after_app():
        nonlocal shell_modified
        if not fallback:
            return
        # Run exactly once after QApplication/tray creation, before placement.
        # Do not assume QScreen.availableGeometry reflects this shell change.
        shell_modified = True
        user.ShowWindow(taskbar, 0)
        set_work_area(full_area)
        info["shell_work_area_fallback"]["prepared_after_application"] = True
        info["shell_work_area_fallback"]["active_work_area_physical"] = work_area()
    def set_work_area(rect):
        value = wintypes.RECT(*rect)
        # Flags=0 changes the live work area without writing the user profile.
        if not user.SystemParametersInfoW(0x002F, 0, ctypes.byref(value), 0):
            raise RuntimeError("SPI_SETWORKAREA failed")
    def restore():
        nonlocal restored
        if restored:
            return
        receipt = info.setdefault("restore_receipt", {})
        errors = []
        if changed:
            status = user.ChangeDisplaySettingsExW(None, original, None, 4, None)
            receipt["display_mode_status"] = status
            if status != 0:
                errors.append(f"Desktop mode restore failed: {status}")
        if shell_modified:
            user.ShowWindow(taskbar, 4 if taskbar_was_visible else 0)  # SW_SHOWNOACTIVATE / SW_HIDE
            receipt["taskbar_visibility_restored_to"] = taskbar_was_visible
            try:
                set_work_area(initial_work)
                receipt["work_area_restored_to"] = initial_work
            except Exception as error:
                errors.append(str(error))
        restored = True
        receipt["completed"] = not errors
        if errors:
            raise RuntimeError("; ".join(errors))
    try:
        original = mode(0xFFFFFFFF)
        if original is None:
            raise RuntimeError("EnumDisplaySettingsW current mode failed")
        size = lambda value: struct.unpack_from("II", value, 172)
        initial = size(original)
        initial_work = work_area()
        reserved = [max(0, initial[0] - (initial_work[2] - initial_work[0])),
                    max(0, initial[1] - (initial_work[3] - initial_work[1]))]
        scale = float(os.environ["QT_SCALE_FACTOR"])
        client_required = [math.ceil(1060 * scale), math.ceil(700 * scale)]
        required = [max(1920, client_required[0] + reserved[0]),
                    max(1080, client_required[1] + reserved[1])]
        info = {"initial": initial, "initial_work_area_physical": initial_work,
                "reserved_physical": reserved, "required_client_physical": client_required,
                "required_desktop_physical": required}
        selected = original
        fallback = False
        if initial[0] < required[0] or initial[1] < required[1]:
            candidates = []
            client_candidates = []
            for index in range(4096):
                value = mode(index)
                if value is None:
                    break
                w, h = size(value)
                if w >= required[0] and h >= required[1]:
                    candidates.append((w * h, value))
                if w >= client_required[0] and h >= client_required[1]:
                    client_candidates.append((w * h, value))
            if not candidates:
                if not client_candidates:
                    raise RuntimeError(f"No supported desktop mode fits the client: {info}")
                # CI display adapters may top out at 1080p. Preserve application
                # flags and make only the shell's reserved work area available.
                candidates = client_candidates
                fallback = True
            selected = min(candidates, key=lambda row: row[0])[1]
            status = user.ChangeDisplaySettingsExW(None, selected, None, 4, None)
            if status != 0:
                raise RuntimeError(f"Temporary desktop mode change failed: {status}")
            changed = True
        if fallback:
            taskbar = user.FindWindowW("Shell_TrayWnd", None)
            if not taskbar:
                raise RuntimeError("CI taskbar fallback could not find Shell_TrayWnd")
            taskbar_was_visible = bool(user.IsWindowVisible(taskbar))
            selected_before = work_area()
            full_area = [0, 0, *size(selected)]
            info["shell_work_area_fallback"] = {
                "mode": "temporary-hide-taskbar-and-use-full-primary-screen",
                "original_taskbar_visible": taskbar_was_visible,
                "original_work_area_physical": initial_work,
                "selected_work_area_before_physical": selected_before,
                "temporary_work_area_physical": full_area,
                "registry_write": False}
        selected_work = work_area() if changed else initial_work
        if not fallback and (selected_work[2] - selected_work[0] < client_required[0]
                or selected_work[3] - selected_work[1] < client_required[1]):
            raise RuntimeError(f"Selected desktop work area does not fit client: {selected_work}, {info}")
        info.update(selected=size(selected), selected_work_area_physical=selected_work, changed=changed)
        return info, prepare_after_app, restore
    except Exception:
        restore()
        raise
    finally:
        user.SetThreadDpiAwarenessContext(old_dpi)


def wait_for_desktop_presentation(app):
    """Wait for queued presentation, without requesting another application frame.

    Qt frameSwapped means queued for presentation, not drawn on the desktop.
    DwmFlush waits for this calling application's queued DirectX changes.
    https://doc.qt.io/qt-6/qquickwindow.html#frameSwapped
    https://learn.microsoft.com/windows/win32/api/dwmapi/nf-dwmapi-dwmflush
    """
    app.processEvents()
    flush = ctypes.windll.dwmapi.DwmFlush
    flush.argtypes, flush.restype = [], ctypes.c_long
    status = flush()
    if status != 0:
        raise RuntimeError(f"DwmFlush failed: HRESULT 0x{status & 0xFFFFFFFF:08x}")
    return {"qt_state": "frame-queued", "desktop_wait": "DwmFlush", "hresult": status}


def native_capture(window):
    """Copy existing desktop pixels; never ask Qt or the window to render."""
    u, g = ctypes.windll.user32, ctypes.windll.gdi32
    ptr = ctypes.c_void_p
    u.GetDC.argtypes, u.GetDC.restype = [ptr], ptr
    u.ReleaseDC.argtypes = [ptr, ptr]
    u.GetClientRect.argtypes = [ptr, ctypes.POINTER(wintypes.RECT)]
    u.ClientToScreen.argtypes = [ptr, ctypes.POINTER(wintypes.POINT)]
    u.GetSystemMetrics.argtypes = [ctypes.c_int]
    u.IsIconic.argtypes = [ptr]
    u.IsWindowVisible.argtypes = [ptr]
    u.GetForegroundWindow.restype = ptr
    u.SetThreadDpiAwarenessContext.argtypes = [ptr]
    u.SetThreadDpiAwarenessContext.restype = ptr
    g.CreateCompatibleDC.argtypes, g.CreateCompatibleDC.restype = [ptr], ptr
    g.CreateDIBSection.argtypes = [ptr, ptr, wintypes.UINT, ctypes.POINTER(ptr), ptr, wintypes.DWORD]
    g.CreateDIBSection.restype = ptr
    g.SelectObject.argtypes, g.SelectObject.restype = [ptr, ptr], ptr
    g.BitBlt.argtypes = [ptr, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                         ptr, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
    g.DeleteObject.argtypes = [ptr]
    g.DeleteDC.argtypes = [ptr]
    old_dpi = u.SetThreadDpiAwarenessContext(ptr(-4))
    if not old_dpi:
        raise RuntimeError("Cannot enter PerMonitorV2 capture context")
    dc = memory = bitmap = old_bitmap = None
    try:
        hwnd = int(window.winId())
        if not u.IsWindowVisible(hwnd) or u.IsIconic(hwnd) or not window.isExposed():
            raise RuntimeError("Main window is not visible and exposed")
        if u.GetForegroundWindow() != hwnd:
            raise RuntimeError("Main window is not foreground; screen pixels may be obscured")
        rect = wintypes.RECT()
        if not u.GetClientRect(hwnd, ctypes.byref(rect)):
            raise RuntimeError("GetClientRect failed")
        a, b = wintypes.POINT(rect.left, rect.top), wintypes.POINT(rect.right, rect.bottom)
        if not (u.ClientToScreen(hwnd, ctypes.byref(a)) and u.ClientToScreen(hwnd, ctypes.byref(b))):
            raise RuntimeError("ClientToScreen failed")
        width, height = b.x - a.x, b.y - a.y
        vx, vy, vw, vh = (u.GetSystemMetrics(k) for k in (76, 77, 78, 79))
        if width <= 0 or height <= 0 or a.x < vx or a.y < vy or b.x > vx + vw or b.y > vy + vh:
            raise RuntimeError(f"Client rectangle outside desktop: {[a.x, a.y, b.x, b.y]}")

        class Header(ctypes.Structure):
            _fields_ = [("size", wintypes.DWORD), ("width", wintypes.LONG),
                        ("height", wintypes.LONG), ("planes", wintypes.WORD),
                        ("bits", wintypes.WORD), ("compression", wintypes.DWORD),
                        ("image_size", wintypes.DWORD), ("xppm", wintypes.LONG),
                        ("yppm", wintypes.LONG), ("used", wintypes.DWORD),
                        ("important", wintypes.DWORD)]

        header = Header(ctypes.sizeof(Header), width, -height, 1, 32, 0,
                        width * height * 4, 0, 0, 0, 0)
        dc = u.GetDC(None)
        memory = g.CreateCompatibleDC(dc)
        bits = ptr()
        bitmap = g.CreateDIBSection(dc, ctypes.byref(header), 0, ctypes.byref(bits), None, 0)
        if not dc or not memory or not bitmap or not bits:
            raise RuntimeError("Could not allocate screen capture bitmap")
        old_bitmap = g.SelectObject(memory, bitmap)
        if not old_bitmap or old_bitmap == ptr(-1).value:
            raise RuntimeError("SelectObject failed")
        if not g.BitBlt(memory, 0, 0, width, height, dc, a.x, a.y, 0x00CC0020 | 0x40000000):
            raise RuntimeError("BitBlt failed")
        g.GdiFlush()
        raw = ctypes.string_at(bits, width * height * 4)
        image = QImage(raw, width, height, width * 4, QImage.Format.Format_RGB32).copy()
        return image, {"client_screen_rect": [a.x, a.y, b.x, b.y],
                       "capture_method": "win32-screen-BitBlt", "foreground": True}
    finally:
        if old_bitmap and memory:
            g.SelectObject(memory, old_bitmap)
        if bitmap:
            g.DeleteObject(bitmap)
        if memory:
            g.DeleteDC(memory)
        if dc:
            u.ReleaseDC(None, dc)
        u.SetThreadDpiAwarenessContext(old_dpi)


def descendants(item):
    yield item
    for child in item.childItems():
        yield from descendants(child)


def find(window, name):
    for item in descendants(window.contentItem()):
        if item.objectName() == name:
            return item
    # Popup objects may be QObject children outside the ordinary visual tree.
    found = window.findChild(QObject, name)
    if found is None:
        raise RuntimeError(f"Missing QML object: {name}")
    return found


def qml_eval(item, code):
    expression = QQmlExpression(QQmlEngine.contextForObject(item), item, code)
    value = expression.evaluate()
    if expression.hasError():
        raise RuntimeError(expression.error().toString())
    return value


def click_theme(window, theme):
    choice = find(window, "theme_" + theme)
    for item in descendants(choice):
        meta = item.metaObject()
        if any(bytes(meta.method(i).methodSignature()).startswith(b"clicked(")
               for i in range(meta.methodCount())):
            # Execute the actual onClicked handler, including its backend.setTheme call.
            qml_eval(item, "clicked(null)")
            return
    raise RuntimeError(f"No clicked signal under theme_{theme}")


def pump(app, milliseconds):
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


def metrics(image):
    # Ignore the GDI reserved/alpha byte. Count the full client interior in RGB.
    inner = image.copy(12, 12, image.width() - 24, image.height() - 24)
    rgb = inner.convertToFormat(QImage.Format.Format_RGB888)
    raw = bytes(rgb.constBits())
    channels = [bytearray(), bytearray(), bytearray()]
    for y in range(rgb.height()):
        row = raw[y * rgb.bytesPerLine(): y * rgb.bytesPerLine() + rgb.width() * 3]
        for i in range(3):
            channels[i].extend(row[i::3])
    total = rgb.width() * rgb.height()
    table = bytes(1 if value <= 8 else 0 for value in range(256))
    masks = [channel.translate(table) for channel in channels]
    nearblack = sum(map(operator.and_, map(operator.and_, masks[0], masks[1]), masks[2]))
    channel_min = [min(channel) for channel in channels]
    channel_max = [max(channel) for channel in channels]
    # Luminance diagnostics can use a bounded sample; near-black counts above are exact.
    sample = inner.scaled(min(inner.width(), 240), min(inner.height(), 160))
    histogram = [0] * 256
    for y in range(sample.height()):
        for x in range(sample.width()):
            color = sample.pixelColor(x, y)
            histogram[round(.2126 * color.red() + .7152 * color.green() + .0722 * color.blue())] += 1
    sampled = sample.width() * sample.height()
    mean = sum(i * n for i, n in enumerate(histogram)) / sampled
    variance = sum((i - mean) ** 2 * n for i, n in enumerate(histogram)) / sampled
    quantiles = {}
    for percentile in (1, 50, 95, 99):
        accumulated = 0
        for i, n in enumerate(histogram):
            accumulated += n
            if accumulated >= sampled * percentile / 100:
                quantiles[str(percentile)] = i
                break
    return {"nearblack_max_rgb": 8, "nearblack_fraction": nearblack / total,
            "mean_luminance": mean, "std_luminance": variance ** .5,
            "luminance_percentiles": quantiles, "rgb_min": channel_min,
            "rgb_max": channel_max, "pixels": total, "luminance_sample_pixels": sampled}


def palette_probe(image, window, item, color, x, y):
    point = item.mapToScene(QPointF(x, y))
    sx, sy = image.width() / window.width(), image.height() / window.height()
    px, py = round(point.x() * sx), round(point.y() * sy)
    expected = [color.red(), color.green(), color.blue()]
    matched = total = 0
    for yy in range(py, min(image.height(), py + max(2, round(8 * sy)))):
        for xx in range(px, min(image.width(), px + max(2, round(3 * sx)))):
            actual = image.pixelColor(xx, yy)
            matched += max(abs(a - b) for a, b in zip(
                (actual.red(), actual.green(), actual.blue()), expected)) <= 8
            total += 1
    if total == 0:
        raise RuntimeError("Palette probe lies outside client capture")
    return {"expected_rgb": expected, "pixel_origin": [px, py],
            "match_fraction": matched / total, "tolerance": 8}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=("baseline", "long", "streaming", "popup"), default="baseline")
    parser.add_argument("--scale", choices=("1", "1.5"), default=os.environ.get("QT_SCALE_FACTOR", "1"))
    parser.add_argument("--offscreen", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.offscreen and (sys.platform != "win32" or os.environ.get("GITHUB_ACTIONS", "").lower() != "true"):
        parser.error("Native desktop mode runs only on Windows GitHub Actions; local native execution is refused")
    os.environ["QT_SCALE_FACTOR"] = args.scale
    if args.offscreen:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        os.environ.setdefault("QT_QUICK_BACKEND", "software")
    elif os.environ.get("QT_QPA_PLATFORM", "").lower() in ("offscreen", "minimal"):
        parser.error("Native mode requires the Windows desktop platform")
    out = args.output or ROOT / "artifacts" / "theme-switch" / f"{args.scenario}-{args.scale}"
    out.mkdir(parents=True, exist_ok=True)
    report = {"scenario": args.scenario, "scale": args.scale,
              "native_evidence": not args.offscreen,
              "capture_method": "Qt-grabWindow-offscreen-diagnostic" if args.offscreen else "win32-screen-BitBlt",
              "threshold_origin": "Regression-test assertion: max RGB <=8 fraction must be <0.2; not a measured production limit",
              "frames": [], "failures": [], "capture_validity_failures": [], "presentation_failures": [],
              "healthy_preswitch": False}
    app = engine = backend = window = None
    restore_display = lambda: None
    prepare_display = lambda: None
    reasoning_patch = None
    with tempfile.TemporaryDirectory(prefix="umeko-theme-ci-") as temporary:
        os.environ["UMEKO_DATA_DIR"] = str(Path(temporary) / "profile")
        os.environ["UMEKO_LANGUAGE"] = "en"
        sys.path.insert(0, str(ROOT))
        try:
            if not args.offscreen:
                report["display_mode"], prepare_display, restore_display = ci_display_mode()
            global QImage, QObject, QPointF, QQmlEngine, QQmlExpression, QEventLoop, QTimer
            from PySide6.QtCore import QObject, QPointF, QEventLoop, QTimer, Qt
            from PySide6.QtGui import QImage
            from PySide6.QtQml import QQmlEngine, QQmlExpression
            from app.storage import Store
            from app.controller import Controller
            from unittest.mock import patch
            import main as application
            seed = Store()
            seed.data["agent"]["agentDir"] = str(Path(temporary) / "agent")
            seed.data["theme"] = "white"
            seed.data["dark"] = False
            seed.data["providers"] = [{"id": "test-provider", "name": "Test provider",
                "api": "openai-completions", "baseUrl": "http://127.0.0.1:9/v1", "key": "",
                "proxy": {"mode": "direct"}, "models": [{"alias": "test-model", "upstream": "test-model",
                    "reasoningLevels": [], "reasoningLevelsAuto": False,
                    "reasoningFormat": "openai", "reasoningFormatAuto": False}]}]
            seed.data["selectedProvider"] = "test-provider"
            seed.data["selectedModel"] = "test-model"
            seed.save()
            # The real popup handler is retained; capability detection is outside
            # this rendering test and must never call even the fake endpoint.
            reasoning_patch = patch.object(Controller, "ensureModelReasoningDetection", lambda *args: None)
            reasoning_patch.start()
            report["network_detection_disabled"] = True
            app, engine, backend = application.create_application()
            prepare_display()
            window = engine.rootObjects()[0]
            screen = app.primaryScreen()
            shell_fallback = bool(report.get("display_mode", {}).get("shell_work_area_fallback"))
            # geometry is the full screen; availableGeometry excludes taskbars.
            # Native capture independently enforces the physical client bounds.
            area = screen.geometry() if shell_fallback else screen.availableGeometry()
            report["placement_geometry"] = {
                "source": "screen.geometry" if shell_fallback else "screen.availableGeometry",
                "logical_rect": [area.x(), area.y(), area.width(), area.height()]}
            if not args.offscreen:
                if area.width() < 1060 or area.height() < 700:
                    raise RuntimeError(f"Desktop too small at scale {args.scale}: {area.width()}x{area.height()} logical pixels")
                window.resize(min(1320, area.width()), min(860, area.height()))
                window.setPosition(area.x(), area.y())
                window.requestActivate()
            window.setProperty("page", "settings")
            window.setProperty("settingsTab", 5)
            record = backend._view
            if args.scenario == "long":
                record.messages = [{"role": "user", "text": "Test conversation"},
                                   {"role": "assistant", "text": "\n\n".join(
                                       f"Paragraph {n}: fixed fixture text for theme switching." for n in range(240)), "error": False}]
                backend.chatChanged.emit()
                backend.transcriptChanged.emit()
            elif args.scenario == "streaming":
                record.messages = [{"role": "assistant", "text": "", "error": False}]
                record.phase = "running"
                backend.chatChanged.emit()
            pump(app, 800)
            report["graphics_api"] = str(window.rendererInterface().graphicsApi())
            if not args.offscreen and "Software" in report["graphics_api"]:
                raise RuntimeError("Native test requires the actual accelerated graphics API, got Software")
            if not args.offscreen and not window.isExposed():
                raise RuntimeError("Main window never became exposed")
            # Settings remains instantiated. Theme clicks below still execute its
            # actual QML MouseArea handler while the real conversation is shown.
            if args.scenario in ("long", "streaming"):
                window.setProperty("page", "chat")
                pump(app, 350)
            popup = find(window, "modelPopup") if args.scenario == "popup" else None
            if popup is not None:
                qml_eval(popup, "open()")
                pump(app, 350)
                if not popup.property("visible"):
                    raise RuntimeError("Popup scenario did not open the real model popup")

            def capture(label, theme, check_palette=True):
                entry = {"label": label, "theme": theme, "timestamp": time.monotonic()}
                try:
                    if args.offscreen:
                        image, info = window.grabWindow(), {"capture_method": report["capture_method"]}
                    else:
                        image, info = native_capture(window)
                    if image.isNull():
                        raise RuntimeError("Empty capture")
                    entry.update(info)
                    entry["size"] = [image.width(), image.height()]
                    filename = label + ".png"
                    # Appearance's lower controls can contain fixture directory paths.
                    screenshot = image.copy(0, 0, image.width(), min(image.height(), round(600 * image.height() / window.height())))
                    if not screenshot.convertToFormat(QImage.Format.Format_RGB888).save(str(out / filename)):
                        raise RuntimeError("PNG write failed")
                    entry["image"] = filename
                    entry["image_crop"] = [0, 0, screenshot.width(), screenshot.height()]
                    entry["metrics"] = metrics(screenshot)
                    if entry["metrics"]["nearblack_fraction"] >= .2:
                        report["failures"].append(label + ": >=20% near-black client pixels")
                    sidebar = find(window, "sidebar")
                    main_area = find(window, "mainArea")
                    # Coordinates use the full client's transform; all probes are
                    # within the saved upper600-DIP screenshot.
                    entry["probes"] = {
                        "sidebar": palette_probe(image, window, sidebar, sidebar.property("color"), 4, min(300, sidebar.height() * .5)),
                        "background": palette_probe(image, window, main_area, window.color(), 10, 5)}
                    entry["page"] = window.property("page")
                    if check_palette:
                        for name, probe in entry["probes"].items():
                            if probe["match_fraction"] < .8:
                                report["failures"].append(f"{label}: stale/missing {name} palette pixels")
                    if popup is not None:
                        entry["popup_visible"] = bool(popup.property("visible"))
                        if not entry["popup_visible"]:
                            report["failures"].append(label + ": popup closed during theme switch")
                except Exception as error:
                    entry["error"] = str(error)
                    report["failures"].append(label + ": " + str(error))
                    report["capture_validity_failures"].append(label + ": " + str(error))
                report["frames"].append(entry)
                (out / "result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

            capture("00-white-baseline", "white")
            report["healthy_preswitch"] = not report["failures"]
            if not report["healthy_preswitch"]:
                report["capture_validity_failures"].append("Pre-switch screen capture was not healthy; cannot attribute a black frame to theme switching")
                raise RuntimeError("Healthy pre-switch capture prerequisite failed")
            for index, theme in enumerate(THEME_WALK[1:], 1):
                if args.scenario == "streaming":
                    backend._handle_pi_event(record, {"type": "delta", "text": f"Streaming chunk {index}.\n\n"})
                swaps = []
                synchronized = []
                armed = []
                def after_sync():
                    if armed:
                        synchronized.append(time.monotonic())
                def swapped():
                    if synchronized:
                        swaps.append(time.monotonic())
                # Direct callbacks observe the render thread's signal order.
                # Ignore a frame that was already synchronized before the click.
                window.afterSynchronizing.connect(after_sync, Qt.ConnectionType.DirectConnection)
                window.frameSwapped.connect(swapped, Qt.ConnectionType.DirectConnection)
                try:
                    click_theme(window, theme)
                    armed.append(True)
                    if backend.config.get("theme") != theme:
                        raise RuntimeError("Actual QML theme handler did not update backend config")
                    # A pre-presentation capture is diagnostic: old pixels are valid until a frame is swapped.
                    capture(f"{index:02d}-{theme}-immediate", theme, check_palette=False)
                    deadline = time.monotonic() + 3
                    while not swaps and time.monotonic() < deadline:
                        pump(app, 10)
                    if not swaps and not args.offscreen:
                        failure = f"{index:02d}-{theme}: no naturally synchronized post-click frameSwapped within 3 seconds"
                        report["failures"].append(failure)
                        report["presentation_failures"].append(failure)
                    if swaps and not args.offscreen:
                        try:
                            presentation = wait_for_desktop_presentation(app)
                            presentation["theme"] = theme
                            presentation["qt_after_synchronizing_at"] = synchronized[0]
                            presentation["qt_frame_queued_at"] = swaps[-1]
                            report.setdefault("presentation_waits", []).append(presentation)
                        except Exception as error:
                            failure = f"{index:02d}-{theme}: {error}"
                            report["failures"].append(failure)
                            report["presentation_failures"].append(failure)
                            raise
                    capture(f"{index:02d}-{theme}-presented", theme)
                    pump(app, 350)
                    capture(f"{index:02d}-{theme}-settled", theme)
                except Exception as error:
                    report["failures"].append(f"{index:02d}-{theme}: {error}")
                finally:
                    window.afterSynchronizing.disconnect(after_sync)
                    window.frameSwapped.disconnect(swapped)
            if args.scenario == "streaming":
                backend._handle_pi_event(record, {"type": "done"})
            report["attempted_transitions"] = len(THEME_WALK) - 1
        except Exception:
            report["failures"].append(traceback.format_exc())
        finally:
            for label, operation in (("backend.close", lambda: backend.close() if backend is not None else None),
                                     ("window.hide", lambda: window.hide() if window is not None else None),
                                     ("engine.delete", lambda: __import__("shiboken6").delete(engine) if engine is not None else None),
                                     ("reasoning.patch.stop", lambda: reasoning_patch.stop() if reasoning_patch is not None else None),
                                     ("display.restore", restore_display)):
                try:
                    operation()
                except Exception as error:
                    report["failures"].append(label + ": " + str(error))
            report["passed"] = not report["failures"]
            (out / "result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps({"passed": report["passed"], "failures": report["failures"],
                              "result": str(out / "result.json"), "native_evidence": report["native_evidence"]}))
            if app is not None:
                app.quit()
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
