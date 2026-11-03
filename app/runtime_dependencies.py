"""Read-only, bounded local preflight probes. No model, installer or remote service."""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path


# Explicit probe declarations, independent of whether a Skill is discoverable.
# Required dependencies determine basic availability; optional ones enable checks.
PACKAGES = (
    ('docx', 'python-docx', '1.2.0'), ('pptx', 'python-pptx', '1.0.2'),
    ('openpyxl', 'openpyxl', '3.1.5'), ('reportlab', 'reportlab', '4.0'),
    ('pdfplumber', 'pdfplumber', '0.10'), ('pypdf', 'pypdf', '3.0'),
    ('playwright.sync_api', 'playwright', '1.40'),
)
WORKFLOWS = (
    ('office', 'Office 文件生成', ('python', 'docx', 'pptx', 'openpyxl'), ('soffice', 'pdftoppm')),
    ('pdf', 'PDF 文本与生成', ('python', 'reportlab', 'pdfplumber', 'pypdf'), ('pdftoppm',)),
    ('git', 'Git', ('git',), ()),
    ('browser', '浏览器自动化（Python Playwright）', ('python', 'playwright.sync_api', 'chromium'), ()),
)
COMMANDS = (
    ('git', ('git',), '--version', '2.20'),
    ('soffice', ('soffice', 'libreoffice'), '--version', '7.0'),
    ('pdftoppm', ('pdftoppm',), '-v', '0.86'),
)
GUIDES = {
    'python': '安装 Python 3.10+，或在任务目录创建 .umeko-tools 虚拟环境，然后重新检测。',
    'office': '在显示的 Python 环境安装 python-docx、python-pptx 和 openpyxl；不要修改 Umeko 的打包环境。',
    'pdf': '在显示的 Python 环境安装 reportlab、pdfplumber 和 pypdf。扫描 PDF 的 OCR 不在本次检测范围内。',
    'git': '安装 Git 2.20+ 并加入 PATH，然后重新检测。',
    'browser': '在显示的 Python 环境安装 Playwright 和 Chromium。检测不会下载或启动浏览器，也不检查远程 MCP。',
    'soffice': '安装 LibreOffice 7+ 并加入 PATH，才可进行 Office 转 PDF 和公式重算。',
    'pdftoppm': '安装 Poppler 并将 pdftoppm 加入 PATH，才可进行 PDF 页面渲染检查。',
}


def version_tuple(value):
    match = re.search(r'(?<!\d)(\d+(?:\.\d+){1,3})(?!\d)', str(value))
    return tuple(int(part) for part in match[1].split('.')) if match else ()


def version_state(value, minimum):
    version = version_tuple(value)
    if not version:
        return 'error', '无法识别版本'
    # A prerelease is not evidence that the declared stable baseline is met.
    if re.search(r'\d(?:a|b|rc|dev)\d', str(value), re.I):
        return 'error', '预发布版本尚未验证'
    size = max(len(version), len(version_tuple(minimum)))
    required = version_tuple(minimum)
    if version + (0,) * (size - len(version)) < required + (0,) * (size - len(required)):
        return 'missing', '版本低于最低要求'
    return 'available', ''


def run_probe(command, timeout=4, env=None):
    """Use files to bound memory even if a damaged executable floods its output."""
    with tempfile.TemporaryDirectory(prefix='umeko-preflight-') as cwd, tempfile.TemporaryFile() as output:
        try:
            process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                stdout=output, stderr=output, shell=False,
                start_new_session=os.name != 'nt',
                creationflags=0x08000000 if os.name == 'nt' else 0)
            try:
                code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                if os.name == 'nt':
                    taskkill = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/taskkill.exe'
                    try:
                        subprocess.run([str(taskkill), '/PID', str(process.pid), '/T', '/F'],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3,
                            creationflags=0x08000000)
                    except (OSError, subprocess.TimeoutExpired):
                        pass
                else:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                if process.poll() is None:
                    process.kill()
                process.wait()
                return {'state': 'error', 'reason': '检测超时'}
            output.seek(0)
            data = output.read(65537)
            if len(data) > 65536:
                return {'state': 'error', 'reason': '检测输出超过上限'}
            if code:
                # Never expose arbitrary stderr, environment values or credentials.
                return {'state': 'error', 'reason': '依赖检查进程失败'}
            return {'state': 'available', 'output': data.decode('utf-8', errors='replace')}
        except OSError:
            return {'state': 'error', 'reason': '无法启动依赖检查进程'}


def python_command(workspace, env):
    local = Path(workspace) / '.umeko-tools' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if local.is_file():
        return [str(local.absolute())]
    # Windows' launcher avoids Microsoft Store python aliases.
    names = ('py', 'python3', 'python') if os.name == 'nt' else ('python3', 'python')
    for name in names:
        found = shutil.which(name, path=env.get('PATH', ''))
        if found:
            return [found, '-3'] if name == 'py' else [found]
    return []


PYTHON_PROBE = r'''
import contextlib, importlib, importlib.metadata, json, os, sys
packages = json.loads(sys.argv[1])
result = {'version': '.'.join(map(str, sys.version_info[:3])), 'path': sys.executable, 'packages': {}}
for module, distribution, minimum in packages:
    row = {}
    try:
        with open(os.devnull, 'w') as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            loaded = importlib.import_module(module)
            row = {'state': 'available', 'version': importlib.metadata.version(distribution), 'path': getattr(loaded, '__file__', '')}
            if distribution == 'playwright':
                with loaded.sync_playwright() as p:
                    path = p.chromium.executable_path
                    result['chromium'] = {'state': 'available' if os.path.isfile(path) else 'missing', 'path': path, 'version': ''}
    except ModuleNotFoundError as error:
        row = {'state': 'missing' if module == error.name or module.startswith(str(error.name) + '.') else 'error'}
    except Exception:
        row = {'state': 'error'}
    result['packages'][module] = row
print(json.dumps(result))
'''


def inspect_dependencies(workspace, env=None, runner=run_probe):
    env = dict(os.environ if env is None else env)
    # The selected interpreter is an external task Python, never sys.executable
    # (which may be the frozen desktop). Probes ignore cwd/PYTHONPATH shadowing.
    command = python_command(workspace, env)
    rows = {}
    if command:
        probe = runner([*command, '-I', '-B', '-c', PYTHON_PROBE, json.dumps(PACKAGES)], timeout=12, env=env)
        if probe['state'] == 'available':
            try:
                payload = json.loads(probe['output'])
                state, reason = version_state(payload['version'], '3.10')
                rows['python'] = dict(state=state, reason=reason, version=payload['version'], path=payload['path'])
                for module, distribution, minimum in PACKAGES:
                    row = payload['packages'][module]
                    if row['state'] == 'available':
                        row['state'], row['reason'] = version_state(row['version'], minimum)
                    else:
                        row['reason'] = '未安装依赖' if row['state'] == 'missing' else '依赖导入失败'
                    rows[module] = row
                rows['chromium'] = payload.get('chromium', {'state': 'missing', 'reason': 'Chromium 未检测到'})
            except (ValueError, KeyError, TypeError):
                rows['python'] = {'state': 'error', 'reason': 'Python 检测结果无效', 'path': command[0]}
        else:
            rows['python'] = {**probe, 'path': command[0]}
    else:
        rows['python'] = {'state': 'missing', 'reason': '未找到任务 Python'}
    for module, _, _ in PACKAGES:
        rows.setdefault(module, {'state': 'error', 'reason': 'Python 不可用，尚未检测'})
    rows.setdefault('chromium', {'state': 'error', 'reason': 'Playwright 不可用，尚未检测'})
    for identifier, names, flag, minimum in COMMANDS:
        path = next((found for name in names if (found := shutil.which(name, path=env.get('PATH', '')))), '')
        if not path:
            rows[identifier] = {'state': 'missing', 'reason': '未找到可执行文件'}
            continue
        probe = runner([path, flag], env=env)
        row = {'path': path, 'state': probe['state'], 'reason': probe.get('reason', '')}
        if probe['state'] == 'available':
            version = version_tuple(probe['output'])
            row['version'] = '.'.join(map(str, version))
            row['state'], row['reason'] = version_state(row['version'], minimum)
        rows[identifier] = row
    minimums = {'python': '3.10', **{m: v for m, _, v in PACKAGES}, **{i: v for i, _, _, v in COMMANDS}}
    dependencies = [{**row, 'id': identifier, 'minimum': minimums.get(identifier, ''), 'version': row.get('version', ''),
                     'path': row.get('path', ''), 'reason': row.get('reason', ''), 'scope': 'local'} for identifier, row in rows.items()]
    capabilities = []
    for identifier, name, required, optional in WORKFLOWS:
        states = [rows[key]['state'] for key in required]
        state = 'missing' if 'missing' in states else 'error' if 'error' in states else 'available'
        if state == 'available' and any(rows[key]['state'] != 'available' for key in optional):
            state = 'partial'
        capabilities.append({'id': identifier, 'name': name, 'scope': 'local', 'state': state,
            'required': list(required), 'optional': list(optional), 'guide': GUIDES[identifier],
            'dependencies': [row for row in dependencies if row['id'] in (*required, *optional)]})
    return {'schemaVersion': 1, 'workspace': str(workspace), 'scope': 'local', 'checkedAt': time.time(),
        'pythonCommand': command,
        'dependencies': dependencies, 'capabilities': capabilities, 'guides': GUIDES,
        'remote': {'state': 'unchecked', 'reason': '远程服务未检测'},
        'qualityVerified': False}
