"""Actual-host regressions; shared Python discovery runs once in Linux checks.

Run with the prepared desktop venv: python scripts/ci-native-tests.py.
Keep unittest module loading for terminal_widget's isolated POSIX PTY worker.
"""
import os
from pathlib import Path
import re
import sys

COMMON = [
    'tests.test_platform',
    'tests.test_terminal_widget',
    'tests.test_skill_import',
    'tests.test_update',
    'tests.test_preview_source',
    # Keep the module entrypoint: load_tests isolates its Qt application.
    'tests.test_preview_channel',
]

WINDOWS = [
    # Unique disposable Run value, guarded again by GITHUB_ACTIONS in the test.
    'tests.test_login_startup.WindowsCIRegistryTests',
    # Linux discovery cannot verify Windows QProcess cached/retiring cleanup.
    'tests.test_session_cache.SessionCacheTests.test_windows_cached_and_retiring_kernels_exit_on_app_close',
    'tests.test_runtime_paths',
    'tests.test_pi_management.NativeExtensionTests',
    'tests.test_windows_python_note',
    'tests.test_tool_history_layout',
    # Its module loader isolates Qt, including Windows CJK font coverage.
    'tests.test_preview_channel_ui',
    'tests.test_codearts_plugin_account.AccountTests.test_timeout_terminates_owned_launcher_tree',
    'tests.test_codearts_plugin_account.AccountTests.test_models_uses_direct_executable_and_private_trusted_directory',
    'tests.test_codearts_transport.TransportTests.test_broker_keepalive_peer_reset_closes_without_handler_traceback',
    'tests.test_desktop_plugins.DesktopPluginTests.test_terminal_worker_grants_the_composer_chat_and_executes_in_the_visible_pty',
    'tests.test_desktop_plugins.GitDemoTests.test_git_status_diff_stage_unstage_and_history_on_disposable_repository',
    'tests.test_pi.PiTests.test_all_native_tools_and_optional_extensions_reach_model_after_reload_and_resume',
    'tests.test_pi.PiTests.test_desktop_steering_interrupts_shell_and_preserves_followup',
    'tests.test_change_review.ReviewTests.test_empty_unchanged_long_lines_literal_names_and_symlinks',
]

UNIX = [
    'tests.test_skill_host.SkillHostTests.test_folder_delete_never_follows_asset_links',
]

NODE_HOST = [
    ('background-jobs', 'real background lifecycle: deadline, exit status, distinct files and byte cursors'),
    ('background-jobs', 'kill by job ID stops only its owned tree; session disposal leaves another manager alone'),
    ('package-install', 'cancellation terminates only the owned installer and its descendant'),
    ('package-install', 'real npm download/cache fallback finishes with a fully offline native Pi install'),
    ('conversation-search', 'literal CJK, quoted code, one/two characters and emoji use original visible text'),
    ('extension-metadata', 'real npm update probe uses the configured registry without installing the extension'),
    ('webview', 'URL submissions reuse the delivery protocol and guidance appears only when the component is missing'),
    ('update-engine', 'zip installs a staged payload and preserves an old-version backup'),
    ('update-engine', 'malicious paths and symlinks cannot escape or redirect extraction'),
    ('update-engine', 'replacement failure rolls back the existing directory'),
    ('update-engine', 'prepare copies the helper executable and runtime outside the install directory'),
    ('update-engine', 'an uncommitted or cancelled handoff never replaces the application'),
]
NODE_WINDOWS = [
    ('tool-permissions-integration', 'actual native powershell tool is intercepted before its harmless write'),
    ('subagent-queue', 'child queue edits/removal, immediate tool and model interruption, FIFO continuation, promotion, isolation and stop recovery'),
]
NODE_MAC = [
    ('update-download', 'verified cached archives avoid network; unrelated files and symlink targets survive'),
    ('update-engine', 'framework-style internal symlinks survive installation'),
    ('update-engine', 'existing installation paths through a directory alias are canonicalized'),
]


if __name__ == '__main__':
    from ci_process import run_logged

    root = Path(__file__).resolve().parents[1]
    log_dir = root / 'build/test-logs'
    log_dir.mkdir(parents=True, exist_ok=True)

    def run_suite(command, name):
        # Windows no-console children need explicit output handles. Keep the
        # complete output in uploaded diagnostics even when a suite fails.
        output = log_dir / f'native-{name}.log'
        try:
            result = run_logged(command, output, timeout=None, cwd=root)
        finally:
            print(output.read_text(encoding='utf-8', errors='replace'), end='', flush=True)
        result.check_returncode()

    suites = COMMON + (WINDOWS if os.name == 'nt' else UNIX)
    run_suite([sys.executable, '-m', 'unittest', *suites, '-v'], 'python')
    # Linux discovery/Node checks already run all Linux branches. Other hosts
    # retain actual process/filesystem/tool branches, not the shared Node suite.
    if sys.platform in ('win32', 'darwin'):
        cases = NODE_HOST + (NODE_WINDOWS if os.name == 'nt' else NODE_MAC)
        pattern = '^(?:' + '|'.join(re.escape(name) for _, name in cases) + ')$'
        files = list(dict.fromkeys(f'tests/{module}.test.mjs' for module, _ in cases))
        run_suite(['node', '--test', '--test-name-pattern=' + pattern, *files], 'node')
