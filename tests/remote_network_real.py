"""Opt-in real network sharing acceptance, with a local scripted model only.

Linux: prepared disposable SSH fixture, --source --host umeko-network-ci.
Windows: --app Umeko.exe --host AUTHORIZED_ALIAS --platform windows
  --run-root C:/remote-tests --run-dir C:/remote-tests/network-01
  --remote-root C:/remote-tests --local-proxy http://127.0.0.1:10818
The Windows host must already lack direct Internet access. This runner never
changes its firewall, SSH service, proxy processes, or server configuration.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath

ROOT = Path(__file__).resolve().parents[1]


def commands(platform, root, python, phase):
    """Each probe needs a new destination and bypasses package caches."""
    destination = root + '/' + phase
    if platform == 'windows':
        def q(value):
            return "'" + value.replace("'", "''") + "'"
        base = "$ErrorActionPreference='Stop'; $d=" + q(destination) + "; New-Item -ItemType Directory -Force $d | Out-Null; "
        finish = "; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }; "
        return {
            'curl': base + 'curl.exe -fS --connect-timeout 8 --max-time 25 https://example.com/ -o "$d/curl.html"' + finish + 'if ((Get-Item "$d/curl.html").Length -le 0) { exit 91 }',
            'pip': base + '& ' + q(python) + ' -m pip install --disable-pip-version-check --no-cache-dir --no-deps --retries 0 --timeout 15 --index-url https://pypi.org/simple --target "$d/pip" six==1.17.0' + finish + 'if (!(Test-Path "$d/pip/six.py")) { exit 92 }',
            'git': base + 'git -c http.connectTimeout=8 -c http.lowSpeedLimit=1 -c http.lowSpeedTime=20 clone --depth 1 https://github.com/octocat/Hello-World.git "$d/git"' + finish + 'if (!(Test-Path "$d/git/README")) { exit 93 }',
        }
    d = shlex.quote(destination)
    base = 'mkdir -p ' + d + '; '
    return {
        'curl': base + f'timeout 35 curl -fS --connect-timeout 8 --max-time 25 https://example.com/ -o {d}/curl.html && test -s {d}/curl.html',
        'pip': base + f'timeout 45 {shlex.quote(python)} -m pip install --disable-pip-version-check --no-cache-dir --no-deps --retries 0 --timeout 15 --target {d}/pip six==1.17.0 && test -s {d}/pip/six.py',
        'npm': base + f'timeout 45 npm install is-number@7.0.0 --prefix {d} --cache {d}/npm-cache --ignore-scripts --no-audit --no-fund --fetch-retries=0 --fetch-timeout=20000 && test -s {d}/node_modules/is-number/index.js',
        'git': base + f'timeout 45 git -c http.connectTimeout=8 -c http.lowSpeedLimit=1 -c http.lowSpeedTime=20 clone --depth 1 https://github.com/octocat/Hello-World.git {d}/git && test -s {d}/git/README',
        # sl is absent on the disposable CI image; a fresh archive cache means
        # apt has to download package bytes before its actual installation.
        'apt': base + f'sudo -n mkdir -p {d}/apt/partial && sudo -n chmod 777 {d}/apt {d}/apt/partial && sudo -n apt-get -o Acquire::Retries=0 -o Acquire::http::Timeout=15 -o Acquire::https::Timeout=15 -o Dir::Cache::archives={d}/apt install -y sl && dpkg-query -W -f=\'${{Status}}\' sl | grep -q "install ok installed"',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--source', action='store_true')
    mode.add_argument('--app', type=Path)
    parser.add_argument('--host', required=True)
    parser.add_argument('--platform', choices=('linux', 'windows'), required=True)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--run-root', type=Path)
    parser.add_argument('--remote-root')
    parser.add_argument('--remote-python')
    parser.add_argument('--local-proxy', help='Existing local HTTP proxy, never started or modified')
    args = parser.parse_args()
    directory = args.run_dir.resolve()
    if args.platform == 'windows':
        if not args.app or not args.run_root or not args.remote_root:
            parser.error('Windows requires --app, --run-root and --remote-root')
        assert args.run_root.resolve() in directory.parents, 'Run directory must be below --run-root'
    assert directory != ROOT and ROOT not in directory.parents, 'Run data must be outside the checkout'
    assert not any(p.name == 'HB-Workspace' for p in (directory, *directory.parents)), 'Run data must be outside HB-Workspace'
    inherited = [p / name for p in directory.parents for name in ('AGENTS.md', 'CLAUDE.md') if (p / name).is_file()]
    assert not inherited, 'Run workspace inherits instructions: ' + str(inherited[:1])
    remote_type = PureWindowsPath if args.platform == 'windows' else PurePosixPath
    remote_root = remote_type(args.remote_root or '/tmp/umeko-network-real')
    assert remote_root.is_absolute(), '--remote-root must be absolute'
    remote = (remote_root / directory.name).as_posix()
    directory.mkdir(parents=True, exist_ok=False)
    for name in ('profile', 'agent', 'workspace', 'ssh-control'):
        (directory / name).mkdir()
    python = os.path.abspath(sys.executable)
    remote_python = args.remote_python or ('python' if args.platform == 'windows' else 'python3')
    spec = {'scenario': 'remote-network', 'runDir': str(directory), 'host': args.host,
            'platform': args.platform, 'remoteDirectory': remote, 'remotePython': remote_python,
            'commands': {phase: commands(args.platform, remote, remote_python, phase)
                         for phase in ('default', 'disabled', 'enabled', 'reconnected')},
            'bootstrapTimeout': 600 if args.platform == 'windows' else 240}
    if args.platform == 'linux':
        # Prove the UID egress block is effective before the application owns
        # any tunnel. A fresh direct request needs real bytes, not DNS alone.
        direct = subprocess.run(['ssh', '-o', 'BatchMode=yes', args.host,
                                 "env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u all_proxy curl -fS --noproxy '*' --connect-timeout 5 --max-time 8 https://example.com/ -o /dev/null"],
                                capture_output=True, text=True, timeout=25)
        assert direct.returncode != 0 and direct.returncode != 255, ('Direct baseline must fail after SSH succeeds', direct)
        spec['directBaseline'] = {'exitCode': direct.returncode, 'stderr': direct.stderr[-2000:]}
    settings = {'agent': {'agentDir': str(directory / 'agent'), 'autoCompaction': False, 'toolPermissionMode': 'auto'},
                'workspace': str(directory / 'workspace'), 'server': {'port': 0},
                'desktop': {'loginStartup': False}, 'providers': []}
    proxy = args.local_proxy or ('http://127.0.0.1:10818' if args.platform == 'windows' else None)
    if proxy:
        settings['remoteNetworkProxy'] = proxy
    (directory / 'profile/settings.json').write_text(json.dumps(settings), encoding='utf-8')
    spec_path = directory / 'spec.json'
    spec_path.write_text(json.dumps(spec, indent=2), encoding='utf-8')
    shim = directory / 'ssh-shim.py'
    shutil.copyfile(ROOT / 'tests/fixtures/remote_ssh_shim.py', shim)
    command = [str(args.app.resolve())] if args.app else [python, str(ROOT / 'main.py')]
    command += ['--remote-environments-smoke', str(spec_path)]
    env = dict(os.environ, UMEKO_DATA_DIR=str(directory / 'profile'), PI_CODING_AGENT_DIR=str(directory / 'agent'),
               QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software', PYTHONUTF8='1',
               UMEKO_SSH_TEST_CONTROL=str(directory / 'ssh-control'),
               UMEKO_TEST_SSH_COMMAND=json.dumps([python, str(shim)]),
               UMEKO_DIAGNOSTICS=str(directory / 'application.log'))
    for name in ('NODE_OPTIONS', 'NODE_PATH', 'UMEKO_REAL_SSH'):
        env.pop(name, None)
    with (directory / 'application-output.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        try:
            status = process.wait(timeout=1800)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=30)
            raise RuntimeError('Network acceptance deadline exceeded; stopped only the owned app')
    result_path = directory / 'result.json'
    result = json.loads(result_path.read_text(encoding='utf-8')) if result_path.exists() else {}
    if status != 0 or not result.get('ok'):
        print((directory / 'application-output.log').read_text(encoding='utf-8', errors='replace')[-16000:])
        raise RuntimeError(f'Network acceptance failed: exit={status}, result={result_path}')
    print(json.dumps({'ok': True, 'result': str(result_path), 'scenario': 'remote-network'}))


if __name__ == '__main__':
    main()
