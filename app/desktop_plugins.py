"""Session-scoped desktop plugins, isolated workers and one reusable QML page slot."""
from __future__ import annotations
import copy, hashlib, json, os, re, sys, uuid
from pathlib import Path
from PySide6.QtCore import QObject, Property, Signal, Slot, QProcess, QProcessEnvironment, QTimer, QUrl

LIMIT=2*1024*1024

def read(path, default=None):
    try:
        if Path(path).stat().st_size>1024*1024:return default
        return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError,ValueError):return default

class DesktopPlugins(QObject):
    changed=Signal()
    sessionChanged=Signal()
    pageChanged=Signal()
    requested=Signal()
    dismissed=Signal()
    response=Signal(str,"QVariantMap")
    def __init__(self, backend):
        super().__init__(backend)
        self.b=backend;self.root=backend.store.directory/'desktop-plugins';self.registry=self.root/'settings.json'
        self.settings=read(self.registry,{}) or {};self.entries={}
        for identifier,record in self.settings.get('installed',{}).items():
            if re.fullmatch('[a-z][a-z0-9-]{0,63}',identifier) and re.fullmatch(r'\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?',record.get('version','')):
                self.entries[identifier]={**record,'builtin':False}
        for folder in (backend.root/'umeko-plugins').glob('*'):
            m=read(folder/'manifest.json',{}) or {}
            if m.get('kind')=='umeko-plugin' and m.get('apiVersion')==1 and m.get('id')==folder.name:self.entries[folder.name]={**m,'builtin':True}
        self.workers={};self._page='';self._error='';self._session={};self.storage_key='';self._busy=False;self._status='';self.closed=False
        self.refresh=QTimer(self);self.refresh.setSingleShot(True);self.refresh.setInterval(200);self.refresh.timeout.connect(self.synchronize)
        backend.viewChanged.connect(self.synchronize)
        backend.chatChanged.connect(lambda: self.refresh.start() if not self.refresh.isActive() else None)
        self.synchronize()
    def path(self, identifier):
        e=self.entries[identifier]
        return self.b.root/'umeko-plugins'/identifier if e.get('builtin') else self.root/'packages'/identifier/e['version']
    def enabled(self,identifier):return self.settings.get('enabled',{}).get(identifier,True)
    def session_enabled(self,identifier):
        sessions=self.settings.get('sessions',{})
        return identifier in sessions[self.storage_key] if self.storage_key in sessions else self.entries[identifier].get('builtin',False)
    @Property('QVariantList',notify=changed)
    def rows(self):return sorted([{**e,'enabled':self.enabled(k),'sessionEnabled':self.session_enabled(k),'hasPage':bool(e.get('page'))} for k,e in self.entries.items()],key=lambda e:e['name'])
    @Property('QVariantList',notify=changed)
    def sessionPlugins(self):return [e for e in self.rows if e['enabled'] and e['sessionEnabled'] and e['hasPage']]
    @Property('QVariantMap',notify=sessionChanged)
    def session(self):
        result=dict(self._session)
        if "session.read" not in self.entries.get(self._page,{}).get("permissions",[]):result.pop("messages",None)
        return result
    @Property('QVariantMap',notify=pageChanged)
    def page(self):
        if not self._page:return {}
        e=self.entries[self._page];worker=self.workers.get(self._page)
        return {'id':self._page,'title':e['name'],'url':QUrl.fromLocalFile(str(self.path(self._page)/e['page'])).toString(),'config':self.settings.get('config',{}).get(self._page,read(self.path(self._page)/e.get('config','config.json'),{})),'error':self._error,'loading':not worker or not worker['ready']}
    @Property(bool,notify=changed)
    def busy(self):return self._busy
    @Property(str,notify=changed)
    def status(self):return self._status
    @Slot(str,result='QVariantMap')
    def details(self,identifier):
        if identifier not in self.entries:return {}
        e=self.entries[identifier];path=self.path(identifier)
        try:
            with (path/e.get('readme','README.md')).open('r',encoding='utf-8') as f:doc=f.read(65536)
        except OSError:doc=''
        config=self.settings.get('config',{}).get(identifier,read(path/e.get('config','config.json'),{}))
        return {**e,'readmeText':doc,'configText':json.dumps(config,ensure_ascii=False,indent=2)}
    def save(self):
        try:
            self.root.mkdir(parents=True,exist_ok=True)
            data={**self.settings,'installed':{k:e for k,e in self.entries.items() if not e.get('builtin')}}
            temporary=self.registry.with_suffix('.tmp');temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');temporary.replace(self.registry);return True
        except OSError:self._status='插件设置保存失败';self.changed.emit();return False
    def synchronize(self):
        if self.closed:return
        view=self.b._view
        key=view.id or 'draft:'+view.key
        switched=self._session.get('token')!=view.key or self._session.get('workspace')!=view.workspace
        if switched:
            self.closePage()
            for identifier in list(self.workers):self.stop(identifier)
            self.storage_key=key
        elif key!=self.storage_key:
            sessions=self.settings.setdefault('sessions',{})
            if self.storage_key in sessions:sessions[key]=sessions.pop(self.storage_key);self.save()
            self.storage_key=key;switched=True
        messages=[{'role':m.get('role',''),'text':m.get('text','')[:2000]} for m in view.messages[-8:]]
        value={'token':view.key,'id':view.id,'workspace':view.workspace,'title':view.title,'busy':view.busy,'messages':messages}
        if value==self._session:return
        self._session=value;self.sessionChanged.emit()
        if switched:self.changed.emit()
        for identifier in list(self.workers):self.send(identifier,{'id':uuid.uuid4().hex,'operation':'session','arguments':{'session':value}})
        for identifier,e in self.entries.items():
            if self.enabled(identifier) and self.session_enabled(identifier) and not e.get('page'):self.start(identifier)
    @Slot(str,bool)
    def setEnabled(self,identifier,value):
        if identifier not in self.entries:return
        old=copy.deepcopy(self.settings);self.settings.setdefault('enabled',{})[identifier]=value
        if not self.save():self.settings=old;return
        if not value:
            if self._page==identifier:self.closePage()
            self.stop(identifier)
        elif self.session_enabled(identifier) and not self.entries[identifier].get('page'):self.start(identifier)
        self.changed.emit()
    @Slot(str,bool)
    def setSessionEnabled(self,identifier,value):
        if identifier not in self.entries:return
        selected=[k for k in self.entries if self.session_enabled(k) and k!=identifier]
        if value:selected.append(identifier)
        if len(selected)>8:self.b.toast.emit('每个会话最多启用 8 个 Umeko 插件');return
        old=copy.deepcopy(self.settings);self.settings.setdefault('sessions',{})[self.storage_key]=selected
        if not self.save():self.settings=old;return
        if not value:
            if self._page==identifier:self.closePage()
            self.stop(identifier)
        elif self.enabled(identifier) and not self.entries[identifier].get('page'):self.start(identifier)
        self.changed.emit()
    @Slot(str,result=bool)
    def openPage(self,identifier):
        if identifier not in self.entries or not self.enabled(identifier) or not self.session_enabled(identifier) or not self.entries[identifier].get('page'):return False
        self.closePage();self._page=identifier;self._error='';self.start(identifier);self.sessionChanged.emit();self.pageChanged.emit();self.requested.emit();return True
    @Slot()
    def closePage(self):
        if not self._page:return
        old=self._page;self._page='';self._error='';self.stop(old);self.sessionChanged.emit();self.pageChanged.emit();self.dismissed.emit()
    def command(self):
        if getattr(sys,'frozen',False):return sys.executable,['--umeko-plugin-worker']
        return sys.executable,['-B',str(self.b.root/'plugin-runtime/worker.py')]
    def process(self):
        process=QProcess(self);env=QProcessEnvironment.systemEnvironment()
        for key in env.keys():
            if re.search(r'(API_KEY|ACCESS_TOKEN|SECRET_KEY|PASSWORD|_AK|_SK)$',key,re.I):env.remove(key)
        env.insert('PYTHONDONTWRITEBYTECODE','1');process.setProcessEnvironment(env);return process
    def start(self,identifier):
        if self.closed or identifier in self.workers:return
        p=self.process();w={'process':p,'buffer':b'','pending':set(),'queue':[],'ready':False,'token':self._session['token']};self.workers[identifier]=w
        def initialize():
            e=self.entries[identifier];config=self.settings.get('config',{}).get(identifier,read(self.path(identifier)/e.get('config','config.json'),{}))
            state=self.root/'state'/identifier/hashlib.sha256(self.storage_key.encode()).hexdigest()
            p.write(self.frame({'id':'initialize','operation':'initialize','arguments':{'path':str(self.path(identifier)),'stateDir':str(state),'config':config,'session':self._session}}))
        p.started.connect(initialize);p.readyReadStandardOutput.connect(lambda:self.receive(identifier,w));p.readyReadStandardError.connect(lambda:p.readAllStandardError())
        def failed(*_):
            if self.workers.get(identifier) is not w:return
            self.workers.pop(identifier);self._error='插件进程已停止，点击重试可重新打开'
            for request in w['pending']:self.response.emit(request,{'ok':False,'error':self._error})
            self.pageChanged.emit();p.deleteLater()
        p.finished.connect(failed);p.errorOccurred.connect(failed)
        program,args=self.command();p.start(program,args)
        def timeout():
            if self.workers.get(identifier) is w and not w['ready']:self._error='插件启动超时';self.stop(identifier);self.pageChanged.emit()
        QTimer.singleShot(20000,self,timeout)
    def frame(self,request):return (json.dumps(request,ensure_ascii=True)+'\n').encode()
    def send(self,identifier,request):
        w=self.workers.get(identifier)
        if not w:return
        if not w['ready']:
            if request.get('operation')=='session':w['queue']=[item for item in w['queue'] if item.get('operation')!='session']
            if len(w['queue'])<16:w['queue'].append(request)
            return
        w['process'].write(self.frame(request))
    def stop(self,identifier):
        w=self.workers.pop(identifier,None)
        if not w:return
        for request in w['pending']:self.response.emit(request,{'ok':False,'error':'插件任务已取消'})
        p=w['process']
        if p.state()==QProcess.Starting:p.kill()
        else:
            p.closeWriteChannel()
            if os.name=='nt':
                def terminate_tree():
                    if p.state()==QProcess.NotRunning:return
                    import subprocess
                    subprocess.Popen([str(Path(os.environ.get('SystemRoot','C:/Windows'))/'System32/taskkill.exe'),'/PID',str(p.processId()),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                QTimer.singleShot(100,p,terminate_tree)
            else:p.terminate()
        p.finished.connect(p.deleteLater)
        if p.state()==QProcess.NotRunning:p.deleteLater()
        else:QTimer.singleShot(400,p,p.kill)
    @Slot(str,str,result=str)
    def call(self,method,raw):
        w=self.workers.get(self._page)
        if not w or len(w['pending'])>=8 or len(raw)>65536 or len(method)>128:return ''
        try:args=json.loads(raw)
        except ValueError:return ''
        if not isinstance(args,dict):return ''
        identifier=self._page;request=uuid.uuid4().hex;w['pending'].add(request)
        self.send(identifier,{'id':request,'operation':'call','arguments':{'method':method,'arguments':args}})
        def timeout():
            if self.workers.get(identifier) is w and request in w['pending']:self._error='插件操作超时，已停止';self.stop(identifier);self.pageChanged.emit()
        QTimer.singleShot(20000,self,timeout);return request
    def receive(self,identifier,w):
        if self.workers.get(identifier) is not w:return
        w['buffer']+=bytes(w['process'].readAllStandardOutput())
        if len(w['buffer'])>LIMIT:self._error='插件输出超过限制';self.stop(identifier);self.pageChanged.emit();return
        while b'\n' in w['buffer']:
            raw,w['buffer']=w['buffer'].split(b'\n',1)
            try:value=json.loads(raw)
            except ValueError:continue
            if not isinstance(value,dict):continue
            if value.get('type')=='event':
                if w['token']==self._session.get('token'):self.host_event(identifier,value)
                continue
            request=value.get('id')
            if request=='initialize':
                if not value.get('ok'):self._error=value.get('error','插件启动失败');self.stop(identifier);self.pageChanged.emit();return
                w['ready']=True;queue=w['queue'];w['queue']=[]
                for item in queue:self.send(identifier,item)
                self.pageChanged.emit()
            elif request in w['pending']:w['pending'].remove(request);self.response.emit(request,value)
    def host_event(self,identifier,event):
        kind=event.get('event');args=event.get('arguments',{});perms=self.entries[identifier].get('permissions',[])
        if kind=='notification':self.b.toast.emit(str(args.get('message',''))[:1000]);return
        if kind in ('session.send','session.attach') and 'session.write' not in perms:return
        if kind=='session.send':
            text=args.get('text','')
            if isinstance(text,str) and text.strip() and len(text)<=32000:(self.b.steer if args.get('steering') else self.b.send)(text)
        if kind in ('session.attach','preview.file') and 'workspace.read' in perms:
            if not self._session.get('workspace'):return
            root=Path(self._session['workspace']).resolve();path=Path(args.get('path','')).resolve()
            if not path.is_relative_to(root) or not path.is_file():return
            if kind=='session.attach':self.b.attachChatboxFile(str(path))
            else:self.b.documentRequested.emit(str(path),path.name,'file')
    def manage(self,request,done):
        if self._busy or self.closed:return
        self._busy=True;self._status='正在处理插件…';self.changed.emit();p=self.process();output=bytearray()
        p.readyReadStandardOutput.connect(lambda:output.extend(bytes(p.readAllStandardOutput())) if len(output)<=LIMIT else p.kill())
        p.readyReadStandardError.connect(lambda:p.readAllStandardError())
        p.started.connect(lambda:(p.write(self.frame(request)),p.closeWriteChannel()))
        settled=False
        def finish(*_):
            nonlocal settled
            if settled:return
            settled=True
            try:result=json.loads(output)
            except ValueError:result={'ok':False,'error':'插件管理进程失败，请检查 Python 运行环境'}
            self._busy=False;self._status='操作已完成' if result.get('ok') else result.get('error','插件操作失败')
            if not self.closed:done(result);self.changed.emit();self.b.toast.emit(self._status)
            p.deleteLater()
        p.finished.connect(finish);p.errorOccurred.connect(finish)
        program,args=self.command();p.start(program,args);QTimer.singleShot(30000,p,p.kill)
    @Slot(str)
    def importZip(self,url):
        path=QUrl(url).toLocalFile()
        if not path:self._status='请选择本机插件 ZIP 文件';self.changed.emit();return
        def done(result):
            if not result.get('ok'):return
            value=result['result'];m={**value['manifest'],'builtin':False};identifier=m['id'];old=copy.deepcopy(self.entries);options=copy.deepcopy(self.settings)
            old_path=self.path(identifier) if identifier in self.entries else None
            if self._page==identifier:self.closePage()
            self.stop(identifier);self.entries[identifier]=m;self.settings.setdefault('config',{}).setdefault(identifier,value['config'])
            if not self.save():self.entries=old;self.settings=options;return
            if old_path and old_path!=self.path(identifier):
                import shutil;shutil.rmtree(old_path,ignore_errors=True)
            self._status='插件已导入，可在当前会话启用'
        self.manage({'id':'install','operation':'install','arguments':{'archive':path,'destination':str(self.root/'packages'),'reserved':[k for k,e in self.entries.items() if e.get('builtin')],'configs':self.settings.get('config',{})}},done)
    @Slot(str,str)
    def saveConfig(self,identifier,raw):
        if identifier not in self.entries or len(raw)>65536:return
        try:value=json.loads(raw);assert isinstance(value,dict)
        except (ValueError,AssertionError):self._status='请输入有效的 JSON 配置对象';self.changed.emit();return
        def done(result):
            if not result.get('ok'):return
            old=copy.deepcopy(self.settings);self.settings.setdefault('config',{})[identifier]=value
            if not self.save():self.settings=old;return
            if self._page==identifier:self.closePage()
            self.stop(identifier)
        self.manage({'id':'config','operation':'config','arguments':{'path':str(self.path(identifier)),'config':value}},done)
    @Slot(str,result=bool)
    def uninstall(self,identifier):
        if identifier not in self.entries or self.entries[identifier].get('builtin') or self._busy:return False
        old=copy.deepcopy(self.entries);options=copy.deepcopy(self.settings)
        if self._page==identifier:self.closePage()
        self.stop(identifier);del self.entries[identifier];self.settings.get('config',{}).pop(identifier,None)
        self.settings.get('enabled',{}).pop(identifier,None)
        for key,ids in self.settings.get('sessions',{}).items():self.settings['sessions'][key]=[item for item in ids if item!=identifier]
        if not self.save():self.entries=old;self.settings=options;return False
        import shutil;shutil.rmtree(self.root/'packages'/identifier,ignore_errors=True);self.changed.emit();return True
    @Slot(str,result=bool)
    def exportSdk(self,url):
        path=QUrl(url).toLocalFile()
        if not path:return False
        for relative in ('desktop-plugin-resources/umeko-plugin-sdk.zip','build/desktop-plugin-resources/umeko-plugin-sdk.zip'):
            source=self.b.root/relative
            if source.is_file():
                try:
                    from PySide6.QtCore import QSaveFile,QIODevice
                    target=QSaveFile(path)
                    if target.open(QIODevice.WriteOnly) and target.write(source.read_bytes())>=0:return target.commit()
                except OSError:return False
        self.b.toast.emit('无法导出插件 SDK，请重新构建插件开发资源');return False
    def close(self):
        if self.closed:return
        self.closed=True;self.refresh.stop()
        processes=[w["process"] for w in self.workers.values()]
        for identifier in list(self.workers):self.stop(identifier)
        for process in processes:
            if process.state()!=QProcess.NotRunning and not process.waitForFinished(300):process.kill();process.waitForFinished(100)
