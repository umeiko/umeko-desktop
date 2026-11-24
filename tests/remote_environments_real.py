"""Run opt-in remote acceptance against a source app or a packaged Qt artifact.

Windows example (only the explicitly authorized SSH alias):
  python tests/remote_environments_real.py --app C:/path/Umeko.exe \
    --host my-ssh-alias --platform windows --run-root C:/remote-tests \
    --run-dir C:/remote-tests/run-01 --remote-root C:/remote-tests

No real profile, upstream model, visible window, focus operation or input injection.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath

ROOT = Path(__file__).resolve().parents[1]


def payload(directory, size):
    directory.mkdir()
    small_bytes = 0
    for index in range(256):
        folder = directory / f'group-{index % 16:02d}'
        folder.mkdir(exist_ok=True)
        data = os.urandom(4096)
        (folder / f'small-{index:04d}.bin').write_bytes(data)
        small_bytes += len(data)
    remaining = size - small_bytes
    assert remaining > 0
    with (directory / 'large.bin').open('wb') as handle:
        while remaining:
            data = os.urandom(min(1024 * 1024, remaining))
            handle.write(data)
            remaining -= len(data)


def unpack_application(archive, directory):
    """Unpack a downloaded PR artifact and its contained release zip."""
    directory.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            path = Path(member.filename.replace('\\', '/'))
            assert not path.is_absolute() and '..' not in path.parts, 'Unsafe artifact member'
            assert not member.external_attr >> 16 & 0o170000 == 0o120000, 'Artifact symlink is unsupported'
        bundle.extractall(directory)
    executables = list(directory.rglob('Umeko.exe'))
    if not executables:
        nested = list(directory.rglob('*.zip'))
        assert len(nested) == 1, ('Expected one Windows release zip', nested)
        return unpack_application(nested[0], directory / 'package')
    assert len(executables) == 1, ('Ambiguous packaged application', executables)
    return executables[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    executable = parser.add_mutually_exclusive_group(required=True)
    executable.add_argument('--app', type=Path, help='Unpacked PR Qt application executable')
    executable.add_argument('--source', action='store_true', help='Use this checkout and prepared Pi runtime')
    executable.add_argument('--artifact-zip', type=Path, help='Downloaded PR Windows package/artifact zip')
    executable.add_argument('--github-run-id', help='Download the Windows package from this PR Actions run')
    parser.add_argument('--github-artifact', default='Umeko-windows-x64')
    parser.add_argument('--github-repository', default='umeiko/umeko-desktop')
    parser.add_argument('--host', required=True, help='OpenSSH config alias for the authorized test host')
    parser.add_argument('--platform', choices=('windows', 'linux'), required=True)
    parser.add_argument('--run-dir', type=Path, required=True, help='A fresh isolated directory')
    parser.add_argument('--run-root', type=Path, help='Allowed local root for Windows acceptance')
    parser.add_argument('--remote-root', help='Allowed root for generated data on the remote host')
    parser.add_argument('--expected-ssh-executable', type=Path, help='Assert which SSH executable the application selects')
    parser.add_argument('--remote-python', default=None)
    parser.add_argument('--long-seconds', type=int, default=1200, help='Default acceptance requires 1200; smaller is diagnostic only')
    parser.add_argument('--payload-mib', type=int, default=200, help='Default acceptance requires 200; smaller is diagnostic only')
    parser.add_argument('--outage-seconds', type=int, default=125, help='Default acceptance requires >120 seconds')
    args = parser.parse_args()
    directory = args.run_dir.resolve()
    if args.platform == 'windows':
        if not args.run_root or not args.remote_root:
            parser.error('Windows acceptance requires --run-root and --remote-root')
        approved = args.run_root.resolve()
        assert approved in directory.parents, 'Windows run directory must be below --run-root'
    assert directory != ROOT and ROOT not in directory.parents, 'Run data must stay outside HB-Workspace checkout'
    assert args.long_seconds >= 1 and args.payload_mib >= 2 and args.outage_seconds >= 1
    inherited = [parent / name for parent in directory.parents
                 for name in ('AGENTS.md', 'CLAUDE.md') if (parent / name).is_file()]
    if inherited:
        raise RuntimeError('The isolated workspace would inherit agent instructions: ' + str(inherited[0]))
    remote_path = PureWindowsPath if args.platform == 'windows' else PurePosixPath
    remote_root = remote_path(args.remote_root or '/tmp/umeko-remote-real')
    if not remote_root.is_absolute():
        parser.error('--remote-root must be an absolute path on the remote host')
    expected_ssh = args.expected_ssh_executable.resolve(strict=True) if args.expected_ssh_executable else None
    directory.mkdir(parents=True, exist_ok=False)
    application = args.app.resolve() if args.app else None
    if application:
        assert application.is_file(), 'Packaged application is missing: ' + str(application)
    if args.github_run_id:
        downloaded = directory / 'artifact-download'
        subprocess.run(['gh', 'run', 'download', args.github_run_id, '--repo', args.github_repository,
                        '--name', args.github_artifact, '--dir', str(downloaded)], check=True, timeout=600)
        bundles = list(downloaded.rglob('*.zip'))
        assert len(bundles) == 1, ('Expected one release archive in Windows artifact', bundles)
        application = unpack_application(bundles[0], directory / 'application')
    elif args.artifact_zip:
        application = unpack_application(args.artifact_zip.resolve(), directory / 'application')
    (directory / 'profile').mkdir()
    (directory / 'agent').mkdir()
    (directory / 'workspace').mkdir()
    (directory / 'ssh-control').mkdir()
    payload_bytes = args.payload_mib * 1024 * 1024
    payload(directory / 'payload', payload_bytes)
    shim = directory / 'ssh-shim.py'
    shutil.copyfile(ROOT / 'tests/fixtures/remote_ssh_shim.py', shim)
    # Keep the venv launcher. Resolving its symlink would select the base
    # interpreter and hide the environment's Qt and gateway dependencies.
    python = os.path.abspath(sys.executable)
    spec = {'runDir': str(directory), 'host': args.host, 'platform': args.platform,
            'longSeconds': args.long_seconds, 'payloadBytes': payload_bytes,
            'outageSeconds': args.outage_seconds,
            'remoteDirectory': (remote_root / directory.name / 'payload').as_posix(),
            'acceptanceScope': args.long_seconds >= 1200 and args.payload_mib >= 200 and args.outage_seconds > 120}
    if args.platform == 'windows':
        # The current lab link is approximately 40--50 KB/s. Each high-entropy
        # 200 MiB direction alone needs 1.2--1.5 hours before JSON framing,
        # 257 files, reconnect waits and tool/RPC overhead. These outer limits
        # allow those real transfers rather than shrinking the acceptance data.
        spec.update(bootstrapTimeout=7200, uploadTimeout=14400, downloadTimeout=14400, recoveryTimeout=7200)
        spec['acceptanceScope'] = args.long_seconds == 1200 and args.payload_mib == 200 and args.outage_seconds == 125
    else:
        spec.update(bootstrapTimeout=240, uploadTimeout=900, downloadTimeout=900)
    if args.remote_python:
        spec['remotePython'] = args.remote_python
    if expected_ssh:
        spec['expectedSshExecutable'] = str(expected_ssh)
    spec_path = directory / 'spec.json'
    spec['applicationTimeout'] = (args.long_seconds + spec['bootstrapTimeout']
                                  + spec['uploadTimeout'] + spec['downloadTimeout']
                                  + (spec['recoveryTimeout'] + args.outage_seconds + 1200
                                     if args.platform == 'windows' else 600))
    spec_path.write_text(json.dumps(spec, indent=2), encoding='utf-8')
    settings = {'agent': {'agentDir': str(directory / 'agent'), 'autoCompaction': False, 'toolPermissionMode': 'auto'},
                'workspace': str(directory / 'workspace'), 'server': {'port': 0},
                'desktop': {'loginStartup': False}, 'providers': []}
    (directory / 'profile/settings.json').write_text(json.dumps(settings), encoding='utf-8')
    command = [str(application)] if application else [python, str(ROOT / 'main.py')]
    command += ['--remote-environments-smoke', str(spec_path)]
    env = dict(os.environ, UMEKO_DATA_DIR=str(directory / 'profile'), PI_CODING_AGENT_DIR=str(directory / 'agent'),
               QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software',
               UMEKO_SSH_TEST_CONTROL=str(directory / 'ssh-control'),
               UMEKO_TEST_SSH_COMMAND=json.dumps([python, str(shim)]), PYTHONUTF8='1',
               UMEKO_DIAGNOSTICS=str(directory / 'application.log'))
    env.pop('NODE_OPTIONS', None)
    env.pop('NODE_PATH', None)
    env.pop('UMEKO_REAL_SSH', None)
    print('Isolated real SSH acceptance: ' + str(spec_path), flush=True)
    with (directory / 'application-output.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        try:
            status = process.wait(timeout=spec['applicationTimeout'])
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=30)
            raise RuntimeError('Acceptance deadline exceeded; terminated only this launched application')
    result_path = directory / 'result.json'
    result = json.loads(result_path.read_text(encoding='utf-8')) if result_path.exists() else {}
    if status != 0 or not result.get('ok'):
        print((directory / 'application-output.log').read_text(encoding='utf-8', errors='replace')[-18000:])
        raise RuntimeError(f'Real SSH acceptance failed: exit={status}, result={result_path}')
    result['acceptanceScope'] = spec['acceptanceScope']
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(('REAL_REMOTE_ACCEPTANCE_PASSED' if spec['acceptanceScope'] else 'DIAGNOSTIC_ONLY_PASSED') + ': ' + str(result_path))


if __name__ == '__main__':
    main()
