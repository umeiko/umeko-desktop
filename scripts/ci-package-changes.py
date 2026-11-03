"""Compare the tested PR merge with its base; unknown paths build by default."""
import os
import subprocess
from pathlib import Path


def needs_packages(paths):
    # These are documentation inputs, never copied into the desktop packages.
    # README.md, skill/provider docs and runtime Markdown ARE packaged inputs.
    return any(not (path.startswith(('docs/', 'docs-site/', 'tests/'))
                        or path in ('scripts/capture-documentation.py',
                                    '.github/workflows/docs.yml')) for path in paths)


if __name__ == '__main__':
    result = subprocess.run(
        ['git', 'diff', '--name-only', '-z', os.environ['PR_BASE'], 'HEAD'],
        check=True, capture_output=True,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    paths = result.stdout.decode('utf-8', errors='surrogateescape').split('\0')
    # Tests and contributor-only CI notes don't change packaging. All other
    # unclassified paths fail open, including dependency and workflow changes.
    paths = [p for p in paths if p]
    packages = needs_packages(paths)
    with Path(os.environ['GITHUB_OUTPUT']).open('a', encoding='utf-8') as output:
        output.write(f'packages={str(packages).lower()}\n')
    print(f'Native packages required: {packages}')
