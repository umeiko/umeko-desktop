"""User and Agent share each persistent PTY; attaching grants one chat access."""
import json, os, shutil, sys, threading, uuid
from pathlib import Path
from umeko_plugin_sdk import Plugin, PluginError
from .terminal import Terminal


class Terminals(Plugin):
    def __init__(self,context):
        super().__init__(context);self.terminals={};self.active='';self.visible=False;self.views=set();self.lock=threading.RLock();self.changed=threading.Event()
        self.publisher=threading.Thread(target=self.publish_loop,daemon=True);self.publisher.start()
    @staticmethod
    def workspace(value):return os.path.normcase(os.path.abspath(value)) if value else ''
    def allowed(self,terminal,target):
        return any(self.workspace(grant.get('workspace'))==self.workspace(target.get('workspace')) and (grant['token']==target['token'] or grant.get('id') and not grant['id'].startswith('pending-') and grant['id']==target.get('id')) for grant in terminal.grants)
    def get(self,identifier):
        terminal=self.terminals.get(identifier)
        if not terminal:raise PluginError('终端不存在或已经关闭，请让用户重新附加终端')
        if self.context.call_source=='agent' and not self.allowed(terminal,self.context.capture_session()):raise PluginError('此聊天没有关联该终端，请让用户在终端右键菜单中附加到当前聊天')
        return terminal
    def profiles(self):
        if os.name=='nt':
            entries=[('powershell',shutil.which('pwsh.exe') or shutil.which('powershell.exe')),('cmd',os.environ.get('COMSPEC') or shutil.which('cmd.exe'))]
        else:
            shell=os.environ.get('SHELL','/bin/bash')
            entries=[('default',shell if Path(shell).is_file() else shutil.which('bash') or '/bin/sh'),('bash',shutil.which('bash')),('zsh',shutil.which('zsh')),('sh',shutil.which('sh'))]
        return [{'id':key,'path':value,'name':Path(value).stem} for key,value in entries if value]
    def create(self,args):
        self.context.require('process.execute')
        if self.context.call_source!='ui':raise PluginError('请由用户在终端界面创建终端')
        if len(self.terminals)>=self.context.config['maxTerminals']:raise PluginError('终端数量已达上限，请先关闭不再使用的终端')
        parent=self.terminals.get(args.get('splitFrom',''));profile=args.get('profile',parent.profile if parent else self.context.config['shell'])
        profiles=self.profiles();selected=next((row for row in profiles if row['id']==profile),profiles[0] if profiles else None)
        if not selected:raise PluginError('本机没有可用的终端 Shell')
        argv=[selected['path']];load=self.context.config.get('useShellProfile',True)
        if selected['id']=='powershell':argv+=['-NoLogo']+([] if load else ['-NoProfile'])
        elif selected['id']=='cmd':argv+=['/Q']
        elif Path(selected['path']).name=='bash':argv+=(['-il'] if load else ['--noprofile','--norc','-i'])
        elif Path(selected['path']).name=='zsh':argv+=(['-il'] if load else ['-f','-i'])
        else:argv+=['-i']
        target=self.context.capture_session();cwd=Path(parent.cwd if parent else target.get('workspace') or Path.home()).resolve()
        if not cwd.is_dir():raise PluginError('终端工作目录不存在')
        env={key:value for key,value in os.environ.items() if not key.upper().endswith(('API_KEY','ACCESS_TOKEN','SECRET_KEY','PASSWORD','_AK','_SK'))}
        env.update(TERM='xterm-256color',COLORTERM='truecolor',TERM_PROGRAM='umeko',PYTHONIOENCODING='utf-8')
        identifier='terminal-ID-'+uuid.uuid4().hex[:12];group=parent.group if parent else identifier
        if sum(row.group==group for row in self.terminals.values())>=2:raise PluginError('同一分组最多上下拆分 2 个终端，请使用加号新建分组')
        try:terminal=Terminal(identifier,selected['name'],selected['id'],argv,cwd,env,80,24,self.context.config['scrollback'],self.changed,group)
        except (OSError,RuntimeError) as error:raise PluginError('无法启动终端：'+str(error)) from None
        self.terminals[identifier]=terminal;self.active=identifier;self.publish_list();return terminal.info()
    def listing(self):
        target=self.context.capture_session();agent=self.context.call_source=='agent'
        rows=[{**row.info(),'attached':self.allowed(row,target)} for row in self.terminals.values() if not agent or self.allowed(row,target)]
        active=self.active if any(row['id']==self.active for row in rows) else rows[0]['id'] if rows else ''
        return {'terminals':rows,'activeId':active,'profiles':self.profiles() if not agent else []}
    def publish_list(self):
        if self.visible:self.context.publish('terminal.list',{'changed':True,'activeId':self.active})
    def handle(self,method,args):
        with self.lock:
            if method=='list':
                if self.context.call_source=='ui' and args.get('ensure') and not self.terminals:self.create({})
                return self.listing()
            if method=='create':return self.create(args)
            if method=='view':
                if self.context.call_source!='ui':raise PluginError('此方法仅供终端页面使用')
                ids=args.get('ids',[])[:4];self.views=set(ids);self.visible=True
                return {'frames':[self.get(identifier).frame(reset=True) for identifier in ids if identifier in self.terminals]}
            terminal=self.get(args.get('terminalId',''))
            if method=='read':return terminal.contents(min(1000,max(1,int(args.get('lines',200)))),args.get('afterSequence',-1))
            if method in ('run','write','input'):
                if method=='input' and self.context.call_source!='ui':raise PluginError('请使用公开的 write 方法')
                text=args.get('command' if method=='run' else 'text','')
                if not isinstance(text,str) or not text or len(text)>16000:raise PluginError('终端输入需要 1–16000 字符')
                if method=='run':text=text.rstrip('\r\n').replace('\r\n','\n').replace('\n','\r')+'\r'
                if self.context.call_source=='agent':
                    target=self.context.capture_session()
                    if target['token']==self.context.session.get('token'):self.active=terminal.id
                    self.context.open_page();self.context.publish('terminal.select',{'terminalId':terminal.id},session=target)
                sequence=terminal.revision
                try:terminal.write(text)
                except OSError as error:raise PluginError(str(error)) from None
                return {'terminalId':terminal.id,'submitted':True,'afterSequence':sequence,'visible':self.visible}
            if method=='interrupt':
                terminal.write('\x03');return {'terminalId':terminal.id,'submitted':True}
            if self.context.call_source!='ui':raise PluginError('此终端操作仅供用户界面使用')
            if method=='resize':terminal.resize(min(240,max(20,int(args['columns']))),min(100,max(4,int(args['rows']))));return {'resized':True}
            if method=='unsplit':
                group=terminal.group
                for member in self.terminals.values():
                    if member.group==group:member.group=member.id
                self.active=terminal.id;self.views={terminal.id};self.publish_list()
                return {'terminalId':terminal.id,'unSplit':True}
            if method=='rename':
                name=args.get('name','').strip()
                if not name or len(name)>80:raise PluginError('终端名称需要 1–80 个字符')
                terminal.name=name;self.publish_list();return {'renamed':True}
            if method=='clear':terminal.clear();return {'frame':terminal.frame(reset=True)}
            if method=='attach':
                target=self.context.capture_session()
                if not self.allowed(terminal,target):terminal.grants.append(target)
                language=self.context.request_session.get('language','zh')
                text=('The user attached a terminal from widget: '+terminal.id+'.') if language=='en' else '用户附带了来自widget：'+terminal.id+'的终端'
                self.context.append_to_chat(text,session=target);self.publish_list()
                return {'terminalId':terminal.id,'attached':True,'text':text}
            if method=='kill':
                self.terminals.pop(terminal.id);terminal.close();self.views.discard(terminal.id)
                if self.active==terminal.id:self.active=next(iter(self.terminals),'')
                self.publish_list();return {'closed':True}
            raise PluginError('未知终端操作')
    def on_event(self,name,data):
        if name=='page.visibility':self.visible=bool(data.get('visible'));self.changed.set()
        elif name=='session.changed':
            with self.lock:
                for terminal in self.terminals.values():
                    for grant in terminal.grants:
                        if grant['token']==data.get('token'):grant['id']=data.get('id','')
    def publish_loop(self):
        while not self.context.cancelled.is_set():
            self.changed.wait(.08);self.changed.clear()
            if self.context.cancelled.is_set():break
            with self.lock:terminals=list(self.terminals.values());views=set(self.views);visible=self.visible
            for terminal in terminals:
                if (terminal.exited or not terminal.backend.isalive()) and not terminal.closed:
                    terminal.close();self.publish_list()
                if visible and terminal.id in views and terminal.revision!=terminal.last_frame:
                    try:self.context.publish('terminal.frame',terminal.frame())
                    except (ValueError,PluginError):pass
            # Batch output bursts; never repaint for every individual byte/token.
            self.context.cancelled.wait(.08)
    def close(self):
        super().close();self.changed.set()
        with self.lock:terminals=list(self.terminals.values());self.terminals.clear()
        for terminal in terminals:terminal.close()
        self.publisher.join(timeout=1)


def create_plugin(context):return Terminals(context)
