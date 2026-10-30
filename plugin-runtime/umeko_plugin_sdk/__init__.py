"""Umeko desktop plugin API v1. Standard library only; no application imports."""
from __future__ import annotations
import copy, json, os, platform, signal, subprocess, threading, uuid
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
    lifecycle: str = 'session'
    _request: threading.local = field(default_factory=threading.local,init=False,repr=False)

    @property
    def request_id(self):return getattr(self._request,'id','')
    @request_id.setter
    def request_id(self,value):self._request.id=value
    @property
    def call_source(self):return getattr(self._request,'source','')
    @call_source.setter
    def call_source(self,value):self._request.source=value
    @property
    def request_session(self):return getattr(self._request,'session',{})
    @request_session.setter
    def request_session(self,value):self._request.session=value

    def capture_session(self):
        """Capture identity now; safe to keep for a later background notification."""
        source=self.request_session or self.session
        if not source.get('token'):raise PluginError('当前没有可绑定的聊天')
        return {key:source.get(key,'') for key in ('token','id','workspace')}

    def _target_session(self,session=None):
        if session is not None:
            if not isinstance(session,dict) or not isinstance(session.get('token'),str) or not session['token']:raise PluginError('session 必须来自 capture_session()')
            return session
        if self.request_session:return self.request_session
        if self.lifecycle=='application':raise PluginError('应用级后台操作必须显式指定捕获的 session')
        return self.session

    @property
    def workspace(self): return Path((self.request_session or self.session).get('workspace', ''))

    def require(self, permission):
        if permission not in self.permissions: raise PluginError('Plugin permission is required: '+permission)

    def resolve_workspace(self, relative='.', *, session=None):
        self.require('workspace.read')
        target=self._target_session(session);workspace=Path(target.get('workspace',''))
        if not target.get('workspace') or not workspace.is_dir(): raise PluginError('请先为当前会话选择工作目录')
        root=workspace.resolve()
        path=(root / relative).resolve()
        if not path.is_relative_to(root): raise PluginError('路径超出当前会话目录')
        return path

    def send_message(self, text, steering=False, *, session=None):
        self.require('session.write')
        if not isinstance(text,str) or not text.strip() or len(text)>32000: raise PluginError('消息内容无效或过长')
        self.emit({'event':'session.send','arguments':{'text':text,'steering':bool(steering),'session':self._target_session(session)}})

    def attach_file(self, relative, *, session=None):
        self.require('session.write')
        target=self._target_session(session);path=self.resolve_workspace(relative,session=target)
        self.emit({'event':'session.attach','arguments':{'path':str(path),'session':target}})

    def append_to_chat(self, text, *, session=None):
        """Append user-visible context to the composer without sending a prompt."""
        self.require('session.write')
        if not isinstance(text,str) or not text.strip() or len(text)>16000:raise PluginError('聊天上下文文本无效或过长')
        self.emit({'event':'session.draft','arguments':{'text':text,'session':self._target_session(session)}})

    def open_page(self):
        self.require('session.write')
        self.emit({'event':'page.open','arguments':{'session':self.capture_session()}})

    def preview_file(self, relative):
        path=self.resolve_workspace(relative)
        self.emit({'event':'preview.file','arguments':{'path':str(path),'session':self.capture_session()}})

    def reveal_file(self, relative):
        path=self.resolve_workspace(relative)
        self.emit({'event':'file.reveal','arguments':{'path':str(path),'session':self.capture_session()}})

    def reveal_in_explorer(self, relative):
        path=self.resolve_workspace(relative)
        self.emit({'event':'explorer.reveal','arguments':{'path':str(path),'session':self.capture_session()}})

    def open_with(self, relative):
        path=self.resolve_workspace(relative)
        self.emit({'event':'file.openWith','arguments':{'path':str(path),'session':self.capture_session()}})

    def copy_files(self, relatives, cut=False):
        paths=[str(self.resolve_workspace(relative)) for relative in relatives]
        self.emit({'event':'files.copy','arguments':{'paths':paths,'cut':bool(cut),'session':self.capture_session()}})

    def notify(self, message):
        self.emit({'event':'notification','arguments':{'message':str(message)[:1000]}})

    def notify_agent(self, message, *, data=None, request_id=None, wake=True, session=None):
        """Push an attributed update; return its ID, not an Agent completion receipt."""
        self.require('session.write')
        if not isinstance(message,str) or not message.strip() or len(message)>8000:
            raise PluginError('Agent 通知需要 1–8000 字的文本')
        if data is not None and not isinstance(data,dict):raise PluginError('通知 data 必须是 JSON 对象')
        if type(wake) is not bool:raise PluginError('wake 必须是布尔值')
        identifier=uuid.uuid4().hex
        value={'id':identifier,'message':message,'data':data or {},'requestId':self.request_id if request_id is None else request_id,'wake':wake}
        if session is not None:value['session']=self._target_session(session)
        elif self.request_session:value['session']=self.capture_session()
        elif self.lifecycle=='application' and not value['requestId']:raise PluginError('应用级通知必须指定 session=capture_session() 的结果，或关联请求 ID')
        if not isinstance(value['requestId'],str) or len(value['requestId'])>64:raise PluginError('request_id 无效')
        try:raw=json.dumps(value,ensure_ascii=False,allow_nan=False)
        except (ValueError,TypeError):raise PluginError('通知必须是有效 JSON 数据') from None
        if len(raw.encode('utf-8'))>32768:raise PluginError('Agent 通知超过 32 KiB')
        self.emit({'event':'agent.notify','arguments':value})
        return identifier

    def publish(self, topic, data, *, session=None):
        """Publish structured view data to the currently open Widget page."""
        if not isinstance(topic,str) or not topic or len(topic)>80 or not isinstance(data,dict):raise PluginError('Widget 事件需要名称和 JSON 对象')
        if len(json.dumps(data,ensure_ascii=False,allow_nan=False).encode('utf-8'))>65536:raise PluginError('Widget 事件超过 64 KiB')
        arguments={'topic':topic,'data':data}
        if session is not None:arguments['session']=self._target_session(session)
        self.emit({'event':'widget.event','arguments':arguments})

    def run_executable(self, name, args=(), *, timeout=12, limit=512*1024, session=None):
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
        cwd=self.state_dir if self.lifecycle=='application' and session is None and not self.request_session else self.resolve_workspace(session=session)
        try:
            process=subprocess.Popen([executable,*args],cwd=cwd,env=env,stdin=subprocess.DEVNULL,
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
    def on_event(self, name: str, data: dict): pass
    def close(self): self.context.close()
