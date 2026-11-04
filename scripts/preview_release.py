"""Select native Preview builds and publish their verified artifacts as a prerelease."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess


PLATFORMS = {
    'windows-x64': ('Windows x64', 'windows-2022'),
    'linux-x64': ('Linux x64', 'ubuntu-22.04'),
    'macos-arm64': ('macOS Apple Silicon', 'macos-15'),
    'macos-x64': ('macOS Intel', 'macos-15-intel'),
}


def select_matrix(inputs):
    rows = [dict(platform=platform, name=name, runner=runner)
            for platform, (name, runner) in PLATFORMS.items()
            if inputs.get(platform.replace('-', '_')) is True]
    if not rows:
        raise ValueError('Select at least one Preview platform')
    return {'include': rows}


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def checked_asset(folder, name, expected_hash, expected_size=None):
    require(isinstance(name, str) and name not in ('', '.', '..')
            and '/' not in name and '\\' not in name, 'Unsafe asset name')
    path = folder / name
    require(path.is_file() and not path.is_symlink(), f'Missing asset: {name}')
    require(path.stat().st_size > 0, f'Empty asset: {name}')
    if expected_size is not None:
        require(path.stat().st_size == expected_size, f'Wrong size: {name}')
    require(digest(path) == expected_hash, f'Wrong digest: {name}')
    checksum = path.with_name(name + '.sha256')
    require(checksum.read_text(encoding='utf-8').split() == [expected_hash, name],
            f'Invalid checksum file: {name}')
    return [path, checksum]


def collect_assets(incoming, output, platforms, commit):
    require(bool(platforms) and len(platforms) == len(set(platforms))
            and set(platforms) <= PLATFORMS.keys(), 'Invalid selected platforms')
    require(re.fullmatch(r'[0-9a-f]{40}', commit), 'Invalid source commit')
    output.mkdir(parents=True, exist_ok=True)
    require(not any(output.iterdir()), 'Publish directory must be empty')
    versions = set()
    for platform in platforms:
        folder = incoming / ('Preview-' + platform)
        metadata = folder / 'build.json'
        report = json.loads(metadata.read_text(encoding='utf-8'))
        build = report['build']
        require(report['platform'] == platform and build['commit'] == commit,
                'Artifact platform or source commit mismatch')
        # build_icons.py regenerates tracked assets before recording metadata.
        # The selected commit and successful native CI job establish provenance;
        # retain the accurate dirty marker in the attached manifest.
        version = build['version']
        require(re.fullmatch(r'\d+\.\d+\.\d+', version), 'Invalid version')
        versions.add(version)
        require(all(report.get(key) == 'passed' for key in ('gui', 'pi', 'terminal')),
                'Packaged GUI, Pi and terminal must pass')
        if 'https' in report:
            require(report['https'] == 'passed', 'Packaged HTTPS must pass')
        suffix = '.tar.gz' if platform == 'linux-x64' else '.zip'
        require(report['archive'] == f'Umeko-{version}-{platform}-{commit[:7]}{suffix}',
                'Unexpected archive name')
        assets = checked_asset(folder, report['archive'], report['sha256'])
        if platform.startswith('macos-'):
            disk = report['diskImage']
            require(disk['name'] == report['archive'].removesuffix('.zip') + '.dmg',
                    'Unexpected disk image name')
            assets += checked_asset(folder, disk['name'], disk['sha256'], disk['bytes'])
        for asset in assets:
            shutil.copy2(asset, output / asset.name)
        shutil.copy2(metadata, output / f'Umeko-preview-{platform}.json')
    require(len(versions) == 1, 'Selected packages have different versions')
    files = sorted(output.iterdir())
    (output / 'SHA256SUMS.txt').write_text(
        ''.join(f'{digest(path)}  {path.name}\n' for path in files), encoding='ascii')
    return versions.pop()


def gh(*args):
    return subprocess.check_output(['gh', *map(str, args)], text=True)


def verify_build_run(repo, run, platforms):
    require(run.isdigit(), 'Invalid build run')
    metadata = json.loads(gh('api', f'repos/{repo}/actions/runs/{run}'))
    require(metadata['head_repository']['full_name'] == repo
            and metadata['path'] == '.github/workflows/preview.yml'
            and metadata['event'] == 'workflow_dispatch', 'Not a trusted Preview build')
    jobs = json.loads(gh('api', f'repos/{repo}/actions/runs/{run}/jobs?per_page=100'))['jobs']
    for platform in platforms:
        name = 'Preview ' + PLATFORMS[platform][0]
        require(any(job['name'] == name and job['conclusion'] == 'success' for job in jobs),
                f'No successful native package job for {platform}')


def verify_uploaded(release, files):
    rows = {row['name']: row for row in release['assets']}
    require(set(rows) == {path.name for path in files}, 'Release assets do not match')
    for path in files:
        row = rows[path.name]
        require(row['state'] == 'uploaded' and row['size'] == path.stat().st_size
                and row['digest'] == 'sha256:' + digest(path),
                f'Uploaded asset verification failed: {path.name}')


def publish():
    repo = os.environ['GITHUB_REPOSITORY']
    run = os.environ['GITHUB_RUN_ID']
    attempt = os.environ['GITHUB_RUN_ATTEMPT']
    build_run = os.environ.get('PREVIEW_BUILD_RUN') or run
    commit = os.environ['PREVIEW_COMMIT']
    platforms = json.loads(os.environ['PREVIEW_PLATFORMS'])
    require(repo == 'umeiko/umeko-desktop', 'Unexpected repository')
    require(run.isdigit() and attempt.isdigit(), 'Invalid workflow run')
    if build_run != run:
        verify_build_run(repo, build_run, platforms)
    base = Path('.preview-release')
    incoming, output = base / 'input', base / 'publish'
    # Only this run's selected package artifacts; no older build or SDK assets.
    for platform in platforms:
        require(platform in PLATFORMS, 'Invalid platform')
        gh('run', 'download', build_run, '--repo', repo, '--name', 'Preview-' + platform,
           '--dir', incoming / ('Preview-' + platform))
    version = collect_assets(incoming, output, platforms, commit)
    tag = f'preview-v{version}-{run}-{attempt}'
    files = sorted(output.iterdir(), key=lambda path: path.stat().st_size)
    notes = base / 'notes.md'
    notes.write_text(
        f'## Umeko {version} Preview\n\n'
        + os.environ.get('PREVIEW_NOTES', '').strip() + '\n\n'
        + '手动构建的实验预览版，不替换正式版 Latest。 / Manually built experimental prerelease.\n\n'
        + f'- Source: [{commit}](https://github.com/{repo}/commit/{commit})\n'
        + f'- Platforms: {", ".join(platforms)}\n'
        + f'- Verified build: https://github.com/{repo}/actions/runs/{build_run}\n'
        + f'- Publication: https://github.com/{repo}/actions/runs/{run}\n'
        + '- Packaged GUI, Pi and terminal checks passed; build manifests and SHA-256 checksums are attached.\n',
        encoding='utf-8')
    # A unique tag per run attempt avoids overwriting another experiment.
    gh('release', 'create', tag, '--repo', repo, '--target', commit,
       '--title', f'Umeko {version} Preview ({run}.{attempt})',
       '--notes-file', notes, '--draft', '--prerelease', '--latest=false')
    for path in files:
        gh('release', 'upload', tag, path, '--repo', repo)
    release = json.loads(gh('api', f'repos/{repo}/releases/tags/{tag}'))
    require(release['draft'] and release['prerelease']
            and release['target_commitish'] == commit, 'Unexpected draft release')
    verify_uploaded(release, files)
    gh('release', 'edit', tag, '--repo', repo, '--draft=false', '--prerelease', '--latest=false')
    release = json.loads(gh('api', f'repos/{repo}/releases/tags/{tag}'))
    require(not release['draft'] and release['prerelease'], 'Preview was not published')
    actual_tag = json.loads(gh('api', f'repos/{repo}/git/ref/tags/{tag}'))
    require(actual_tag['object']['sha'] == commit, 'Preview tag points at another commit')
    verify_uploaded(release, files)
    url = release['html_url']
    with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as stream:
        stream.write(f'Published [Preview]({url}) for {", ".join(platforms)}. All uploaded digests verified.\n')
    print(url, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'publish'])
    args = parser.parse_args()
    if args.command == 'publish':
        publish()
        return
    matrix = select_matrix(json.loads(os.environ['PREVIEW_INPUTS']))
    commit = subprocess.check_output(['git', '-C', 'source', 'rev-parse', 'HEAD'], text=True).strip()
    require(re.fullmatch(r'[0-9a-f]{40}', commit), 'Invalid source commit')
    values = {'matrix': json.dumps(matrix), 'commit': commit,
              'platforms': json.dumps([row['platform'] for row in matrix['include']])}
    with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as stream:
        stream.write(''.join(f'{key}={value}\n' for key, value in values.items()))


if __name__ == '__main__':
    main()
