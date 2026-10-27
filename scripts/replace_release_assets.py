"""Explicit same-tag replacement, after the publisher has verified every CI artifact."""
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path


def replace_published_release(repo, tag, commit, files, notes, gh, api, *, authorized=False):
    if not authorized:
        raise ValueError('Same-version replacement requires explicit authorization')
    assert repo in ('umeiko/umeko-desktop', 'umeiko/umeko-desktop-cpp')
    assert re.fullmatch(r'v\d+\.\d+\.\d+(?:-minimal)?', tag)
    assert re.fullmatch(r'[a-f0-9]{40}', commit)
    release = api('releases/tags/'+tag)
    if release.get('immutable'):
        raise RuntimeError('GitHub marks this release immutable; it cannot be overwritten')
    assert not release['draft']
    reference = api('git/ref/tags/'+tag)['object']
    assert reference['type'] == 'commit'
    assert reference['sha'] in (release['target_commitish'], commit)
    expected = {file.name: {'path': file, 'digest': 'sha256:'+hashlib.sha256(file.read_bytes()).hexdigest(), 'size':file.stat().st_size} for file in files}
    assert expected and len(expected) == len(files)
    prefix = 'umeko-replace-'+commit[:12]+'-'
    stage = files[0].parent/'replacement-stage'
    stage.mkdir(exist_ok=True)

    def matches(asset, wanted):
        return asset and asset['state']=='uploaded' and asset['digest']==wanted['digest'] and asset['size']==wanted['size']

    def current():
        return api('releases/'+str(release['id']))

    # Stage and verify every changed file before touching any published name.
    canonical, staged = {}, {}
    for name, wanted in expected.items():
        assets = current()['assets']
        existing = next((item for item in assets if item['name']==name), None)
        if matches(existing, wanted):
            canonical[name] = existing['id']
            continue
        temporary = prefix+name
        uploaded = next((item for item in assets if item['name']==temporary), None)
        if not uploaded:
            path = stage/temporary
            if not path.exists():
                os.link(wanted['path'], path)
            assert 'sha256:'+hashlib.sha256(path.read_bytes()).hexdigest()==wanted['digest']
            last_error = None
            for _ in range(3):
                try:
                    gh('release','upload',tag,path,'--repo',repo)
                except (subprocess.CalledProcessError, TimeoutError) as error:
                    last_error = error
                uploaded = next((item for item in current()['assets'] if item['name']==temporary), None)
                if matches(uploaded, wanted):
                    break
                if uploaded:
                    assert uploaded['state']=='starter' and uploaded['size']==0
                    gh('api','--method','DELETE',f'repos/{repo}/releases/assets/{uploaded["id"]}')
                    uploaded = None
            else:
                raise RuntimeError('Staged upload failed: '+name) from last_error
        assert matches(uploaded, wanted), name
        staged[name] = uploaded['id']
        print('Replacement staged and verified:', name, flush=True)

    before = current()
    assert {asset['id'] for asset in before['assets']} <= {asset['id'] for asset in release['assets']} | set(staged.values())
    assert api('git/ref/tags/'+tag)['object']['sha'] in (reference['sha'], commit)
    assert before['target_commitish'] in (release['target_commitish'], commit)
    keep = set(canonical.values()) | set(staged.values())
    old = [asset for asset in before['assets'] if asset['id'] not in keep]
    snapshot = files[0].parent/'previous-release.json'
    if not snapshot.exists():
        snapshot.write_text(json.dumps(before, indent=2), encoding='utf-8')
    for name, identifier in staged.items():
        previous = next((asset for asset in current()['assets'] if asset['name']==name), None)
        if previous:
            assert previous['id'] in {item['id'] for item in old}
            gh('api','--method','PATCH',f'repos/{repo}/releases/assets/{previous["id"]}', '-f',f'name=umeko-previous-{previous["id"]}-{name}')
        gh('api','--method','PATCH',f'repos/{repo}/releases/assets/{identifier}', '-f','name='+name)
        canonical[name] = identifier

    # Preserve the old bytes until the complete replacement set is confirmed.
    actual = current()
    for name, wanted in expected.items():
        asset = next(item for item in actual['assets'] if item['name']==name)
        assert asset['id']==canonical[name] and matches(asset, wanted), name
    if reference['sha'] != commit:
        gh('api','--method','PATCH',f'repos/{repo}/git/refs/tags/{tag}', '-f','sha='+commit, '-F','force=true')
    payload = stage/'release-metadata.json'
    payload.write_text(json.dumps({'target_commitish':commit, 'body':notes}), encoding='utf-8')
    gh('api','--method','PATCH',f'repos/{repo}/releases/{release["id"]}', '--input',payload)
    for asset in old:
        assert asset['id'] not in canonical.values()
        gh('api','--method','DELETE',f'repos/{repo}/releases/assets/{asset["id"]}')
    result = current()
    assert {asset['name'] for asset in result['assets']}==set(expected)
    assert result['target_commitish']==commit
    assert api('git/ref/tags/'+tag)['object']['sha']==commit
    for asset in result['assets']:
        assert matches(asset, expected[asset['name']])
    return result
