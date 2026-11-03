"""PR package boundaries and the workflow's real parallel exit-status handling."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ci_package_changes', ROOT/'scripts/ci-package-changes.py')
scope = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scope)


class PackageChangesTests(unittest.TestCase):
    def test_source_and_test_changes_keep_the_light_path(self):
        for path in ('app/controller.py','app/qml/Main.qml','app/qml/markdown.js','runtime/bridge.mjs',
                     'tests/test_links.py','tests/fixtures/requirements.txt','tests/fixtures/demo.spec',
                     'docs/ci.md','docs-site/index.md','.github/workflows/docs.yml'):
            with self.subTest(path=path):self.assertFalse(scope.needs_packages([path]))

    def test_build_dependencies_resources_and_unknown_inputs_request_packages(self):
        for path in ('build.ps1','build.sh','setup.sh','requirements.txt','requirements-dev.txt',
                     'runtime/package-lock.json','runtime/umeko-docs/help.md','runtime/webview-component.json',
                     'app/icons/app.ico','app/qml/qmldir','app/qml/skill.svg','app/new-data.json',
                     'runtime/new-data.json','app/native-adapter.cpp','app/theme-prompt.txt','README.md',
                     'plugin-runtime/sdk.js','umeko-plugins/terminal/main.qml','licenses/MPL.txt',
                     'bundled-skills/demo/SKILL.md','.github/workflows/build.yml','unknown/file'):
            with self.subTest(path=path):self.assertTrue(scope.needs_packages([path]))
        self.assertFalse(scope.needs_packages([]))
        self.assertTrue(scope.needs_packages(['app/controller.py','app/qml/skill.svg']))

    def test_parallel_worker_status_and_isolation(self):
        bash = shutil.which('bash') if os.name != 'nt' else str(Path(shutil.which('git')).parents[1]/'bin/bash.exe') if shutil.which('git') else ''
        if not bash or not Path(bash).is_file():self.skipTest('Bash is unavailable')
        workflow=(ROOT/'.github/workflows/build.yml').read_text(encoding='utf-8')
        block=textwrap.dedent(workflow.split('      - name: Python unit tests\n        run: |\n',1)[1].split('\n  windows-path-checks:',1)[0])
        orchestration=block.split('          export -f unit_tests ui_smokes'.strip(),1)[1]
        fixture='''
set -e
export RUNNER_TEMP="$(pwd -P)"
dbus-run-session() { if [[ "$1" == -- ]]; then shift; fi; export DBUS_SESSION_BUS_ADDRESS="fixture:$BASHPID"; "$@"; }
gnome-keyring-daemon() { cat >/dev/null; }
# Validate every recursive cleanup target against this disposable workspace.
rm() {
  target="$(realpath -- "${@: -1}")"
  case "$target" in "$RUNNER_TEMP"/umeko-ci.*) command rm "$@";; *) return 77;; esac
}
unit_tests() { printf '%s\\n%s\\n' "$XDG_DATA_HOME" "$DBUS_SESSION_BUS_ADDRESS" > unit.env; return "$UNIT_STATUS"; }
ui_smokes() { printf '%s\\n%s\\n' "$XDG_DATA_HOME" "$DBUS_SESSION_BUS_ADDRESS" > ui.env; return "$UI_STATUS"; }
export -f unit_tests ui_smokes dbus-run-session gnome-keyring-daemon rm
'''
        for unit,ui in ((0,0),(1,0),(0,1),(1,1)):
            with self.subTest(unit=unit,ui=ui), tempfile.TemporaryDirectory(prefix='umeko-ci-workers-') as temporary:
                root=Path(temporary).resolve()
                result=subprocess.run([bash,'-c',fixture+orchestration],cwd=root,
                    env=dict(os.environ,UNIT_STATUS=str(unit),UI_STATUS=str(ui)),
                    capture_output=True,text=True,timeout=20,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                self.assertEqual(result.returncode,1 if unit or ui else 0,result.stdout+result.stderr)
                first=(root/'unit.env').read_text().splitlines();second=(root/'ui.env').read_text().splitlines()
                self.assertNotEqual(first[0],second[0]);self.assertNotEqual(first[1],second[1])
                self.assertFalse(list(root.glob('umeko-ci.*')))
