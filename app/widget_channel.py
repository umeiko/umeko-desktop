"""The existing desktop tool's session-bound Widget RPC and push channel."""
from __future__ import annotations
import copy, hashlib, json, os, re, time
from collections import OrderedDict, deque
from pathlib import Path
from PySide6.QtCore import QObject, QTimer, QUrl


class WidgetChannel(QObject):
    def __init__(self, manager):
        super().__init__(manager)
        self.m=manager;self.b=manager.b;self.calls=OrderedDict();self.management={}
        self.states=OrderedDict();self.current={'token':'','key':'','snapshot':{},'messages':[],'sequence':0};self.rates={}
        manager.response.connect(self.response);manager.managed.connect(self.managed)
        manager.sessionChanged.connect(self.bind)
        pool=getattr(self.b,'_pool',None)
        if pool:pool.event.connect(self.pi_event)

    @property
    def token(self):return self.current['token']
    @property
    def key(self):return self.current['key']
    @property
    def messages(self):return self.current['messages']
    @property
    def sequence(self):return self.current['sequence']

    @staticmethod
    def workspace(value):return os.path.normcase(os.path.abspath(value)) if value else ''

    def snapshot(self,record):
        return {'token':record.key,'id':record.id,'workspace':record.workspace,'title':record.title,'busy':record.busy,
            'messages':[{'role':row.get('role',''),'text':row.get('text','')[:2000]} for row in getattr(record,'messages',[])[-8:]]}

    def log_path(self,state=None):
        state=state or self.current
        return self.m.root/'messages'/(hashlib.sha256(state['key'].encode()).hexdigest()+'.json')

    def remember(self,record):
        snapshot=self.snapshot(record);key=record.id or 'draft:'+record.key
        state=self.states.get(record.key)
        if state is None:
            state=next((value for value in self.states.values() if value['key']==key and self.workspace(value['snapshot'].get('workspace'))==self.workspace(record.workspace)),None)
        if state is None:
            state={'token':record.key,'key':key,'snapshot':snapshot,'messages':[],'sequence':0}
            try:
                path=self.log_path(state)
                if path.stat().st_size<=2*1024*1024:
                    value=json.loads(path.read_text(encoding='utf-8'));rows=value['messages'];sequence=value['sequence']
                    if not isinstance(rows,list) or type(sequence) is not int or any(not isinstance(row,dict) or type(row.get('sequence')) is not int or not isinstance(row.get('widgetId'),str) for row in rows):raise ValueError('Invalid Widget message history')
                    for row in rows:
                        if row.get('delivery') in ('pending','sending','queued'):row['delivery']='interrupted'
                    state['messages']=rows;state['sequence']=sequence
            except (OSError,ValueError,KeyError,TypeError):pass
        changed=state['key']!=key
        if self.workspace(state['snapshot'].get('workspace'))!=self.workspace(record.workspace):
            for row in state['messages']:
                if row['delivery'] in ('pending','sending','queued'):row.update(delivery='cancelled',error='目标聊天的工作目录已改变')
            changed=True
        if state['token']!=record.key:
            for row in state['messages']:
                if row['delivery'] in ('sending','queued'):row['delivery']='interrupted'
            changed=True
        state.update(token=record.key,key=key,snapshot=snapshot)
        self.states[record.key]=state;self.states.move_to_end(record.key)
        while len(self.states)>128:
            candidate=next((token for token,value in self.states.items() if value is not self.current and value is not state and not any(row['delivery'] in ('pending','sending','queued') for row in value['messages']) and not any(item['token']==token and item['status']=='running' for item in self.calls.values())),None)
            if candidate is None:break
            self.states.pop(candidate)
        if changed:self.save(state)
        return state

    def bind(self):
        if self.m.closed:return
        self.current=self.remember(self.b._view)
        QTimer.singleShot(0,self,self.flush)

    def save(self,state=None):
        state=state or self.current
        try:
            path=self.log_path(state);path.parent.mkdir(parents=True,exist_ok=True)
            state['messages']=state['messages'][-100:]
            while state['messages'] and len(json.dumps(state['messages'],ensure_ascii=False).encode('utf-8'))>1024*1024:state['messages'].pop(0)
            temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps({'sequence':state['sequence'],'messages':state['messages']},ensure_ascii=False),encoding='utf-8');temporary.replace(path)
        except OSError:self.b.toast.emit('Widget 消息记录保存失败')

    def require(self, identifier, active=False):
        if identifier not in self.m.entries:raise ValueError('Widget ID 不存在')
        if active and (not self.m.enabled(identifier) or not self.m.session_enabled(identifier)):raise ValueError('请先在当前会话激活该 Widget')
        return self.m.entries[identifier]

    def document(self,identifier):
        entry=self.require(identifier);root=self.m.path(identifier).resolve()
        name=entry.get('agent',{}).get('document','');path=(root/name).resolve()
        if not name or not path.is_relative_to(root) or not path.is_file() or path.stat().st_size>65536:raise ValueError('Widget 缺少可读取的 Agent 使用文档，请更新插件包')
        return path

    def list(self,active_only=False,caller=None):
        rows=[]
        for entry in self.m.rows:
            identifier=entry['id'];application=self.m.application(identifier)
            active=entry['enabled'] and (application or entry['sessionEnabled'] and (caller is None or caller is self.b._view))
            if active_only and not active:continue
            try:document=str(self.document(identifier))
            except ValueError:document=''
            rows.append({'id':identifier,'name':entry['name'],'version':entry['version'],'summary':entry.get('summary',''),
                'lifecycle':entry['lifecycle'],'enabled':entry['enabled'],'active':active,'open':self.m._page==identifier and (caller is None or caller is self.b._view),'running':entry['running'],'starting':entry['starting'],
                'document':document,'methods':list(entry.get('agent',{}).get('methods',{}))})
        return rows

    def sdk_path(self):
        for relative in ('desktop-plugin-resources/umeko-plugin-sdk.zip','build/desktop-plugin-resources/umeko-plugin-sdk.zip'):
            path=self.b.root/relative
            if path.is_file():return path.resolve()
        raise ValueError('Widget SDK 资源缺失，请重新构建插件开发资源')

    def execute(self,operation,args,caller,control):
        target=caller or self.b._view
        name=operation.removeprefix('widgets.')
        identifier=args.get('id','')
        if target is not self.b._view and name not in ('list','resource','messages','result') and not (name in ('docs','call') and self.m.application(identifier)):
            raise ValueError('会话级 Widget 接口绑定当前显示的主会话，请切回该会话后调用')
        state=self.remember(target)
        if name=='list':return {'widgets':self.list(bool(args.get('activeOnly',False)),target),'sessionId':target.id}
        if name=='resource':return {'path':str(self.sdk_path())}
        if name=='docs':
            entry=self.require(identifier);path=self.document(identifier)
            return {'id':identifier,'summary':entry['summary'],'lifecycle':entry.get('lifecycle','session'),'document':{'path':str(path),'text':path.read_text(encoding='utf-8-sig')},
                    'methods':entry.get('agent',{}).get('methods',{}),'callOperation':'widgets.call','resultOperation':'widgets.result','updatesOperation':'widgets.messages'}
        if name=='messages':
            if identifier:self.require(identifier)
            after=args.get('after',0);limit=args.get('limit',50)
            if type(after) is not int or after<0 or type(limit) is not int or not 1<=limit<=100:raise ValueError('after >= 0；limit 必须为 1–100')
            rows=[row for row in state['messages'] if row['sequence']>after and (not identifier or row['widgetId']==identifier)]
            page=rows[:limit]
            return {'updates':copy.deepcopy(page),'nextCursor':page[-1]['sequence'] if page else max(after,state['sequence']),'hasMore':len(rows)>limit,
                    'historyTruncated':bool(state['messages'] and after<state['messages'][0]['sequence']-1)}
        if name=='result':
            request=args.get('requestId');item=self.calls.get(request)
            same_chat=item and item['session'].get('id') and not item['session']['id'].startswith('pending-') and item['session']['id']==target.id and self.workspace(item['session'].get('workspace'))==self.workspace(target.workspace)
            if not item or item['token']!=target.key and not same_chat:raise ValueError('该 Widget 请求不存在或不属于当前会话')
            updates=[row for row in state['messages'] if row['requestId']==request and row['widgetId']==item['id']]
            return {**{key:copy.deepcopy(value) for key,value in item.items() if key not in ('token','control','session')},'requestId':request,'updates':copy.deepcopy(updates)}
        if name=='import':
            path=Path(args.get('path','')).expanduser()
            if not path.is_file():raise ValueError('请选择存在的 Widget ZIP')
            token=self.m.importZip(QUrl.fromLocalFile(str(path.resolve())).toString())
        elif name=='config':
            self.require(identifier);config=args.get('config')
            if not isinstance(config,dict):raise ValueError('config 必须为 JSON 对象')
            token=self.m.saveConfig(identifier,json.dumps(config,ensure_ascii=False))
        elif name=='call':
            entry=self.require(identifier,True);method=args.get('method');arguments=args.get('arguments',{});timeout=args.get('timeoutMs',20000)
            if not isinstance(arguments,dict) or len(json.dumps(arguments))>65536:raise ValueError('arguments 必须为最多 64 KiB 的 JSON 对象')
            if method not in entry.get('agent',{}).get('methods',{}):raise ValueError('该方法未在 Widget 的 Agent 接口中公开，请先调用 widgets.docs')
            if type(timeout) is not int or not 1000<=timeout<=120000:raise ValueError('timeoutMs 必须为 1000–120000')
            while len(self.calls)>=64:
                old=next((key for key,value in self.calls.items() if value['status']!='running'),None)
                if old is None:raise ValueError('Widget 待完成请求过多，请稍后重试')
                self.calls.pop(old)
            snapshot=self.snapshot(target)
            token=self.m.call_for(identifier,method,json.dumps(arguments,ensure_ascii=False),agent=True,timeout_ms=timeout,session=snapshot)
            if not token:raise ValueError('Widget 当前无法接受调用')
            job=control._new_job(operation,'running')
            control.jobs[job]['widgetSession']=target.key
            control.jobs[job]['widgetSessionId']=target.id;control.jobs[job]['widgetWorkspace']=target.workspace
            self.calls[token]={'id':identifier,'method':method,'token':target.key,'session':{key:snapshot[key] for key in ('token','id','workspace')},'status':'running','jobId':job,'control':control}
            return {'status':'accepted','requestId':token,'jobId':job,'resultOperation':'widgets.result'}
        elif name in ('enable','activate'):
            self.require(identifier);value=args.get('enabled')
            if type(value) is not bool:raise ValueError('enabled 必须是布尔值')
            if name=='enable':self.m.setEnabled(identifier,value)
            else:self.m.setSessionEnabled(identifier,value)
            actual=self.m.enabled(identifier) if name=='enable' else self.m.session_enabled(identifier)
            if actual!=value:raise ValueError(self.m.status or 'Widget 设置未能保存')
            return {'status':'applied','id':identifier,'enabled':value}
        elif name=='open':
            self.require(identifier,True)
            if not self.m.openPage(identifier):raise ValueError('该 Widget 没有可打开的页面')
            return {'status':'applied','id':identifier}
        elif name=='close':self.m.closePage();return {'status':'applied'}
        elif name=='uninstall':
            self.require(identifier)
            if not self.m.uninstall(identifier):raise ValueError('不能卸载内置 Widget，或当前正在管理插件')
            return {'status':'applied'}
        elif name=='exportSdk':
            path=Path(args.get('path','')).expanduser()
            if not path.is_absolute():raise ValueError('path 必须是本机绝对路径')
            if not self.m.exportSdk(QUrl.fromLocalFile(str(path)).toString()):raise ValueError('无法导出 Widget SDK')
            return {'status':'applied','path':str(path)}
        else:raise ValueError('未知 Widget 操作')
        if not token:raise ValueError('Widget 管理正在进行，请稍后重试')
        job=control._new_job(operation,'running');control.jobs[job].update(widgetSession=target.key,widgetSessionId=target.id,widgetWorkspace=target.workspace);self.management[token]=(control,job)
        return {'status':'accepted','jobId':job}

    def response(self,request,value):
        item=self.calls.get(request)
        if not item or item['status']!='running':return
        if len(json.dumps(value,ensure_ascii=False).encode('utf-8'))>524288:value={'ok':False,'error':'Widget 返回超过 512 KiB，请通过工作区文件提供大型结果'}
        item.update(status='completed' if value.get('ok') else 'failed',result=copy.deepcopy(value))
        item['control']._finish(item['jobId'],copy.deepcopy(value))

    def managed(self,token,value):
        pending=self.management.pop(token,None)
        if pending:pending[0]._finish(pending[1],value)

    def notify(self,identifier,args):
        if self.m.closed:return
        if identifier not in self.m.entries or not self.m.enabled(identifier) or not self.m.session_enabled(identifier):return
        message=args.get('message');event_id=args.get('id');request=args.get('requestId','');data=args.get('data',{});wake=args.get('wake',True)
        if not isinstance(message,str) or not message.strip() or len(message)>8000 or not isinstance(event_id,str) or not re.fullmatch('[a-f0-9]{32}',event_id) or not isinstance(data,dict) or type(wake) is not bool:return
        if not isinstance(request,str) or len(request)>64 or len(json.dumps(args,ensure_ascii=False).encode('utf-8'))>32768:return
        application=self.m.application(identifier);call=self.calls.get(request) if request else None
        if request:
            if call and call['id']!=identifier:return
            if not call and request not in self.m.workers.get(identifier,{}).get('pending',set()):return
        target=args.get('session')
        if call:
            if target is not None and (not isinstance(target,dict) or target.get('token')!=call['token']):
                self.reject(identifier,event_id,request,'通知的目标聊天与原请求不一致');return
            target=call['session']
        elif target is None:
            if application:self.reject(identifier,event_id,request,'应用级通知必须指定已捕获的目标聊天');return
            target=self.m._session
        if not isinstance(target,dict) or not isinstance(target.get('token'),str):return
        state=self.states.get(target['token'])
        if not state or self.workspace(target.get('workspace'))!=self.workspace(state['snapshot'].get('workspace')):
            self.reject(identifier,event_id,request,'目标聊天引用已失效或工作目录已改变');return
        if not application and state is not self.current:return
        if any(row['id']==event_id for row in state['messages']):return
        now=time.monotonic();rate=self.rates.setdefault(identifier,deque())
        while rate and now-rate[0]>60:rate.popleft()
        if len(rate)>=60:return
        rate.append(now);state['sequence']+=1
        row={'id':event_id,'sequence':state['sequence'],'widgetId':identifier,'name':self.m.entries[identifier]['name'],'requestId':request,
            'sessionId':state['snapshot'].get('id',''),'session':{key:target.get(key,'') for key in ('token','id','workspace')},
            'message':message,'data':copy.deepcopy(data),'wake':wake,'timestamp':int(time.time()*1000),'delivery':'pending'}
        state['messages'].append(row);self.save(state);self.flush()

    def reject(self,identifier,event_id,request,error):
        data={'id':event_id,'requestId':request,'delivery':'failed','error':error}
        if identifier in self.m.workers:self.m.send(identifier,{'id':'delivery-'+event_id,'operation':'event','arguments':{'name':'agent.delivery','data':data}})

    def stop_notifications(self,identifier):
        seen=set()
        for state in self.states.values():
            if id(state) in seen:continue
            seen.add(id(state));changed=False
            for row in state['messages']:
                if row['widgetId']==identifier and row['delivery']=='pending':row.update(delivery='cancelled',error='插件已停止');changed=True
            if changed:self.save(state)

    def record_for(self,state):
        snapshot=state['snapshot'];view=self.b._view
        if view.key==state['token']:record=view
        else:
            pool=getattr(self.b,'_pool',None)
            record=pool.records.get(state['token']) if pool else None
            if not record and pool and snapshot.get('id'):record=pool.find(snapshot['id'])
        if record and self.workspace(record.workspace)==self.workspace(snapshot.get('workspace')):return record
        return None

    def flush(self):
        if self.m.closed:return
        seen=set()
        for state in list(self.states.values()):
            if id(state) in seen:continue
            seen.add(id(state));self.flush_state(state)

    def flush_state(self,state):
        record=self.record_for(state)
        if record is None:return
        for row in state['messages']:
            if row['delivery']!='pending':continue
            identifier=row['widgetId']
            if identifier not in self.m.entries or not self.m.enabled(identifier) or not self.m.application(identifier) and (state is not self.current or not self.m.session_enabled(identifier)):
                self.receipt(row,'cancelled',state=state);continue
            if record.busy and (not getattr(record,'ready',False) or getattr(record,'phase','')!='running'):return
            if not getattr(record,'ready',False) and not row['wake']:continue
            if not hasattr(self.b,'_write_pi'):continue
            self.receipt(row,'sending',state=state)
            payload={'type':'widget-notify','notification':{key:value for key,value in row.items() if key!='delivery'}}
            if not record.busy and row['wake']:
                if not self.b._command_pi('widget-notify',record,notification=payload['notification']):self.receipt(row,'failed',state=state)
            elif getattr(record,'ready',False):self.b._write_pi(payload,record)
            else:row['delivery']='pending'

    def receipt(self,row,status,error='',state=None):
        state=state or self.current
        row['delivery']=status
        if error:row['error']=str(error)[:1000]
        self.save(state);data={'id':row['id'],'requestId':row['requestId'],'sessionId':state['snapshot'].get('id',''),'delivery':status,**({'error':error} if error else {})}
        identifier=row['widgetId'];worker=self.m.workers.get(identifier)
        if worker and (self.m.application(identifier) or worker['token']==state['token']):self.m.send(identifier,{'id':'delivery-'+row['id'],'operation':'event','arguments':{'name':'agent.delivery','data':data}})
        if self.m._page==identifier and state is self.current:self.m.event.emit('agent.delivery',data)

    def pi_event(self,record,event):
        if self.m.closed:return
        state=self.states.get(record.key)
        if not state or record.key!=state['token']:return
        if event.get('type') in ('ready','session','state'):state=self.remember(record)
        if event.get('type')=='widget_delivery':
            row=next((row for row in state['messages'] if row['id']==event.get('id')),None)
            if row and (state is self.current or self.m.application(row['widgetId'])):self.receipt(row,event.get('status','failed'),event.get('error',''),state)
        elif event.get('type') in ('ready','done'):QTimer.singleShot(0,self,self.flush)
        elif event.get('type')=='exit':
            for row in state['messages']:
                if row['delivery'] in ('sending','queued'):self.receipt(row,'failed','Agent 进程已退出',state)
