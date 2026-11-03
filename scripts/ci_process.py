"""Wait for a CI process without waiting for inherited output-pipe EOF."""
import os
from pathlib import Path
import subprocess


def run_logged(command, output, *, timeout, env=None, cwd=None):
    # A descendant may inherit stdout after the process being checked exits.
    # A regular file keeps its output without making that descendant an exit gate.
    with Path(output).open("wb") as stream:
        return subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT,
            timeout=timeout, env=env, cwd=cwd,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
