"""Download a platform release asset without touching the installed application."""
from __future__ import annotations

import hashlib
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
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    name = asset['name']
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,199}', name):
        raise ValueError('更新包文件名无效')
    temporary = None
    try:
        request = urllib.request.Request(asset['url'], headers={'User-Agent':'Umeko updater', 'Accept-Encoding':'identity'})
        with urllib.request.urlopen(request, timeout=30) as response:
            final_url = response.geturl()
            if urllib.parse.urlsplit(final_url).scheme != 'https': raise ValueError('更新包下载地址必须使用 HTTPS')
            digest, received, previous = hashlib.sha256(), 0, -1
            with tempfile.NamedTemporaryFile(dir=directory, prefix='.umeko-', suffix='.part', delete=False) as output:
                temporary = Path(output.name)
                while chunk := response.read(256*1024):
                    if cancelled(): raise InterruptedError('下载已取消')
                    received += len(chunk)
                    if received > asset['size']: raise ValueError('更新包大小与发布信息不一致')
                    output.write(chunk); digest.update(chunk)
                    percent = received*100//asset['size']
                    if percent != previous: progress(percent); previous = percent
        if cancelled(): raise InterruptedError('下载已取消')
        if received != asset['size'] or digest.hexdigest() != asset['sha256']:
            raise ValueError('更新包校验失败，请重新下载')
        target, number = directory/name, 1
        while target.exists() or target.is_symlink():
            target = directory/(Path(name).stem+f'-{number}'+Path(name).suffix)
            number += 1
        os.replace(temporary, target)
        temporary = None
        return str(target)
    finally:
        if temporary is not None: temporary.unlink(missing_ok=True)
