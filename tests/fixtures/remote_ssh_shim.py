"""Proxy only acceptance-owned SSH children and inject a scoped network outage.

No global process lookup, firewall change, SSH daemon control or proxy access.
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def main():
    control = Path(os.environ['UMEKO_SSH_TEST_CONTROL']).resolve()
    control.mkdir(parents=True, exist_ok=True)
    if (control / 'blocked').exists():
        # Model an actual ConnectTimeout. This preserves the production 60s
        # retry waits while permitting >120s outage before the final retry.
        time.sleep(10)
        print('acceptance-owned SSH connection timed out', file=sys.stderr)
        return 255
    ssh = os.environ.get('UMEKO_REAL_SSH') or shutil.which('ssh')
    if not ssh:
        raise RuntimeError('OpenSSH client is missing')
    arguments = sys.argv[1:]
    process = subprocess.Popen([ssh, *arguments], creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    # The transport's persistent client forwards the websocket port with -L.
    tunnel = any(arg == '-L' or arg.startswith('-L') for arg in arguments)
    with (control / 'clients.jsonl').open('a', encoding='utf-8') as handle:
        handle.write(json.dumps({'pid': process.pid, 'ownerPid': os.getpid(), 'tunnel': tunnel, 'argv': arguments}) + '\n')
    try:
        return process.wait()
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)


if __name__ == '__main__':
    sys.exit(main())
