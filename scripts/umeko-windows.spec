# One PyInstaller analysis for the desktop and its console companion.
from pathlib import Path

from PyInstaller.utils.hooks import collect_all


root = Path(SPECPATH).parent
runtime_files = (
    'coordinator-skills.mjs',
    'cowork-tools.mjs',
    'cowork-local.mjs',
    'cowork-subagents.mjs',
    'skills.mjs',
    'markdown-preview.mjs',
    'session-capabilities.mjs',
    'tool-visibility.mjs',
    'conversation-search.mjs',
    'session-files.mjs',
    'update-engine.mjs',
    'update-cleanup.mjs',
    'widget-market.mjs',
    'bridge.mjs',
    'input-queue.mjs',
    'widget-messages.mjs',
    'background-jobs.mjs',
    'shell-snapshot.mjs',
    'command-process.mjs',
    'process-guard.mjs',
    'tool-permissions.mjs',
    'apply-patch.mjs',
    'subagents.mjs',
    'subagent-sdk.mjs',
    'subagent-settings.mjs',
    'rpc-ui.mjs',
    'provider-policy.mjs',
    'resources.mjs',
    'chatbox.mjs',
    'network-retry.mjs',
    'pi-commands.mjs',
    'umeko-control.mjs',
    'umeko-documents.mjs',
    'umeko-operations.json',
    'webview-component.mjs',
    'webview-component.json',
)
data_files = (
    ('bundled-skills', 'bundled-skills'),
    ('cowork-skills', 'cowork-skills'),
    ('build/desktop-plugin-resources', 'desktop-plugin-resources'),
    ('plugin-runtime', 'plugin-runtime'),
    ('build/builtin-widgets', 'umeko-plugins'),
    ('app/qml', 'app/qml'),
    ('app/theme-prompt.txt', 'app'),
    ('app/character-defaults.json', 'app'),
    ('app/provider-presets.json', 'app'),
    ('app/icons', 'app/icons'),
    ('runtime/umeko-docs', 'runtime/umeko-docs'),
    ('build/webview-support', 'webview-support'),
    ('build/build-info.json', '.'),
    ('build/provider-resources', 'provider-resources'),
    ('THIRD_PARTY_NOTICES.md', '.'),
    ('licenses', 'licenses'),
)
datas = [(str(root / path), destination) for path, destination in data_files]
datas += [(str(root / "runtime" / name), "runtime") for name in runtime_files]
binaries = [(str(root / "build/notification-runtime/umeko_notifications.dll"), "notification-runtime")]
hidden_imports = ["zoneinfo"]
for package in ("pypinyin", "tzdata"):
    package_data, package_binaries, package_imports = collect_all(package)
    datas += package_data
    binaries += package_binaries
    hidden_imports += package_imports

analysis = Analysis(
    [str(root / "main.py")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden_imports,
)
modules = PYZ(analysis.pure)
entry = dict(exclude_binaries=True, icon=str(root / "app/icons/app.ico"))
desktop = EXE(modules, analysis.scripts, [], name="Umeko", console=False, **entry)
cli = EXE(modules, analysis.scripts, [], name="Umeko-cli", console=True, **entry)
bundle = COLLECT(desktop, cli, analysis.binaries, analysis.datas, name="Umeko")
