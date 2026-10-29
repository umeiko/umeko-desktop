"""Umeko desktop plugin API v1. Standard library only; no application imports."""
from __future__ import annotations
import copy, os, platform, signal, subprocess, threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

API_VERSION = 1
class PluginError(RuntimeError): pass

@dataclass
class Context:
    package_dir: Path
    state_dir: Path
    config: dict
    session: dict
    permissions: list[str]
    executables: dict = field(default_factory=dict)
    emit: Callable = lambda value: None
    cancelled: threading.Event = field(default_factory=threading.Event)
    _processes: set = field(default_factory=set,init=False,repr=False)

    @property
    def workspace(self): return Path(self.session.get('workspace', ''))

    def require(self, permission):
        if permission not in self.permissions: raise PluginError('Plugin permission is required: '+permission)

    def resolve_workspace(self, relative='.'):
        self.require('workspace.read')
        if not self.session.get('workspace') or not self.workspace.is_dir(): raise PluginError('请先为当前会话选择工作目录')
        root=self.workspace.resolve()
        path=(root / relative).resolve()
        if not path.is_relative_to(root): raise PluginError('路径超出当前会话目录')
        return path

    def send_message(self, text, steering=False):
        self.require('session.write')
        if not isinstance(text,str) or not text.strip() or len(text)>32000: raise PluginError('消息内容无效或过长')
        self.emit({'event':'session.send','arguments':{'text':text,'steering':bool(steering)}})

    def attach_file(self, relative):
        self.require('session.write')
        path=self.resolve_workspace(relative)
        self.emit({'event':'session.attach','arguments':{'path':str(path)}})

    def preview_file(self, relative):
        path=self.resolve_workspace(relative)
        self.emit({'event':'preview.file','arguments':{'path':str(path)}})

    def notify(self, message):
        self.emit({'event':'notification','arguments':{'message':str(message)[:1000]}})

    def run_executable(self, name, args=(), *, timeout=12, limit=512*1024):
        self.require('process.execute')
        spec=self.executables.get(name,{})
        if 'system' in spec: executable=spec['system']
        else:
            target=('windows' if os.name=='nt' else 'macos' if platform.system()=='Darwin' else 'linux')+'-'+('arm64' if platform.machine().lower() in ('arm64','aarch64') else 'x64')
            relative=spec.get(target)
            if not relative: raise PluginError('此平台没有插件所需的可执行文件：'+name)
            executable=str((self.package_dir/relative).resolve())
            if not Path(executable).is_relative_to(self.package_dir.resolve()): raise PluginError('可执行文件路径无效')
        if not executable or any(not isinstance(x,str) or '\0' in x for x in args): raise PluginError('可执行文件参数无效')
        env={k:v for k,v in os.environ.items() if not k.upper().endswith(('API_KEY','ACCESS_TOKEN','SECRET_KEY','PASSWORD','_AK','_SK'))}
        env.update(GIT_TERMINAL_PROMPT='0',GIT_OPTIONAL_LOCKS='0',PAGER='cat',GIT_PAGER='cat')
        try:
            process=subprocess.Popen([executable,*args],cwd=self.resolve_workspace(),env=env,stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,stderr=subprocess.STDOUT,start_new_session=os.name!='nt',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        except OSError: raise PluginError('找不到可执行文件或无法启动：'+name) from None
        self._processes.add(process)
        chunks=[]; size=0; truncated=False
        def consume():
            nonlocal size,truncated
            while True:
                data=process.stdout.read(16384)
                if not data: break
                available=max(0,limit-size)
                if available: chunks.append(data[:available]);size+=min(len(data),available)
                if len(data)>available:
                    truncated=True; self._stop_process(process); break
        reader=threading.Thread(target=consume,daemon=True);reader.start()
        try:
            if self.cancelled.is_set(): self._stop_process(process)
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self._stop_process(process);process.wait(); raise PluginError('命令运行超时，已停止') from None
        finally:
            reader.join(1);process.stdout.close();self._processes.discard(process)
        return {'code':process.returncode,'text':b''.join(chunks).decode('utf-8','replace'),'truncated':truncated}

    def _stop_process(self, process):
        if process.poll() is not None:return
        try:
            if os.name=='nt':
                subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=3,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            else:os.killpg(process.pid,signal.SIGKILL)
        except (OSError,subprocess.TimeoutExpired):process.kill()

    def close(self):
        self.cancelled.set()
        for process in list(self._processes):self._stop_process(process)

class Plugin:
    def __init__(self, context: Context): self.context=context
    def handle(self, method: str, arguments: dict): raise PluginError('未知插件操作：'+method)
    def close(self): self.context.close()
