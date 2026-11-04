"""Replace the rolling Windows Preview after trusted main-branch CI succeeds."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.preview_release import collect_assets, require, verify_uploaded


REPOSITORY = 'umeiko/umeko-desktop'
PLATFORMS = ['windows-x64']
PACKAGE_JOBS = {'Windows x64', 'Linux x64', 'macOS Apple Silicon', 'macOS Intel'}


class GitHub:
    def __init__(self, repo, token):
        self.repo, self.token = repo, token

    def api(self, path, method='GET', data=None, missing_ok=False):
        if method == 'GET':
            separator = '&' if '?' in path else '?'
            path += separator + '_umeko=' + str(time.time_ns())
        request = urllib.request.Request(
            f'https://api.github.com/repos/{self.repo}/{path}',
            data=json.dumps(data).encode('utf-8') if data is not None else None,
            headers={'Authorization': 'Bearer ' + self.token,
                     'Accept': 'application/vnd.github+json',
                     'X-GitHub-Api-Version': '2022-11-28',
                     'Content-Type': 'application/json'}, method=method)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = response.read()
                return json.loads(body) if body else None
        except urllib.error.HTTPError as error:
            if error.code == 404 and missing_ok:
                return None
            raise

    def pages(self, path, key=None):
        rows, page = [], 1
        while True:
            result = self.api(f'{path}?per_page=100&page={page}')
            items = result[key] if key else result
            rows.extend(items)
            if len(items) < 100:
                return rows
            page += 1

    def gh(self, *args):
        return subprocess.check_output(['gh', *map(str, args)], text=True)


def verify_ci_run(client, run, commit):
    require(run.isdigit() and re.fullmatch(r'[0-9a-f]{40}', commit), 'Invalid CI provenance')
    metadata = client.api(f'actions/runs/{run}')
    require(metadata['head_repository']['full_name'] == REPOSITORY
            and metadata['path'] == '.github/workflows/build.yml'
            and metadata['event'] in ('push', 'workflow_dispatch')
            and metadata['head_branch'] == 'main'
            and metadata['head_sha'] == commit
            and metadata['status'] in ('in_progress', 'completed')
            and metadata['conclusion'] in (None, 'success'), 'Not a trusted main CI build')
    # The final job can start before the REST replica reflects its successful
    # dependencies. Refresh briefly, while still rejecting real failed checks.
    for attempt in range(6):
        jobs = client.pages(f'actions/runs/{run}/jobs', 'jobs')
        relevant = [job for job in jobs if job['name'] in PACKAGE_JOBS | {'checks'}]
        require(not any(job['conclusion'] in ('failure', 'cancelled', 'timed_out', 'action_required')
                        for job in relevant), 'Tests and selected native packages must pass')
        names = {job['name'] for job in relevant if job['conclusion'] == 'success'}
        if {'checks', 'Windows x64'} <= names and all(job['conclusion'] == 'success' for job in relevant):
            return
        if attempt < 5:
            time.sleep(2)
    require(False, 'Tests and Windows package must pass (status refresh timed out)')


def current_preview(client):
    # Listing includes drafts, unlike releases/tags for an unpublished tag.
    return next((release for release in client.pages('releases')
                 if release['tag_name'] == 'preview'), None)


def main_is_current(client, commit):
    return client.api('branches/main')['commit']['sha'] == commit


def replace_preview(client, commit, files, notes, run, attempt):
    previous = current_preview(client)
    if previous:
        require(not previous.get('immutable'), 'The existing Preview is immutable')
        require(previous['prerelease'] or previous['draft'], 'Refusing to replace a stable release')
    tag = f'preview-staging-{run}-{attempt}'
    staged = client.api('releases', 'POST', dict(
        tag_name=tag, target_commitish=commit, name='Umeko Preview', body=notes,
        draft=True, prerelease=True, make_latest='false'))
    endpoint = f'releases/{staged["id"]}'
    cutover_started = False
    try:
        for path in sorted(files, key=lambda file: file.stat().st_size):
            client.gh('release', 'upload', tag, path, '--repo', REPOSITORY)
        ready = client.api(endpoint)
        require(ready['draft'] and ready['prerelease'] and ready['target_commitish'] == commit,
                'Unexpected staging release')
        verify_uploaded(ready, files)
        if not main_is_current(client, commit):
            return None
        latest = current_preview(client)
        require((latest or {}).get('id') == (previous or {}).get('id'),
                'The Preview changed during upload')
        cutover_started = True
        if previous:
            client.api(f'releases/{previous["id"]}', 'DELETE')
        if client.api('git/ref/tags/preview', missing_ok=True):
            client.api('git/refs/tags/preview', 'DELETE')
        client.api('git/refs', 'POST', {'ref': 'refs/tags/preview', 'sha': commit})
        client.api(endpoint, 'PATCH', dict(tag_name='preview', target_commitish=commit,
                                          draft=False, prerelease=True, make_latest='false'))
        published = client.api(endpoint)
        require(not published['draft'] and published['prerelease']
                and published['tag_name'] == 'preview'
                and published['target_commitish'] == commit, 'Preview was not published')
        require(client.api('git/ref/tags/preview')['object']['sha'] == commit,
                'Preview tag points at another commit')
        verify_uploaded(published, files)
        return published
    finally:
        # Before cutover the old Preview remains available. After cutover,
        # retain the verified draft on failure so an upload need not be repeated.
        if not cutover_started:
            client.api(endpoint, 'DELETE')


def publish(environment=None, client=None, base=None):
    env = os.environ if environment is None else environment
    repo, run, commit = env['GITHUB_REPOSITORY'], env['GITHUB_RUN_ID'], env['GITHUB_SHA']
    attempt = env['GITHUB_RUN_ATTEMPT']
    require(repo == REPOSITORY and env['GITHUB_REF'] == 'refs/heads/main'
            and env['GITHUB_EVENT_NAME'] in ('push', 'workflow_dispatch'), 'Preview requires main CI')
    require(attempt.isdigit(), 'Invalid run attempt')
    client = client or GitHub(repo, env['GH_TOKEN'])
    verify_ci_run(client, run, commit)
    if not main_is_current(client, commit):
        print('A newer main commit exists; keeping the current Preview.', flush=True)
        return None
    base = Path('.ci-preview-release') if base is None else base
    incoming, output = base / 'input', base / 'publish'
    client.gh('run', 'download', run, '--repo', repo, '--name', 'Umeko-windows-x64',
              '--dir', incoming / 'Preview-windows-x64')
    version = collect_assets(incoming, output, PLATFORMS, commit)
    notes = (f'## Umeko {version} Preview\n\n'
             'main 的最新已验证 Windows x64 预览包，后续成功 CI 会替换此预发布版本。\n\n'
             f'- Source: https://github.com/{repo}/commit/{commit}\n'
             f'- Verified CI: https://github.com/{repo}/actions/runs/{run}\n'
             '- GUI、Pi、终端与完整 CI 测试已通过；附构建信息和 SHA-256 校验文件。\n')
    release = replace_preview(client, commit, sorted(output.iterdir()), notes, run, attempt)
    if release:
        with open(env['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as summary:
            summary.write(f'Published rolling Windows [Preview]({release["html_url"]}) '
                          f'from `{commit}`. Uploaded sizes and SHA-256 digests verified.\n')
        print(release['html_url'], flush=True)
    return release


if __name__ == '__main__':
    publish()
