"""Provision an optional, verified Quick OCR runtime without changing the app installation."""
from __future__ import annotations

import argparse
from http.client import HTTPException
from tempfile import TemporaryFile
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import time
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


BLOCK = 1024 * 1024
ORIGINS = {'github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com', 'files.pythonhosted.org'}


class InstallCancelled(Exception):
    pass


def paths(root, component):
    lock = (root / 'app/quick_ocr_components.json').read_bytes()
    machine = {'amd64': 'x86_64', 'arm64': 'aarch64'}.get(platform.machine().lower(), platform.machine().lower())
    key = f'{sys.platform}-{machine}'
    spec = json.loads(lock)['platforms'].get(key)
    fingerprint = hashlib.sha256(lock + key.encode()).hexdigest()
    target = component / f'runtime-{fingerprint[:16]}'
    return spec, fingerprint, target


def interpreter(directory):
    return directory / ('python/python.exe' if os.name == 'nt' else 'python/bin/python3.12')


def ready(directory, fingerprint):
    try:
        return (directory / 'verified').read_text(encoding='ascii') == fingerprint and interpreter(directory).is_file()
    except (OSError, UnicodeError):
        return False


def cleaned_env(scratch=None):
    env = {k: v for k, v in os.environ.items() if k not in ('PYTHONHOME','PYTHONPATH','PYTHONUSERBASE','PYTHONEXECUTABLE','__PYVENV_LAUNCHER__')
           and not k.startswith('_PYI_')}
    if 'LD_LIBRARY_PATH_ORIG' in env:
        env['LD_LIBRARY_PATH'] = env.pop('LD_LIBRARY_PATH_ORIG')
    elif getattr(sys, 'frozen', False):
        env.pop('LD_LIBRARY_PATH', None)
    if scratch is not None:
        env.update(TMPDIR=str(scratch), TMP=str(scratch), TEMP=str(scratch))
    return env


def _trusted(url):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname not in ORIGINS or parsed.username or parsed.password or parsed.port not in (None,443):
        raise ValueError('Unexpected OCR download origin')


class Redirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _trusted(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _fetch(asset, destination, check, cache=None):
    name = asset['name']
    if name != Path(name).name or '/' in name or '\\' in name:
        raise ValueError('Invalid asset name')
    url = asset['url']
    _trusted(url)
    candidate = destination / name
    for attempt in range(2):
        check()
        try:
            source = (cache / name).open('rb') if cache is not None else build_opener(Redirects()).open(Request(url, headers={'User-Agent': 'Umeko-Quick-OCR/1'}), timeout=12)
            with source, candidate.open('wb') as out:
                digest = hashlib.sha256()
                size = 0
                while chunk := source.read(BLOCK):
                    check()
                    size += len(chunk)
                    if size > asset['size']:
                        raise ValueError('Incorrect OCR asset size')
                    digest.update(chunk)
                    out.write(chunk)
                if size != asset['size'] or digest.hexdigest() != asset['sha256']:
                    raise ValueError('Incorrect OCR asset checksum')
            return candidate
        except (OSError, URLError, HTTPException) as error:
            if cache is not None or attempt == 1:
                reason = getattr(error, 'reason', error)
                status = getattr(error, 'code', None)
                raise RuntimeError(f'{name}: {type(reason).__name__}' + (f' HTTP {status}' if status else '')) from error
            time.sleep(0.15)
    raise AssertionError('unreachable')


def _run(command, cwd, check):
    with TemporaryFile(dir=cwd) as output, subprocess.Popen(command, cwd=cwd, env=cleaned_env(cwd),
            stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0) as child:
        until = time.monotonic() + 210
        try:
            while child.poll() is None:
                check()
                if time.monotonic() > until:
                    raise TimeoutError('OCR installation process timed out')
                time.sleep(.05)
        finally:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
        if child.returncode:
            raise RuntimeError('OCR runtime preparation did not complete')
        output.seek(0)
        return output.read(4096)


def install(root, component, stage, cancel, cache=None):
    spec, fingerprint, target = paths(root, component)
    if spec is None:
        raise ValueError('Unsupported Quick OCR platform')
    if ready(target, fingerprint):
        return

    def check():
        if cancel.exists():
            raise InstallCancelled

    staging = stage / 'candidate'
    downloads = stage / 'downloads'
    scratch = stage / 'tmp'
    for directory in (staging, downloads, scratch):
        directory.mkdir()
    py_asset = _fetch(spec['python'], downloads, check, cache)

    def members(archive):
        for member in archive:
            check()
            yield member

    with tarfile.open(py_asset, 'r:gz', copybufsize=BLOCK) as archive:
        archive.extractall(staging, members=members(archive), filter='data')
    wheels = [_fetch(asset, downloads, check, cache) for asset in spec['wheels']]
    python = str(interpreter(staging))
    site = staging / 'site'
    _run([python, '-I', '-m', 'pip', '--isolated', '--disable-pip-version-check', 'install',
          '--no-index', '--no-deps', '--no-compile', '--only-binary=:all:', '--target', str(site),
          *map(str, wheels)], scratch, check)
    result = _run([python, '-I', str(root / 'app/quick_ocr_worker.py'), str(site), '--check'], scratch, check)
    if json.loads(result) != {'ok': True}:
        raise ValueError('OCR runtime verification failed')
    (staging / 'verified').write_text(fingerprint, encoding='ascii')
    check()
    try:
        staging.rename(target)
    except OSError:
        if not ready(target, fingerprint):
            raise


def main(root, argv):
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', type=Path)
    parser.add_argument('--asset-cache', type=Path)
    args = parser.parse_args(argv)
    stage = args.stage.resolve()
    component = stage.parent
    try:
        if (args.stage != stage or component.name != 'quick-ocr' or not stage.name.startswith('.prepare-')
                or (stage / 'requested').read_text(encoding='ascii') != stage.name):
            return 1
    except (OSError, UnicodeError):
        return 1
    try:
        install(root, component, stage, stage / 'cancel', args.asset_cache)
    except InstallCancelled:
        return 2
    except (OSError, ValueError, RuntimeError, tarfile.TarError) as error:
        if sys.stderr:
            message = str(error) if type(error) in (RuntimeError, ValueError) else type(error).__name__
            print(f'Quick OCR setup: {message[:180]}', file=sys.stderr, flush=True)
        return 1
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return 0
