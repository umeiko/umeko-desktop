"""Download a platform release asset without touching the installed application."""
from __future__ import annotations

import os
from pathlib import Path
import platform
import re
import tempfile
import urllib.parse
import urllib.request


def platform_target(system=None, architecture=None):
    system = system or platform.system()
    architecture = (architecture or platform.machine()).lower()
    arch = 'arm64' if architecture in ('arm64', 'aarch64') else 'x64' if architecture in ('amd64', 'x86_64', 'x64') else ''
    family = {'Windows':'windows', 'Darwin':'macos', 'Linux':'linux'}.get(system, '')
    return family+'-'+arch if family and arch else ''


def select_asset(data, project_url, target, native=False, minimal=False):
    tag = str(data.get('tag_name', ''))
    version = tag.removeprefix('v').removesuffix('-minimal')
    if not target or not re.fullmatch(r'\d+\.\d+\.\d+', version): return {}
    extension = '.tar.gz' if target.startswith('linux-') else '.zip'
    pattern = (re.escape('UmekoCpp-v'+version+('-minimal' if minimal else '')+'-'+target+extension)
               if native else re.escape('Umeko-'+version+'-'+target+'-')+r'[a-f0-9]{7,40}'+re.escape(extension))
    matches = []
    for asset in data.get('assets') or []:
        name = str(asset.get('name', ''))
        url = str(asset.get('browser_download_url', ''))
        digest = str(asset.get('digest', ''))
        size = asset.get('size', 0)
        expected = project_url+'/releases/download/'+tag+'/'+urllib.parse.quote(name)
        if (re.fullmatch(pattern, name) and url == expected and re.fullmatch(r'sha256:[a-f0-9]{64}', digest)
                and type(size) is int and 0 < size <= 2*1024**3):
            matches.append({'name':name, 'url':url, 'sha256':digest[7:], 'size':size})
    return matches[0] if len(matches) == 1 else {}


def download_asset(asset, directory, progress, cancelled):
    # Same engine / resume format as C++; this function runs in controller._job.
    import json
    import subprocess
    import sys
    import threading
    from .pi_runtime import node_executable, CREATE_NO_WINDOW
    from .update_proxy import system_proxy
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    name = asset['name']
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,199}', name):
        raise ValueError('更新包文件名无效')
    url = urllib.parse.urlsplit(asset['url'])
    match = re.fullmatch(r'/umeiko/(umeko-desktop(?:-cpp)?)/releases/download/([^/]+)/[^/]+', url.path)
    if url.scheme != 'https' or url.netloc != 'github.com' or not match:
        raise ValueError('更新包下载地址无效')
    if cancelled(): raise InterruptedError('下载已暂停，进度已保存')
    proxy = system_proxy(asset['url'])
    from .update import update_environment
    qt_environment = update_environment()
    environment = {key:qt_environment.value(key) for key in qt_environment.keys()}
    environment['UMEKO_UPDATE_PROXY'] = proxy
    root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
    job = dict(repo=match[1], version=urllib.parse.unquote(match[2]), cache=str(directory),
               asset=dict(name=name, url=asset['url'], bytes=asset['size'], sha256=asset['sha256']))
    with tempfile.TemporaryDirectory(prefix='umeko-download-job-') as temp:
        job_file = Path(temp)/'job.json'
        job_file.write_text(json.dumps(job), encoding='utf-8'); job_file.chmod(0o600)
        process = subprocess.Popen([node_executable(), str(root/'runtime/update-engine.mjs'), 'download', str(job_file)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            encoding='utf-8', env=environment, creationflags=CREATE_NO_WINDOW)
        stopped = threading.Event()
        def watch_cancel():
            while not stopped.wait(.1):
                if cancelled():
                    try: process.stdin.write('pause\n'); process.stdin.flush()
                    except (BrokenPipeError, OSError): pass
                    if not stopped.wait(3) and process.poll() is None: process.kill()
                    return
        watcher = threading.Thread(target=watch_cancel, daemon=True); watcher.start()
        last = {}
        try:
            for line in process.stdout:
                try: value = json.loads(line)
                except ValueError: continue
                if not isinstance(value, dict) or 'state' not in value: continue
                last = value
                progress({**value, 'route':'系统代理' if proxy else '直连'})
            process.wait()
            if last.get('state') == 'ready': return last['archive']
            if cancelled() or last.get('state') == 'paused': raise InterruptedError('下载已暂停，进度已保存')
            raise ValueError(last.get('message') or '下载引擎意外退出，已保存下载进度，请继续下载')
        finally:
            stopped.set(); watcher.join(1)
            if process.poll() is None: process.kill(); process.wait()
            process.stdout.close(); process.stdin.close()
