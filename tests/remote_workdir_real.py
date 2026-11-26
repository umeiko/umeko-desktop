"""Run opt-in real SSH remote-workdir acceptance (dialog, 7 tools, 4 plugins, restart, reconnect).

Works against either the source checkout (Linux CI) or an unpacked Windows CI package
(Umeko.exe) with an isolated profile and a local scripted model (0 cost).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _ssh_executable(platform: str) -> str:
    if os.name == 'nt':
        for candidate in (
            r'C:\Program Files\Git\usr\bin\ssh.exe',
            r'C:\Program Files\Git\bin\ssh.exe',
        ):
            if Path(candidate).is_file():
                return candidate
    found = shutil.which('ssh')
    if not found:
        raise RuntimeError('OpenSSH client not found')
    return found


def _run_remote_ssh(ssh_exe: str, host: str, command: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [ssh_exe, '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', host, command],
        capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
    )


def _verify_remote_and_local(ssh_exe: str, host: str, platform: str, remote_path: str, mirror_dir: Path):
    # 1. Local mirror MUST NOT contain the remote files created by Pi tools
    for name in ('alpha.txt', 'untracked.txt', 'bash-marker.txt', 'sub'):
        assert not (mirror_dir / name).exists(), f'Local mirror unexpectedly modified: {mirror_dir / name}'

    # 2. Separate independent SSH command verifies files exist and match on the remote host
    if platform == 'windows':
        ps = (
            f"$p = '{remote_path.replace(chr(39), chr(39)*2)}'; "
            "Get-Content -Raw (Join-Path $p 'alpha.txt'); "
            "Write-Output '---BETA---'; "
            "Get-Content -Raw (Join-Path $p 'sub\\beta.txt'); "
            "Write-Output '---BASH---'; "
            "Get-Content -Raw (Join-Path $p 'bash-marker.txt')"
        )
        import base64
        encoded = base64.b64encode(ps.encode('utf-16le')).decode('ascii')
        cmd = f'powershell.exe -NoLogo -NoProfile -NonInteractive -EncodedCommand {encoded}'
    else:
        quoted = "'" + remote_path.replace("'", "'\\''") + "'"
        cmd = f'cat {quoted}/alpha.txt && echo "---BETA---" && cat {quoted}/sub/beta.txt && echo "---BASH---" && cat {quoted}/bash-marker.txt'

    proc = _run_remote_ssh(ssh_exe, host, cmd)
    assert proc.returncode == 0, f'Independent SSH verification failed: {proc.stdout}\n{proc.stderr}'
    out = proc.stdout
    assert 'AFTER_EDIT_MARKER' in out and 'line-three-reviewed' in out, out
    assert 'nested remote content' in out, out
    assert 'bash-marker' in out, out
    return out


def _cleanup_remote(ssh_exe: str, host: str, platform: str, remote_path: str):
    if platform == 'windows':
        ps = f"Remove-Item -LiteralPath '{remote_path.replace(chr(39), chr(39)*2)}' -Recurse -Force -ErrorAction SilentlyContinue"
        import base64
        encoded = base64.b64encode(ps.encode('utf-16le')).decode('ascii')
        _run_remote_ssh(ssh_exe, host, f'powershell.exe -NoLogo -NoProfile -NonInteractive -EncodedCommand {encoded}')
    else:
        quoted = "'" + remote_path.replace("'", "'\\''") + "'"
        _run_remote_ssh(ssh_exe, host, f'rm -rf -- {quoted}')


def _launch_app(command: list[str], env: dict[str, str], log_path: Path, timeout: int) -> int:
    with log_path.open('w', encoding='utf-8') as log:
        process = subprocess.Popen(
            command, env=env, stdout=log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
        )
        try:
            return process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=30)
            raise RuntimeError(f'Timed out running {command}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument('--app', type=Path, help='Unpacked Umeko executable')
    src.add_argument('--source', action='store_true', help='Run from source checkout')
    parser.add_argument('--host', required=True)
    parser.add_argument('--platform', choices=('linux', 'windows'), required=True)
    parser.add_argument('--remote-parent', required=True, help='Existing remote parent folder where test folder is created')
    parser.add_argument('--run-dir', type=Path, required=True, help='Isolated local test directory')
    parser.add_argument('--outage-seconds', type=int, default=12)
    parser.add_argument('--bootstrap-timeout', type=int, default=300)
    parser.add_argument('--keep-remote', action='store_true')
    args = parser.parse_args()

    directory = args.run_dir.resolve()
    assert directory != ROOT and ROOT not in directory.parents, 'Run dir must be outside checkout'
    directory.mkdir(parents=True, exist_ok=True)
    for sub in ('profile', 'agent', 'workspace', 'ssh-control'):
        (directory / sub).mkdir(exist_ok=True)

    shim = directory / 'ssh-shim.py'
    shutil.copyfile(ROOT / 'tests/fixtures/remote_ssh_shim.py', shim)
    python = os.path.abspath(sys.executable)
    ssh_exe = _ssh_executable(args.platform)
    folder_name = f'umeko-rw-{uuid.uuid4().hex[:8]}'

    settings = {
        'agent': {'agentDir': str(directory / 'agent'), 'autoCompaction': False, 'toolPermissionMode': 'auto'},
        'workspace': str(directory / 'workspace'),
        'server': {'port': 0},
        'desktop': {'loginStartup': False},
        'providers': [],
    }
    (directory / 'profile/settings.json').write_text(json.dumps(settings), encoding='utf-8')

    spec_main = {
        'phase': 'main',
        'runDir': str(directory),
        'host': args.host,
        'platform': args.platform,
        'remoteParent': args.remote_parent,
        'folderName': folder_name,
        'outageSeconds': args.outage_seconds,
        'bootstrapTimeout': args.bootstrap_timeout,
    }
    spec_main_path = directory / 'spec-main.json'
    spec_main_path.write_text(json.dumps(spec_main, indent=2), encoding='utf-8')

    base_cmd = [str(args.app.resolve())] if args.app else [python, str(ROOT / 'main.py')]
    env = dict(
        os.environ,
        UMEKO_DATA_DIR=str(directory / 'profile'),
        PI_CODING_AGENT_DIR=str(directory / 'agent'),
        QT_QPA_PLATFORM='offscreen',
        QT_QUICK_BACKEND='software',
        UMEKO_SSH_TEST_CONTROL=str(directory / 'ssh-control'),
        UMEKO_TEST_SSH_COMMAND=json.dumps([python, str(shim)]),
        PYTHONUTF8='1',
        UMEKO_DIAGNOSTICS=str(directory / 'application-main.log'),
    )
    env.pop('NODE_OPTIONS', None)
    env.pop('NODE_PATH', None)
    env.pop('UMEKO_REAL_SSH', None)

    created_remote = None
    try:
        # Phase 1: dialog, 7 tools, 4 plugins, connection drop recovery
        status = _launch_app(base_cmd + ['--remote-workdir-smoke', str(spec_main_path)], env,
                             directory / 'output-main.log', timeout=args.bootstrap_timeout + 600)
        res_path = directory / 'result.json'
        res_main = json.loads(res_path.read_text(encoding='utf-8')) if res_path.exists() else {}
        if status != 0 or not res_main.get('ok'):
            print((directory / 'output-main.log').read_text(encoding='utf-8', errors='replace')[-12000:])
            raise RuntimeError(f'Phase 1 failed: exit={status}, result={res_main}')
        created_remote = res_main['remoteWorkspace']['remotePath']
        mirror_dir = Path(res_main['mirrorDir'])

        # Independent SSH verification: remote changed, local mirror did not
        ssh_proof = _verify_remote_and_local(ssh_exe, args.host, args.platform, created_remote, mirror_dir)

        # Phase 2: restart fresh app on same profile and reopen remote project
        spec_reopen = {
            'phase': 'reopen',
            'runDir': str(directory),
            'host': args.host,
            'platform': args.platform,
            'projectId': res_main['projectId'],
            'expectedRemotePath': created_remote,
            'bootstrapTimeout': args.bootstrap_timeout,
        }
        spec_reopen_path = directory / 'spec-reopen.json'
        spec_reopen_path.write_text(json.dumps(spec_reopen, indent=2), encoding='utf-8')
        env_reopen = dict(env, UMEKO_DIAGNOSTICS=str(directory / 'application-reopen.log'))
        status2 = _launch_app(base_cmd + ['--remote-workdir-smoke', str(spec_reopen_path)], env_reopen,
                              directory / 'output-reopen.log', timeout=args.bootstrap_timeout + 300)
        reopen_path = directory / 'reopen-result.json'
        res_reopen = json.loads(reopen_path.read_text(encoding='utf-8')) if reopen_path.exists() else {}
        if status2 != 0 or not res_reopen.get('ok'):
            print((directory / 'output-reopen.log').read_text(encoding='utf-8', errors='replace')[-12000:])
            raise RuntimeError(f'Phase 2 reopen failed: exit={status2}, result={res_reopen}')

        summary = {
            'ok': True,
            'platform': args.platform,
            'mode': 'packaged' if args.app else 'source',
            'main': res_main,
            'independentSshVerified': True,
            'independentSshOutputPreview': ssh_proof[:300],
            'localMirrorUnchanged': True,
            'reopen': res_reopen,
        }
        summary_path = directory / 'summary.json'
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
        print('REMOTE_WORKDIR_REAL_PASSED:', summary_path, flush=True)
    finally:
        if created_remote and not args.keep_remote:
            _cleanup_remote(ssh_exe, args.host, args.platform, created_remote)


if __name__ == '__main__':
    main()
