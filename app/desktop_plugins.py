"""Session Widgets and application services, isolated workers and one QML slot."""
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
    managed=Signal(str,"QVariantMap")
    event=Signal(str,"QVariantMap")
    def __init__(self, backend):
        super().__init__(backend)
        self.b=backend;self.root=backend.store.directory/'desktop-plugins';self.registry=self.root/'settings.json'
        self._icons=read(backend.root/'plugin-runtime/umeko_plugin_sdk/icons.json',[]) or []
        self.settings=read(self.registry,{}) or {};self.entries={}
        for identifier,record in self.settings.get('installed',{}).items():
            if re.fullmatch('[a-z][a-z0-9-]{0,63}',identifier) and re.fullmatch(r'\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?',record.get('version','')):
                self.entries[identifier]={**record,'builtin':False}
        for folder in (backend.root/'umeko-plugins').glob('*'):
            m=read(folder/'manifest.json',{}) or {}
            if m.get('kind')=='umeko-plugin' and m.get('apiVersion')==1 and m.get('id')==folder.name:self.entries[folder.name]={**m,'builtin':True}
        self._review_loops={};self._review_requests={}
        self.response.connect(self.review_response)
        self.workers={};self._failed_services=set();self.application_token='application:'+uuid.uuid4().hex;self._page='';self._selection='';self._error='';self._session={};self.storage_key='';self._busy=False;self._status='';self.closed=False
        self.refresh=QTimer(self);self.refresh.setSingleShot(True);self.refresh.setInterval(200);self.refresh.timeout.connect(self.synchronize)
        backend.viewChanged.connect(self.synchronize)
        backend.chatChanged.connect(lambda: self.refresh.start() if not self.refresh.isActive() else None)
        from .widget_channel import WidgetChannel
        self.bridge=WidgetChannel(self)
        from .desktop_pet import DesktopPet
        self._pet=DesktopPet(self)
        self._pet_imports={}
        self._pet.imported.connect(self.pet_imported)
        self.synchronize()
    def review_response(self,request,value):
        target=self._review_requests.pop(request,None)
        if target:self.b._pool.write(target[0],{'type':'loop_review_response','id':target[1]})
    def review_event(self,record,event):
        kind=event.get('type');identifier='change-review'
        if kind=='exit':
            loop=self._review_loops.pop(record.key,None)
            if loop and self.enabled(identifier):
                self.call_for(identifier,'finish',json.dumps({'loopId':loop,'reason':'exited'}),timeout_ms=10000,session=self.bridge.snapshot(record))
            return
        if kind!='loop_review':return
        phase=event.get('phase')
        if phase not in ('begin','finish') or not isinstance(event.get('loopId'),str):return
        if phase=='begin':self._review_loops[record.key]=event['loopId']
        else:self._review_loops.pop(record.key,None)
        request=''
        if identifier in self.entries and self.enabled(identifier):
            request=self.call_for(identifier,phase,json.dumps({'loopId':event['loopId'],'reason':event.get('reason','completed')}),timeout_ms=10000,session=self.bridge.snapshot(record))
        if request:self._review_requests[request]=(record,event.get('id'))
        else:self.b._pool.write(record,{'type':'loop_review_response','id':event.get('id')})
    def path(self, identifier):
        e=self.entries[identifier]
        return self.b.root/'umeko-plugins'/identifier if e.get('builtin') else self.root/'packages'/identifier/e['version']
    def application(self,identifier):return self.entries.get(identifier,{}).get('lifecycle','session')=='application'
    def enabled(self,identifier):return self.settings.get('enabled',{}).get(identifier,not self.application(identifier) or identifier=='desktop-pet' and self.entries[identifier].get('builtin',False))
    @Property(QObject,constant=True)
    def pet(self):return self._pet
    def session_enabled(self,identifier):
        if self.application(identifier):return self.enabled(identifier)
        sessions=self.settings.get('sessions',{})
        return identifier in sessions[self.storage_key] if self.storage_key in sessions else self.entries[identifier].get('builtin',False)
    @Property('QVariantList',notify=changed)
    def rows(self):return sorted([{**e,**self.icon_for(k),'lifecycle':e.get('lifecycle','session'),'enabled':self.enabled(k),'sessionEnabled':self.session_enabled(k),'hasPage':bool(e.get('page')),'running':bool(self.workers.get(k,{}).get('ready')),'starting':k in self.workers and not self.workers[k]['ready']} for k,e in self.entries.items()],key=lambda e:e['name'])
    @Property('QVariantList',constant=True)
    def iconCatalog(self):return self._icons
    def icon_for(self,identifier):
        icon=self.entries[identifier].get('icon','puzzle')
        if isinstance(icon,str):
            return {'iconGlyph':next((row['glyph'] for row in self._icons if row['id']==icon),'puzzle'),'iconSource':''}
        if isinstance(icon,dict) and isinstance(icon.get('path'),str):
            root=self.path(identifier).resolve();path=(root/icon['path']).resolve()
            if path.is_relative_to(root) and path.is_file():return {'iconGlyph':'puzzle','iconSource':QUrl.fromLocalFile(str(path)).toString()}
        return {'iconGlyph':'puzzle','iconSource':''}
    @Property('QVariantList',notify=changed)
    def sessionPlugins(self):return [e for e in self.rows if e['enabled'] and e['sessionEnabled'] and e['hasPage']]
    def recent_key(self):return os.path.normcase(os.path.abspath(self._session.get('workspace') or '.'))
    @Property('QVariantMap',notify=changed)
    def recentPlugin(self):
        available=self.sessionPlugins
        identifier=self.settings.get('recentPages',{}).get(self.recent_key())
        return next((e for e in available if e['id']==identifier),available[0] if available else {})
    @Property('QVariantMap',notify=sessionChanged)
    def session(self):
        result=dict(self._session)
        if "session.read" not in self.entries.get(self._page,{}).get("permissions",[]):result.pop("messages",None)
        return result
    @Property('QVariantMap',notify=pageChanged)
    def page(self):
        if not self._page:return {}
        e=self.entries[self._page];worker=self.workers.get(self._page)
        return {'id':self._page,'title':e['name'],**self.icon_for(self._page),'url':QUrl.fromLocalFile(str(self.path(self._page)/e['page'])).toString(),'selection':self._selection,'config':self.settings.get('config',{}).get(self._page,read(self.path(self._page)/e.get('config','config.json'),{})),'error':self._error,'loading':not worker or not worker['ready']}
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
        return {**e,'readmeText':doc,'configText':json.dumps(config,ensure_ascii=False,indent=2),'settingsUrl':QUrl.fromLocalFile(str(path/e['settingsPage'])).toString() if e.get('settingsPage') else ''}
    @Slot(str,str,str,result=str)
    def settingsCall(self,identifier,method,raw):
        return self.call_for(identifier,method,raw)
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
            for identifier in list(self.workers):
                if not self.application(identifier):self.stop(identifier)
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
            if self.enabled(identifier) and self.session_enabled(identifier) and (self.application(identifier) or not e.get('page')):self.start(identifier)
    @Slot(str,bool)
    def setEnabled(self,identifier,value):
        if identifier not in self.entries:return
        if value and self.application(identifier) and sum(self.application(k) and self.enabled(k) for k in self.entries if k!=identifier)>=8:
            self.b.toast.emit('应用级后台服务最多同时启用 8 个');return
        old=copy.deepcopy(self.settings);self.settings.setdefault('enabled',{})[identifier]=value
        if not self.save():self.settings=old;return
        if value:self._failed_services.discard(identifier)
        if not value:
            if self._page==identifier:self.closePage()
            self.stop(identifier)
        elif self.session_enabled(identifier) and (self.application(identifier) or not self.entries[identifier].get('page')):self.start(identifier)
        self.changed.emit()
    @Slot(str,bool)
    def setSessionEnabled(self,identifier,value):
        if identifier not in self.entries:return
        if self.application(identifier):self.setEnabled(identifier,value);return
        selected=[k for k in self.entries if not self.application(k) and self.session_enabled(k) and k!=identifier]
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
        if self._page==identifier and not self._error and identifier in self.workers:return True
        self._failed_services.discard(identifier)
        self.closePage();self._page=identifier;self._error=''
        recent=self.settings.setdefault('recentPages',{})
        if recent.get(self.recent_key())!=identifier:
            recent[self.recent_key()]=identifier;self.save();self.changed.emit()
        self.start(identifier);self.send(identifier,{'id':uuid.uuid4().hex,'operation':'event','arguments':{'name':'page.visibility','data':{'visible':True}}});self.sessionChanged.emit();self.pageChanged.emit();self.requested.emit();return True
    @Slot()
    def closePage(self):
        if not self._page:return
        old=self._page;self._page='';self._selection='';self._error=''
        self.send(old,{'id':uuid.uuid4().hex,'operation':'event','arguments':{'name':'page.visibility','data':{'visible':False}}})
        if not self.application(old):self.stop(old)
        self.sessionChanged.emit();self.pageChanged.emit();self.dismissed.emit()
    def command(self):
        if getattr(sys,'frozen',False):return sys.executable,['--umeko-plugin-worker']
        return sys.executable,['-B',str(self.b.root/'plugin-runtime/worker.py')]
    def process(self):
        process=QProcess(self);env=QProcessEnvironment.systemEnvironment()
        for key in env.keys():
            if re.search(r'(API_KEY|ACCESS_TOKEN|SECRET_KEY|PASSWORD|_AK|_SK)$',key,re.I):env.remove(key)
        env.insert('PYTHONDONTWRITEBYTECODE','1');process.setProcessEnvironment(env);return process
    def start(self,identifier):
        if self.closed or identifier in self.workers or identifier in self._failed_services:return
        if identifier=='desktop-pet' and self.entries[identifier].get('builtin'):
            self.workers[identifier]={'service':self._pet,'ready':True,'pending':set(),'token':self.application_token}
            self._pet.start();self.changed.emit();return
        application=self.application(identifier)
        p=self.process();w={'process':p,'buffer':b'','pending':set(),'queue':[],'ready':False,'token':self.application_token if application else self._session['token']};self.workers[identifier]=w
        def initialize():
            e=self.entries[identifier];config=self.settings.get('config',{}).get(identifier,read(self.path(identifier)/e.get('config','config.json'),{}))
            state=self.root/'state'/identifier/('application' if application else hashlib.sha256(self.storage_key.encode()).hexdigest())
            p.write(self.frame({'id':'initialize','operation':'initialize','arguments':{'path':str(self.path(identifier)),'stateDir':str(state),'config':config,'session':self._session}}))
        p.started.connect(initialize);p.readyReadStandardOutput.connect(lambda:self.receive(identifier,w));p.readyReadStandardError.connect(lambda:p.readAllStandardError())
        def failed(*_):
            if self.workers.get(identifier) is not w:return
            self.workers.pop(identifier);error='插件进程已停止，重新启用可重试'
            if self.application(identifier):self._failed_services.add(identifier)
            if self._page==identifier:self._error=error
            else:self._status=self.entries[identifier]['name']+'：'+error
            for request in w['pending']:self.response.emit(request,{'ok':False,'error':error})
            self.pageChanged.emit();self.changed.emit();p.deleteLater()
        p.finished.connect(failed);p.errorOccurred.connect(failed)
        program,args=self.command();p.start(program,args)
        def timeout():
            if self.workers.get(identifier) is w and not w['ready']:
                if self.application(identifier):self._failed_services.add(identifier)
                if self._page==identifier:self._error='插件启动超时'
                else:self._status=self.entries[identifier]['name']+'：插件启动超时'
                self.stop(identifier);self.pageChanged.emit()
        QTimer.singleShot(20000,self,timeout)
    def frame(self,request):return (json.dumps(request,ensure_ascii=True)+'\n').encode()
    def send(self,identifier,request):
        w=self.workers.get(identifier)
        if not w:return
        if 'service' in w:return
        if not w['ready']:
            if request.get('operation')=='session':w['queue']=[item for item in w['queue'] if item.get('operation')!='session']
            if len(w['queue'])<16:w['queue'].append(request)
            return
        w['process'].write(self.frame(request))
    def stop(self,identifier):
        self.bridge.stop_notifications(identifier)
        w=self.workers.pop(identifier,None)
        if not w:return
        for request in w['pending']:self.response.emit(request,{'ok':False,'error':'插件任务已取消'})
        if 'service' in w:
            w['service'].stop();self.changed.emit();return
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
        self.changed.emit()
    @Slot(str,str,result=str)
    def call(self,method,raw):
        return self.call_for(self._page,method,raw)
    def call_for(self,identifier,method,raw,*,agent=False,timeout_ms=20000,session=None):
        if identifier not in self.entries or not self.enabled(identifier) or not self.session_enabled(identifier):return ''
        if agent and method not in self.entries[identifier].get('agent',{}).get('methods',{}):return ''
        self.start(identifier)
        w=self.workers.get(identifier)
        if not w or len(w['pending'])>=8 or len(raw)>65536 or len(method)>128:return ''
        try:args=json.loads(raw)
        except ValueError:return ''
        if not isinstance(args,dict):return ''
        request=uuid.uuid4().hex;w['pending'].add(request)
        if 'service' in w:
            def invoke():
                if self.workers.get(identifier) is not w:return
                try:
                    result=self._pet.handle(method,args)
                    if method=='importAppearance':
                        self._pet_imports[result['importId']]=(request,w);return
                    value={'ok':True,'result':result}
                except (ValueError,OSError,TypeError) as error:value={'ok':False,'error':str(error)}
                w['pending'].discard(request);self.response.emit(request,value)
            QTimer.singleShot(0,self,invoke)
            def service_timeout():
                if self.workers.get(identifier) is w and request in w['pending']:
                    w['pending'].discard(request)
                    self.response.emit(request,{'ok':False,'error':'桌宠操作超时，可通过 status 查看导入结果'})
            QTimer.singleShot(timeout_ms,self,service_timeout)
            return request
        snapshot={**(session or self._session),'language':getattr(self.b,'language','zh')}
        self.send(identifier,{'id':request,'operation':'agentCall' if agent else 'call','arguments':{'method':method,'arguments':args,'session':snapshot}})
        def timeout():
            if self.workers.get(identifier) is w and request in w['pending']:
                if self.application(identifier):self._failed_services.add(identifier)
                if self._page==identifier:self._error='插件操作超时，已停止'
                else:self._status=self.entries[identifier]['name']+'：插件操作超时，已停止'
                self.stop(identifier);self.pageChanged.emit()
        QTimer.singleShot(timeout_ms,self,timeout);return request
    def pet_imported(self,token,result):
        pending=self._pet_imports.pop(token,None)
        if pending:
            request,worker=pending
            if self.workers.get('desktop-pet') is worker and request in worker['pending']:
                worker['pending'].discard(request)
                self.response.emit(request,{'ok':True,'result':{'appearance':result['appearance']['id'],'appearances':self._pet.appearances}} if result['ok'] else result)
    def receive(self,identifier,w):
        if self.workers.get(identifier) is not w:return
        w['buffer']+=bytes(w['process'].readAllStandardOutput())
        if len(w['buffer'])>LIMIT:
            if self._page==identifier:self._error='插件输出超过限制'
            else:self._status=self.entries[identifier]['name']+'：插件输出超过限制'
            if self.application(identifier):self._failed_services.add(identifier)
            self.stop(identifier);self.pageChanged.emit();return
        while b'\n' in w['buffer']:
            raw,w['buffer']=w['buffer'].split(b'\n',1)
            try:value=json.loads(raw)
            except ValueError:continue
            if not isinstance(value,dict):continue
            if value.get('type')=='event':
                if self.application(identifier) or w['token']==self._session.get('token'):self.host_event(identifier,value)
                continue
            request=value.get('id')
            if request=='initialize':
                if not value.get('ok'):
                    error=value.get('error','插件启动失败')
                    if self._page==identifier:self._error=error
                    else:self._status=self.entries[identifier]['name']+'：'+error
                    if self.application(identifier):self._failed_services.add(identifier)
                    self.stop(identifier);self.pageChanged.emit();return
                w['ready']=True;queue=w['queue'];w['queue']=[]
                for item in queue:self.send(identifier,item)
                self.pageChanged.emit();self.changed.emit()
            elif request in w['pending']:w['pending'].remove(request);self.response.emit(request,value)
    def host_event(self,identifier,event):
        kind=event.get('event');args=event.get('arguments',{});perms=self.entries[identifier].get('permissions',[])
        if not isinstance(args,dict):return
        if kind=='agent.notify':
            if 'session.write' in perms:self.bridge.notify(identifier,args)
            return
        if kind=='widget.event':
            target=args.get('session')
            if target is not None and (not isinstance(target,dict) or target.get('token')!=self._session.get('token') or target.get('workspace')!=self._session.get('workspace')):return
            if identifier==self._page and isinstance(args.get('topic'),str) and 0<len(args['topic'])<=80 and isinstance(args.get('data'),dict) and len(json.dumps(args['data'],ensure_ascii=False).encode('utf-8'))<=65536:
                self.event.emit(args['topic'],args['data'])
            return
        if self.application(identifier) and kind!='notification':
            target=args.get('session',{})
            if not isinstance(target,dict) or target.get('token')!=self._session.get('token'):return
        if kind=='page.open':
            if 'session.write' in perms:self.openPage(identifier)
            return
        if kind=='session.draft':
            if 'session.write' not in perms:return
            target=args.get('session',{});text=args.get('text','')
            if not isinstance(target,dict) or target.get('token')!=self._session.get('token') or not isinstance(text,str) or not text.strip() or len(text)>16000:return
            draft=getattr(self.b._view,'draft','')
            self.b.setDraft(draft+(chr(10) if draft and not draft.endswith(chr(10)) else '')+text)
            self.b.editorText.emit(self.b._view.draft)
            return
        if kind in ('files.copy','file.openWith'):
            if 'workspace.read' not in perms or not self._session.get('workspace'):return
            from . import plugin_file_actions
            root=Path(self._session['workspace']).resolve()
            if kind=='files.copy':
                values=args.get('paths',[])
                if not isinstance(values,list) or not 1<=len(values)<=100:return
                paths=[Path(value).resolve() for value in values if isinstance(value,str)]
                if len(paths)!=len(values) or any(not path.is_relative_to(root) or not path.exists() for path in paths):return
                if args.get('cut') and 'workspace.write' not in perms:return
                plugin_file_actions.copy_files(paths,bool(args.get('cut')))
            else:
                path=Path(args.get('path','')).resolve()
                if path.is_relative_to(root) and path.is_file():plugin_file_actions.open_with(path)
            return
        if kind in ('file.reveal','explorer.reveal'):
            if 'workspace.read' not in perms or not self._session.get('workspace'):return
            root=Path(self._session['workspace']).resolve();path=Path(args.get('path','')).resolve()
            if not path.is_relative_to(root):return
            if kind=='file.reveal':
                if path.exists():self.b.openChatboxPath(str(path),True)
                elif path.parent.is_relative_to(root) and path.parent.is_dir():self.b.openChatboxPath(str(path.parent),False)
            elif not self.openPage('file-tree'):self.b.toast.emit('请先启用文件树插件')
            else:self._selection=path.relative_to(root).as_posix();self.pageChanged.emit()
            return
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
        if self._busy or self.closed:return ''
        token=uuid.uuid4().hex
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
            if not self.closed:
                applied=done(result)
                if applied is False:result={'ok':False,'error':self._status or '插件设置未能保存'}
                self.changed.emit();self.b.toast.emit(self._status);self.managed.emit(token,result)
            p.deleteLater()
        p.finished.connect(finish);p.errorOccurred.connect(finish)
        program,args=self.command();p.start(program,args);QTimer.singleShot(30000,p,p.kill);return token
    @Slot(str,result=str)
    def importZip(self,url):
        path=QUrl(url).toLocalFile()
        if not path:self._status='请选择本机插件 ZIP 文件';self.changed.emit();return ''
        def done(result):
            if not result.get('ok'):return
            value=result['result'];m={**value['manifest'],'builtin':False};identifier=m['id'];old=copy.deepcopy(self.entries);options=copy.deepcopy(self.settings)
            old_path=self.path(identifier) if identifier in self.entries else None
            if self._page==identifier:self.closePage()
            self.stop(identifier);self.entries[identifier]=m;self.settings.setdefault('config',{}).setdefault(identifier,value['config'])
            if self.application(identifier):self.settings.setdefault('enabled',{})[identifier]=False
            if not self.save():self.entries=old;self.settings=options;return False
            if old_path and old_path!=self.path(identifier):
                import shutil;shutil.rmtree(old_path,ignore_errors=True)
            self._status='后台服务已导入，请启用以随应用运行' if self.application(identifier) else '插件已导入，可在当前会话启用'
        return self.manage({'id':'install','operation':'install','arguments':{'archive':path,'destination':str(self.root/'packages'),'reserved':[k for k,e in self.entries.items() if e.get('builtin')],'configs':self.settings.get('config',{})}},done)
    @Slot(str,str,result=str)
    def saveConfig(self,identifier,raw):
        if identifier not in self.entries or len(raw)>65536:return ''
        try:value=json.loads(raw);assert isinstance(value,dict)
        except (ValueError,AssertionError):self._status='请输入有效的 JSON 配置对象';self.changed.emit();return ''
        if identifier=='desktop-pet' and self.entries[identifier].get('builtin'):
            token=uuid.uuid4().hex
            def apply():
                try:result={'ok':True,'result':self._pet.configure(value)}
                except (ValueError,OSError) as error:result={'ok':False,'error':str(error)}
                self._status='操作已完成' if result['ok'] else result['error'];self.changed.emit();self.managed.emit(token,result)
            QTimer.singleShot(0,self,apply);return token
        def done(result):
            if not result.get('ok'):return
            old=copy.deepcopy(self.settings);self.settings.setdefault('config',{})[identifier]=value
            if not self.save():self.settings=old;return False
            if self._page==identifier:self.closePage()
            self.stop(identifier)
            if self.application(identifier) and self.enabled(identifier):self._failed_services.discard(identifier);self.start(identifier)
        return self.manage({'id':'config','operation':'config','arguments':{'path':str(self.path(identifier)),'config':value}},done)
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
        self._pet.close()
        processes=[w["process"] for w in self.workers.values() if 'process' in w]
        for identifier in list(self.workers):self.stop(identifier)
        for process in processes:
            if process.state()!=QProcess.NotRunning and not process.waitForFinished(300):process.kill();process.waitForFinished(100)
