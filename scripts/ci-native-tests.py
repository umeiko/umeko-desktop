"""Actual-host regressions; shared Python discovery runs once in Linux checks.

Run with the prepared desktop venv: python scripts/ci-native-tests.py.
Keep unittest module loading for terminal_widget's isolated POSIX PTY worker.
"""
import os
from pathlib import Path
import subprocess
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


if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1]
    suites = COMMON + (WINDOWS if os.name == 'nt' else UNIX)
    subprocess.run([sys.executable, '-m', 'unittest', *suites, '-v'],
                   cwd=root, check=True,
                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
