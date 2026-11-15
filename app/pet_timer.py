"""Explicit timer preparation from the bound pet; never creates an owner session."""
import copy
import importlib.util
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Property, Signal, Slot, QTimeZone, QTimer
from .pi_sessions import SessionState, clean_extension_modes, clean_skill_modes, clean_blocked_tools


class PetTimer(QObject):
    changed = Signal()
    FIELDS = {'name', 'message', 'target', 'frequency', 'first_date', 'local_time', 'zone', 'interval_value', 'interval_unit'}

    def __init__(self, pet):
        super().__init__(pet)
        self.pet, self.b, self.m = pet, pet.b, pet.manager
        self.path = pet.directory / 'timer-drafts.json'
        self.drafts = {}
        self.opened = False
        self.owner = self.binding_id = self.incoming = self.error = self.notice = self.request = ''
        self.preview = None
        self.pending_owner = ''
        self.owners = []
        self.record = None
        try:
            saved = json.loads(self.path.read_text(encoding='utf-8'))
            if isinstance(saved, dict):
                self.drafts = {key:row for key,row in saved.items() if isinstance(key,str) and isinstance(row,dict)
                               and all(isinstance(row.get(field),str) for field in self.FIELDS)}
        except (OSError,ValueError,TypeError): pass
        self.save_timer = QTimer(self); self.save_timer.setSingleShot(True); self.save_timer.setInterval(300)
        self.save_timer.timeout.connect(self.save)
        self.m.response.connect(self.response)
        self.m.changed.connect(self.refresh)
        signal = getattr(self.b,'sidebarChanged',None)
        if signal is not None: signal.connect(self.refresh)
        name = '_pet_timer_existing_schedule'
        if name not in sys.modules:
            path = self.b.root/'umeko-plugins/scheduled-tasks/scripts/scheduled_tasks.py'
            spec = importlib.util.spec_from_file_location(name,path)
            module = importlib.util.module_from_spec(spec); sys.modules[name]=module; spec.loader.exec_module(module)
        self.Schedule = sys.modules[name].Schedule

    def empty(self):
        return {'name':'','message':'','target':'','frequency':'once','first_date':'','local_time':'',
                'zone':bytes(QTimeZone.systemTimeZoneId()).decode() or 'UTC','interval_value':'','interval_unit':'minutes'}

    def draft(self):
        return self.drafts.setdefault(self.owner,self.empty()) if self.owner else self.empty()

    def save(self, drafts=None):
        try:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            temp=self.path.with_suffix('.tmp');temp.write_text(json.dumps(self.drafts if drafts is None else drafts,ensure_ascii=False),encoding='utf-8')
            temp.replace(self.path);return True
        except OSError:
            self.error='无法保存定时草稿；未保存内容退出后可能丢失。'
            self.changed.emit();return False

    def close_service(self):
        self.save_timer.stop()
        if not self.save(): self.b.toast.emit(self.error)

    def rows(self):
        rows={r['id']:dict(r) for r in self.b._sessions if r.get('id')}
        for r in self.b._pool.records.values():
            if r.id and r.file and not r.global_agent and r.id not in rows:
                rows[r.id]={'id':r.id,'file':r.file,'workspace':r.workspace,'title':r.title,'model':r.model,'provider':r.provider}
        meta=self.b.store.data.get('sessionMeta',{})
        pending=getattr(self.b,'_session_files',None)
        result=[]
        for key,row in rows.items():
            details=meta.get(key,{})
            record=self.b._pool.find(key)
            if not row.get('file') or row.get('backend')=='dsh' or any(details.get(k) for k in ('archived','pluginSession','globalAgent')):continue
            if record and record.global_agent:continue
            if pending and (key in pending.deleted or key in pending.pending):continue
            result.append(row)
        return result

    @Slot()
    def refresh(self):
        if not self.opened:return
        self.owners=[{'id':r['id'],'name':r.get('title','会话')+' · '+(r.get('workspace') or '通用')+' · '+r['id'][:8]} for r in self.rows()]
        self.changed.emit()

    def available(self):
        status=self.pet.assistantStatus
        if not status.get('bound') or status.get('id')!=self.binding_id:
            raise ValueError('桌宠绑定已变化；请关闭后重新从胶囊输入 /定时任务。草稿已保留。')
        entry=self.m.entries.get('scheduled-tasks',{})
        if not entry.get('builtin') or not self.m.enabled('scheduled-tasks') or 'create' not in entry.get('agent',{}).get('methods',{}):
            raise ValueError('请先在 Desktop 启用内置定时任务 Widget')

    def source_row(self):
        self.available()
        if not self.owner:raise ValueError('请显式选择已有普通会话作为归属；悬浮小助手不能作为定时归属。')
        row=next((r for r in self.rows() if r['id']==self.owner),None)
        if not row or not Path(row['file']).is_file():raise ValueError('归属会话已删除或尚未持久化，请在 Desktop 打开已有普通会话后刷新。')
        workspace=row.get('workspace','')
        if not Path(workspace or self.b.store.directory/'workspace').is_dir():raise ValueError('归属会话目录不可用；不会替换目录或会话。')
        if workspace:
            project=next((p for p in self.b.store.data.get('projects',[]) if p.get('path')==workspace),None)
            if not project or project.get('archived') or project.get('id') in self.b.store.data.get('removedProjects',[]):
                raise ValueError('归属项目已归档、删除或目录已变化，请重新选择。')
        record=self.b._pool.find(self.owner)
        if record and (record.global_agent or record.workspace!=workspace or record.file!=row['file']):
            raise ValueError('归属会话身份或目录已变化，请在 Desktop 核对。')
        return row

    def resolve(self):
        row=self.source_row()
        record=self.b._pool.find(self.owner)
        if record is None:
            meta=self.b.store.data.get('sessionMeta',{}).get(self.owner,{})
            record=SessionState(id=self.owner,file=row['file'],workspace=row.get('workspace',''),title=row.get('title',''),
                                model=row.get('model') or self.b.store.data.get('selectedModel',''),provider=row.get('provider') or self.b.store.data.get('selectedProvider',''),loaded=False)
            record.extension_modes=clean_extension_modes(meta.get('extensionModes'))
            record.skill_modes=clean_skill_modes(meta.get('skillModes'))
            record.blocked_tools=clean_blocked_tools(meta.get('blockedTools'))
            record.pi_capabilities=copy.deepcopy(meta.get('piCapabilities') or {})
            record.reasoning_effort=meta.get('reasoningEffort','off')
            self.b._pool.touch(record)
        return record

    def targets(self):
        row=self.source_row()
        # The host needs only ordinary session identity for existing Bus permissions.
        record=self.b._pool.find(self.owner) or SessionState(id=self.owner,workspace=row.get('workspace',''))
        return self.m._host_services.scheduled_service().targets(record)

    @Property('QVariantMap',notify=changed)
    def state(self):
        try:targets=self.targets() if self.owner else []
        except ValueError:targets=[]
        return {'opened':self.opened,'owners':self.owners,'owner':self.owner,'draft':copy.deepcopy(self.draft()),
                'targets':targets,'error':self.error,'notice':self.notice,'review':self.preview or {},
                'busy':bool(self.request),'outcome':self.draft().get('outcome','')}

    @Slot(str,str,result='QVariantMap')
    def openCommand(self,text,identifier):
        if not re.match(r'^\s*/定时任务(?:\s|$)',text):return {'ok':False,'error':'请选择 /定时任务 命令'}
        status=self.pet.assistantStatus
        if not status.get('bound') or status.get('id')!=identifier:return {'ok':False,'error':'桌宠绑定已变化，请重新打开胶囊'}
        if self.request:
            self.notice='当前提交正在处理；新输入仍保留在胶囊，未加入本次创建。'
            self.opened=True;self.pet.restoreRequested.emit();self.changed.emit();return {'ok':True}
        self.save_timer.stop()
        if self.owner and not self.save():return {'ok':False,'error':self.error}
        self.owner='';self.binding_id=identifier;self.preview=None;self.error='';self.notice=''
        self.incoming=re.sub(r'^\s*/定时任务(?:\s|$)','',text,count=1)
        self.opened=True;self.refresh();self.pet.restoreRequested.emit()
        return {'ok':True}

    @Slot(str)
    def selectOwner(self,identifier):
        if self.request:return
        if identifier not in {r['id'] for r in self.rows()}:self.error='请选择已有普通会话';self.changed.emit();return
        self.owner=identifier;self.preview=None;self.error='';self.notice=''
        draft=self.draft()
        if self.incoming:
            if draft['message']:
                self.notice='已恢复该会话的定时草稿；新输入未替换旧指令，仍保留在胶囊中。'
            elif not draft.get('outcome'):draft['message']=self.incoming
        self.save_timer.start();self.changed.emit()

    @Slot(str,str)
    def setField(self,key,value):
        if self.request or not self.owner or key not in self.FIELDS or self.draft().get('outcome'):return
        self.draft()[key]=value;self.preview=None;self.error='';self.save_timer.start();self.changed.emit()

    def validate(self):
        row=self.source_row();draft=self.draft()
        if draft.get('outcome'):raise ValueError('该提交已有结果或待核对，不会重复创建。')
        if not draft['name'].strip():raise ValueError('请补充任务名称')
        if not draft['message'].strip():raise ValueError('请补充执行指令')
        if len(draft['name'])>120 or len(draft['message'])>8000 or len(json.dumps(draft['message']))>12000:raise ValueError('名称或指令超过现有接口长度限制')
        if draft['target'] not in {r['id'] for r in self.targets()}:raise ValueError('请显式选择当前归属会话可用的执行对象')
        if draft['frequency']=='once':
            if not all(draft[k] for k in ('first_date','local_time','zone')):raise ValueError('请补充日期、当地时间及时区')
            plan={k:draft[k] for k in ('frequency','first_date','local_time','zone')}
        elif draft['frequency']=='interval':
            if not draft['interval_value']:raise ValueError('请补充间隔数值，最短 15 秒')
            plan={k:draft[k] for k in ('frequency','interval_value','interval_unit')}
        else:raise ValueError('仅支持单次与固定间隔；每天固定时间不能转换成每隔 24 小时。')
        now=time.time();schedule=self.Schedule.from_dict(plan,now=now);due=schedule.next_after(now)
        if due is None:raise ValueError('计划必须有未来触发时间')
        return {'name':draft['name'].strip(),'message':draft['message'].strip(),'target':draft['target'],'schedule':plan,'enabled':True},row,due

    @Slot()
    def review(self):
        if self.request:return
        self.preview=None
        try:
            args,row,due=self.validate()
            plan=args['schedule']
            self.preview={'args':args,'source':{k:row.get(k,'') for k in ('id','file','workspace')},
                          'owner':row.get('title','')+' · '+self.owner,'targetName':next(r['name'] for r in self.targets() if r['id']==args['target']),
                          'scheduleText':('单次：'+plan['first_date']+' '+plan['local_time']+' · '+plan['zone'] if plan['frequency']=='once' else '每隔 '+str(plan['interval_value'])+' '+{'minutes':'分钟','hours':'小时','days':'天（24 小时）'}[plan['interval_unit']]),
                          'next':datetime.fromtimestamp(due).astimezone().isoformat(timespec='seconds')}
            self.error=''
        except (ValueError,KeyError,TypeError) as error:self.error=str(error)
        self.changed.emit()

    @Slot()
    def confirm(self):
        if not self.opened or self.request or not self.preview:return
        try:
            args,row,_=self.validate()
            source={k:row.get(k,'') for k in ('id','file','workspace')}
            if source!=self.preview['source'] or args!=self.preview['args']:raise ValueError('归属或参数已变化，请重新核对。')
            self.record=self.resolve()
            staged=copy.deepcopy(self.drafts);staged[self.owner]['outcome']='创建结果待核对；不会自动重试'
            if not self.save(staged):return
            self.drafts[self.owner]['outcome']=staged[self.owner]['outcome'];self.pending_owner=self.owner
            self.request=self.m.call_for('scheduled-tasks','save',json.dumps(args),session=self.m.bridge.snapshot(self.record))
            if not self.request:
                self.drafts[self.owner].pop('outcome',None);self.save();raise ValueError('服务不可用，未提交创建。')
            self.error=''
        except (ValueError,OSError,KeyError,TypeError) as error:self.error=str(error)
        self.changed.emit()

    def response(self,identifier,value):
        if not self.request or identifier!=self.request:return
        self.request='';self.preview=None
        if value.get('ok'):
            self.drafts[self.pending_owner]['outcome']='已创建，等待触发（不是执行完成）：'+value['result']['task_id'];self.error=''
        else:self.error=str(value.get('error','结果未知'))+'；请在 Desktop 核对，禁止自动重试。'
        self.save();self.changed.emit()

    @Slot()
    def edit(self):
        if not self.request:self.preview=None;self.changed.emit()

    @Slot()
    def close(self):
        self.save_timer.stop();self.save();self.opened=False;self.changed.emit()

    @Slot()
    def openDesktop(self):
        self.pet.restoreRequested.emit()
        if not self.owner:self.close();return
        try:self.source_row()
        except ValueError as error:self.error=str(error);self.changed.emit();return
        self.b.openSession(self.owner)
        # Opening a session may use an asynchronous history preview. Do not bind a
        # Widget page to the previously visible session while that switch is pending.
        if self.b._view.id==self.owner and self.m.openPage('scheduled-tasks'):self.close()
        else:self.notice='请在 Desktop 选中该会话后打开定时任务 Widget。';self.changed.emit()

    @Slot()
    def newDraft(self):
        if self.request or not self.draft().get('outcome','').startswith('已创建'):return
        self.drafts[self.owner]=self.empty();self.preview=None;self.error='';self.notice='';self.save();self.changed.emit()

    @Slot()
    def acknowledgeNotCreated(self):
        if self.request or not self.draft().get('outcome','').startswith('创建结果待核对'):return
        self.draft().pop('outcome',None);self.preview=None;self.error='请重新核对并确认；尚未重新提交。';self.save();self.changed.emit()
