"""PR package boundaries and the workflow's real parallel exit-status handling."""
import importlib.util
import json
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
    def test_daily_builds_use_windows_and_full_releases_require_explicit_dispatch(self):
        for event,value in [('push',''),('pull_request','true'),('workflow_dispatch','false')]:
            with self.subTest(event=event,value=value):
                self.assertEqual([row['platform'] for row in scope.package_matrix(event,value)['include']], ['windows-x64'])
        full = scope.package_matrix('workflow_dispatch','true')['include']
        self.assertEqual({row['platform'] for row in full},
                         {'windows-x64','linux-x64','macos-arm64','macos-x64'})

    def test_main_push_plans_windows_package_without_a_pr_diff_base(self):
        import sys
        with tempfile.TemporaryDirectory() as temporary:
            output=Path(temporary)/'outputs'
            env={**os.environ,'GITHUB_EVENT_NAME':'push','GITHUB_OUTPUT':str(output)}
            env.pop('PR_BASE',None)
            subprocess.run([sys.executable,str(ROOT/'scripts/ci-package-changes.py')],
                           env=env,check=True,capture_output=True,text=True)
            values=dict(line.split('=',1) for line in output.read_text().splitlines())
            self.assertEqual(values['packages'],'true')
            self.assertEqual(json.loads(values['matrix'])['include'][0]['platform'],'windows-x64')

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
        step=workflow.split('      - name: Python unit tests\n',1)[1].split('\n  windows-path-checks:',1)[0]
        block=textwrap.dedent(step.split('        run: |\n',1)[1])
        orchestration=block.split('export -f unit_tests',1)[1]
        runner=(ROOT/'scripts/ci-ui-smokes.bash').read_text(encoding='utf-8')
        smoke_names=('fixture_first_ui_smoke.py','fixture_second_ui_smoke.py')
        before,after=runner.split('smokes=(\n',1)
        _,after=after.split('\n)',1)
        runner=before+'smokes=(\n'+''.join('  tests/'+name+'\n' for name in smoke_names)+')'+after
        fixture='''
set -e
export RUNNER_TEMP="$(pwd -P)"
dbus-run-session() { if [[ "$1" == -- ]]; then shift; fi; export DBUS_SESSION_BUS_ADDRESS="fixture:$BASHPID"; "$@"; }
gnome-keyring-daemon() { cat >/dev/null; }
flock() { :; }
# Validate every recursive cleanup target against this disposable workspace.
rm() {
  target="$(realpath -- "${@: -1}")"
  case "$target" in "$RUNNER_TEMP"/umeko-ci.*|"$RUNNER_TEMP"/umeko-ui.*) command rm "$@";; *) return 77;; esac
}
unit_tests() { printf '%s\\n%s\\n' "$XDG_DATA_HOME" "$DBUS_SESSION_BUS_ADDRESS" > unit.env; return "$UNIT_STATUS"; }
export -f unit_tests dbus-run-session gnome-keyring-daemon flock rm
'''
        for unit,ui in ((0,0),(1,0),(0,1),(1,1)):
            with self.subTest(unit=unit,ui=ui), tempfile.TemporaryDirectory(prefix='umeko-ci-workers-') as temporary:
                root=Path(temporary).resolve()
                (root/'scripts').mkdir()
                (root/'scripts/ci-ui-smokes.bash').write_text(runner,encoding='utf-8',newline='\n')
                python=root/'.venv/bin/python';python.parent.mkdir(parents=True)
                python.write_text('#!/usr/bin/env bash\n'
                    'printf "%s\\n" "$XDG_DATA_HOME" "$DBUS_SESSION_BUS_ADDRESS" "$PI_CODING_AGENT_DIR" '
                    '"$UMEKO_DATA_DIR" "$XDG_RUNTIME_DIR" "$XDG_CONFIG_HOME" "$XDG_CACHE_HOME" > "${1##*/}.env"\n'
                    'exit "$UI_STATUS"\n',encoding='utf-8',newline='\n')
                python.chmod(0o755)
                result=subprocess.run([bash,'-c',fixture+orchestration],cwd=root,
                    env=dict(os.environ,UNIT_STATUS=str(unit),UI_STATUS=str(ui)),
                    capture_output=True,text=True,timeout=20,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                self.assertEqual(result.returncode,1 if unit or ui else 0,result.stdout+result.stderr)
                first=(root/'unit.env').read_text().splitlines()
                workers=[(root/(name+'.env')).read_text().splitlines() for name in smoke_names]
                self.assertEqual(len({first[0],*(worker[0] for worker in workers)}),3)
                self.assertEqual(len({first[1],*(worker[1] for worker in workers)}),3)
                self.assertNotEqual(workers[0][2],workers[1][2])
                for worker in workers:
                    profile=worker[0].rsplit('/',1)[0]
                    self.assertEqual(worker[2:],[profile+'/agent',profile+'/profile',profile+'/run',profile+'/config',profile+'/cache'])
                self.assertFalse(list(root.glob('umeko-ci.*')))
                self.assertFalse(list(root.glob('umeko-ui.*')))
                results=list((root/'build').glob('ui-smokes.*/*.result'))
                self.assertEqual(len(results),2)
                for path in results:
                    self.assertEqual(path.read_text().strip().split('\t')[2],str(ui))
