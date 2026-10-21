"""Publish only complete, successful main-branch build artifacts, without rebuilding."""
from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import subprocess
import time

REPO=os.environ['GITHUB_REPOSITORY']
RUN=os.environ['RELEASE_BUILD_RUN']
TAG=os.environ['RELEASE_TAG']
assert re.fullmatch(r'\d+',RUN) and re.fullmatch(r'v\d+\.\d+\.\d+',TAG)
minimal=False
version=TAG.removeprefix('v')
assert REPO=='umeiko/umeko-desktop'

def gh(*args):
    return subprocess.check_output(['gh',*map(str,args)],text=True)

def api(path):
    separator='&' if '?' in path else '?'
    return json.loads(gh('api',f'repos/{REPO}/'+path+separator+'_umeko='+str(time.time_ns())))

run=api('actions/runs/'+RUN)
assert run['conclusion']=='success' and run['head_branch']=='main'
assert run['head_repository']['full_name']==REPO and run['event'] in ('push','workflow_dispatch')
assert run['path']=='.github/workflows/build.yml'
commit=run['head_sha']
base=Path('.release');incoming=base/'input';publish=base/'publish'
publish.mkdir(parents=True,exist_ok=True)
gh('run','download',RUN,'--repo',REPO,'--pattern','Umeko-*','--dir',incoming)
platforms={'windows-x64','macos-arm64','macos-x64','linux-x64'}
seen=set();sizes=[]
for metadata in incoming.rglob('build.json'):
    report=json.loads(metadata.read_text(encoding='utf-8'))
    target=report['platform'];assert target in platforms and target not in seen
    assert report['build']['commit']==commit and report['build']['version']==version
    assert report['gui']=='passed' and report['pi']=='passed'
    assert report['build']['node']['version']=='22.23.3'
    seen.add(target)
    suffix='.tar.gz' if target=='linux-x64' else '.zip'
    archive=metadata.with_name(report['archive'])
    assert archive.name.startswith('Umeko-'+version+'-'+target+'-') and archive.name.endswith(suffix)
    checksum=archive.with_name(archive.name+'.sha256')
    assert archive.stat().st_size>0
    digest=hashlib.sha256(archive.read_bytes()).hexdigest()
    assert digest==report['sha256'] and checksum.read_text().split()[0]==digest
    shutil.copy2(metadata,publish/('Umeko-'+TAG+'-'+target+'.json'))
    for file in [archive,checksum]:shutil.copy2(file,publish/file.name)
    sizes.append((target,archive.stat().st_size))
assert seen==platforms
for name in ['umeko-provider-sdk-0.1.0.zip','develop-umeko-provider.zip']:
    matches=list(incoming.rglob(name));assert len(matches)==1
    shutil.copy2(matches[0],publish/name)
files=sorted(publish.iterdir(),key=lambda p:p.name.casefold())
assert len(files)==14
(publish/'SHA256SUMS.txt').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in files),encoding='ascii',newline='\n')
files=sorted(publish.iterdir(),key=lambda p:p.stat().st_size)
releases=api('releases')
release=next((r for r in releases if r['tag_name']==TAG),None)
if release is None:
    notes=base/'notes.md'
    notes.write_text('Fix standalone startup on computers without Node.js installed.\n\n- Bundles official Node.js 22.23.3 and npm alongside Python, Qt and Pi.\n- Chat, extension installation, the Pi terminal and kernel updates use the bundled runtime.\n- Every package is checked with system Node removed from PATH.\n\nExtract the complete archive; no separate Node.js or Python installation is required. Existing Provider SDK v1 ZIPs remain compatible.\n\nVerified CI: https://github.com/'+REPO+'/actions/runs/'+RUN+'\n\n'+''.join(f'- {p}: {n/1048576:.2f} MiB\n' for p,n in sizes),encoding='utf-8')
    payload=base/'create-release.json'
    payload.write_text(json.dumps({'tag_name':TAG,'target_commitish':commit,'name':TAG,
                                  'draft':True,'prerelease':minimal,'body':notes.read_text(encoding='utf-8')}),encoding='utf-8')
    release=json.loads(gh('api','--method','POST',f'repos/{REPO}/releases','--input',payload))
assert release['target_commitish']==commit
rid=release['id']
for file in files:
    digest='sha256:'+hashlib.sha256(file.read_bytes()).hexdigest()
    for attempt in range(3):
        actual=api('releases/'+str(rid))
        row=next((r for r in actual['assets'] if r['name']==file.name),None)
        if row and file.name=='SHA256SUMS.txt' and row['digest']!=digest:
            assert actual['draft']
            previous=gh('release','download',TAG,'--repo',REPO,'--pattern',file.name,'--output','-')
            assert previous.splitlines()==file.read_text(encoding='ascii').splitlines(),'Checksum entries changed'
            gh('api','--method','DELETE','repos/'+REPO+'/releases/assets/'+str(row['id']))
            row=None
            print('Normalized draft checksum line endings to LF',flush=True)
        if row and row['state']=='uploaded':
            assert row['digest']==digest and row['size']==file.stat().st_size,file.name
            print('Verified:',file.name,flush=True);break
        assert actual['draft'],'Never modify a published release'
        if row:
            assert row['state']=='starter' and row['size']==0
            gh('api','--method','DELETE','repos/'+REPO+'/releases/assets/'+str(row['id']))
        result=subprocess.run(['gh','release','upload',TAG,str(file),'--repo',REPO],timeout=300)
        if result.returncode:time.sleep(3)
        else:
            uploaded=next(r for r in api('releases/'+str(rid))['assets'] if r['name']==file.name)
            assert uploaded['digest']==digest and uploaded['size']==file.stat().st_size
            print('Uploaded and verified:',file.name,flush=True)
            break
    else:raise RuntimeError('Asset upload failed: '+file.name)
actual=api('releases/'+str(rid))
assert {r['name'] for r in actual['assets']}=={f.name for f in files}
for file in files:
    row=next(r for r in actual['assets'] if r['name']==file.name)
    assert row['state']=='uploaded' and row['digest']=='sha256:'+hashlib.sha256(file.read_bytes()).hexdigest()
if actual['draft']:gh('release','edit',TAG,'--repo',REPO,'--draft=false',*(['--latest=false'] if minimal else ['--latest']))
published=api('releases/'+str(rid));assert not published['draft'] and published['prerelease']==minimal
if not minimal:
    latest=api('releases/latest');assert latest['tag_name']==TAG and not latest['prerelease']
assert api('git/ref/tags/'+TAG)['object']['sha']==commit
print('Published:',published['html_url'],flush=True)
with open(os.environ['GITHUB_STEP_SUMMARY'],'a',encoding='utf-8') as out:
    out.write('Published ['+TAG+']('+published['html_url']+') from verified build ['+RUN+'](https://github.com/'+REPO+'/actions/runs/'+RUN+'). All 15 server-side asset digests verified.\n')
