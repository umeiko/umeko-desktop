"""Collect the Windows QML runtime without optional PySide6 Addons modules."""

from importlib.metadata import distribution
from pathlib import Path

from PyInstaller.utils.hooks.qt import add_qt6_dependencies, pyside6_library_info


hiddenimports, binaries, datas = add_qt6_dependencies(__file__)
qml_binaries, qml_datas = pyside6_library_info.collect_qtqml_files()

# The audio player imports QtMultimedia from Python, where its own hook
# collects the playback libraries and plugins. QML uses Essentials and the
# separately staged Qt WebView frontend (WebView2 on Windows).
addons = distribution("PySide6-Addons")
addon_modules = [
    Path(addons.locate_file(entry)).parent.resolve()
    for entry in addons.files
    if entry.parts[:2] == ("PySide6", "qml") and entry.name == "qmldir"
]


def essential_qml(entries):
    return [
        (source, destination)
        for source, destination in entries
        if not any(Path(source).is_relative_to(module) for module in addon_modules)
    ]


binaries += essential_qml(qml_binaries)
datas += essential_qml(qml_datas)
