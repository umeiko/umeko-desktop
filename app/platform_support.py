"""Desktop paths and input methods, configured before creating a Qt application."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def data_directory(platform=None, environment=None, home=None):
    platform = platform or sys.platform
    environment = os.environ if environment is None else environment
    home = Path.home() if home is None else Path(home)
    if platform == "win32":
        return Path(environment.get("LOCALAPPDATA", str(home))) / "Umeko"
    if platform == "darwin":
        return home / "Library/Application Support/Umeko"
    return Path(environment.get("XDG_DATA_HOME") or home / ".local/share") / "umeko"


def configure_input_method(platform=None, environment=None, plugin_directory=None):
    platform = platform or sys.platform
    environment = os.environ if environment is None else environment
    if not platform.startswith("linux"):
        return
    if "UMEKO_QT_IM_MODULE" in environment:
        environment["QT_IM_MODULE"] = environment["UMEKO_QT_IM_MODULE"]
        return
    if plugin_directory is None:
        from PySide6.QtCore import QLibraryInfo
        plugin_directory = Path(QLibraryInfo.path(QLibraryInfo.PluginsPath)) / "platforminputcontexts"
    plugins = Path(plugin_directory)
    module = environment.get("QT_IM_MODULE", "")
    fcitx = module in ("fcitx", "fcitx5") or (not module and "fcitx" in environment.get("XMODIFIERS", ""))
    if not fcitx:
        return  # Preserve native Wayland text input and unrelated IME choices.
    if any(plugins.glob("*fcitx*.so")):
        environment["QT_IM_MODULE"] = "fcitx"
    elif any(plugins.glob("*ibus*.so")):
        # Fcitx5 implements the IBus protocol. PySide's own Qt normally bundles
        # this plugin; system fcitx Qt plugins may use an incompatible Qt ABI.
        environment["QT_IM_MODULE"] = "ibus"
