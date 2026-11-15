"""Explicit project input using the native record-bound prompt and follow-up paths."""
import copy
import json
import re
from pathlib import Path
from PySide6.QtCore import QObject, Property, Signal, Slot
from .pi_sessions import SessionState, clean_extension_modes, clean_skill_modes, clean_blocked_tools


class PetProject(QObject):
    changed=Signal()

    def __init__(self,pet):
        super().__init__(pet)
        self.pet=pet;self.b=pet.b
        self.opened=False;self.options=[];self.selected='';self.body='';self.error='';self.binding=''
        self.captured=None;self.pending=False;self.incoming='';self.drafts={};self.label=''
        self.path=pet.directory/'project-input.json'
        self.submission={}
        try:
            value=json.loads(self.path.read_text(encoding='utf-8'))
            if isinstance(value,dict):self.submission=value
        except (OSError,ValueError):pass
        self.b._pool.event.connect(self.observe)

    def rows(self):
        projects={p['path']:p for p in self.b.store.data.get('projects',[]) if not p.get('archived') and p.get('id') not in self.b.store.data.get('removedProjects',[])}
        return [r for r in self.pet.taskSchedule.rows() if r.get('workspace') in projects and Path(r.get('file','')).is_file() and Path(r['workspace']).is_dir()]

    @Property('QVariantMap',notify=changed)
    def state(self):
        return {'opened':self.opened,'options':self.options,'selected':self.selected,'body':self.body,'error':self.error,'busy':self.pending,'submission':self.submission,'label':self.label,'detail':(self.captured or {}).get('workspace','')+' · '+self.selected}

    @Slot(str,str,result='QVariantMap')
    def openCommand(self,text,binding):
        status=self.pet.assistantStatus
        if not re.match(r'^\s*/项目(?:\s|$)',text):return {'ok':False,'error':'请输入 /项目 命令'}
        if not status.get('bound') or status.get('id')!=binding:return {'ok':False,'error':'桌宠绑定已变化，请重新打开胶囊'}
        if self.pending:return {'ok':False,'error':'正在打开项目会话，请稍候；输入仍保留'}
        self.binding=binding;self.incoming=re.sub(r'^\s*/项目(?:\s|$)','',text,count=1)
        self.error=''
        self.options=[{'id':r['id'],'name':r.get('title','会话')+' · '+Path(r['workspace']).name,'detail':r['workspace']+' · '+r['id']} for r in self.rows()]
        if self.submission:self.error='上次发送记录已保留，请先在 Desktop 核对；不会自动重发。'
        self.opened=True;self.changed.emit()
        return {'ok':True}

    @Slot(str)
    def setBody(self,text):
        if self.pending:return
        self.body=text
        if self.selected:self.drafts[self.selected]=text

    @Slot()
    def leaveProject(self):
        # Deactivate the target, not its draft. A later default-mode command is
        # a transfer into that saved draft even if its ID was selected before.
        self.selected='';self.captured=None;self.label='';self.body='';self.incoming=''
        self.changed.emit()

    @Slot(str,result='QVariantMap')
    def select(self,identifier):
        if self.pending:return {'ok':False,'error':'正在提交，请稍候'}
        row=next((r for r in self.rows() if r['id']==identifier),None)
        if not row:return {'ok':False,'error':'项目或会话不可用，请重新打开 /项目'}
        saved=self.drafts.get(identifier,'')
        if identifier!=self.selected and saved and self.incoming:
            self.error='目标已有桌宠草稿，未覆盖；请保留正文后用目标按钮切换。'
            self.changed.emit();return {'ok':False,'error':self.error}
        body=self.incoming if self.incoming else ('' if identifier==self.selected and re.match(r'^\s*/项目(?:\s|$)',saved) else saved)
        self.selected=identifier;self.captured={k:row.get(k,'') for k in ('id','workspace','file')}
        self.label=row.get('title') or Path(row['workspace']).name
        self.body=body;self.drafts[identifier]=body;self.incoming='';self.error='';self.changed.emit()
        return {'ok':True,'text':body}

    @Slot(str,str,result='QVariantMap')
    def submitText(self,text,binding):
        if binding!=self.binding or not self.opened:return {'ok':False,'error':'目标已失效，请重新选择'}
        self.setBody(text)
        # A new, different input may follow a positively acknowledged native input.
        # An uncertain submission or the same text needs explicit review instead.
        if self.submission and self.submission.get('acknowledged') and text.strip()!=self.submission.get('body'):
            self.submission={}
        if self.submission:return {'ok':False,'error':'上次发送待核对或正文重复；请用目标菜单查看 Desktop 后允许新发送。'}
        self.send()
        ok=self.submission.get('status','').startswith(('已提交','已进入','已收到'))
        if ok:self.body='';self.drafts[self.selected]=''
        self.changed.emit()
        return {'ok':ok,'error':self.error}

    def valid(self):
        status=self.pet.assistantStatus
        if not status.get('bound') or status.get('id')!=self.binding:return False
        row=next((r for r in self.rows() if r['id']==self.selected),None)
        if not row or {k:row.get(k,'') for k in ('id','workspace','file')}!=self.captured:return False
        record=self.b._pool.find(self.selected)
        return record is None or (not record.global_agent and record.workspace==row['workspace'] and record.file==row['file'])

    def save(self):
        try:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            temp=self.path.with_suffix('.tmp');temp.write_text(json.dumps(self.submission,ensure_ascii=False),encoding='utf-8');temp.replace(self.path)
            return True
        except OSError:
            self.error='无法保存发送恢复记录；未自动重试，退出后新状态可能丢失。'
            return False

    def record(self):
        record=self.b._pool.find(self.selected)
        if record:return record
        row=next(r for r in self.rows() if r['id']==self.selected)
        meta=self.b.store.data.get('sessionMeta',{}).get(self.selected,{})
        record=SessionState(id=self.selected,file=row['file'],workspace=row['workspace'],title=row.get('title',''),loaded=False,
                            model=row.get('model') or self.b.store.data.get('selectedModel',''),provider=row.get('provider') or self.b.store.data.get('selectedProvider',''))
        record.extension_modes=clean_extension_modes(meta.get('extensionModes'))
        record.skill_modes=clean_skill_modes(meta.get('skillModes'))
        record.blocked_tools=clean_blocked_tools(meta.get('blockedTools'))
        record.pi_capabilities=copy.deepcopy(meta.get('piCapabilities') or {})
        record.reasoning_effort=meta.get('reasoningEffort','off')
        self.b._pool.touch(record)
        return record

    @Slot()
    def send(self):
        if not self.opened or self.pending or self.submission:return
        if not self.selected or not self.valid():self.error='目标身份或目录已变化，请重新选择；正文已保留。';self.changed.emit();return
        text=self.body.strip()
        if not text or len(text)>16000:self.error='请输入 1–16000 字符的项目指令';self.changed.emit();return
        record=self.record()
        if getattr(self.b,'_kernel_busy',False) or record.approval or record.prepared_task or record.task_attempt:
            self.error='内核、审批或任务尝试需要在 Desktop 处理；正文已保留。';self.changed.emit();return
        if self.pet.manager.checkpoint_locked(record.workspace):
            self.error='项目正在恢复检查点，请稍后发送。';self.changed.emit();return
        if record.busy and (record.phase!='running' or not record.ready or not record.process):
            self.error='会话正在加载或不可接收排队输入，请稍后发送。';self.changed.emit();return
        if not record.busy and sum(r.busy and not r.global_agent for r in self.b._pool.records.values())>=8:
            self.error='原生会话并发已满，请稍后发送。';self.changed.emit();return
        self.submission={**self.captured,'body':text,'status':'结果待核对；不会自动重发'}
        if not self.save():self.submission={};self.changed.emit();return
        self.pending=True
        try:
            if record.busy:
                # Native queue events are rendered by Desktop and restored by its
                # existing queue_returned/queue_rejected handling. No private queue.
                self.b._write_pi({'type':'follow-up','text':text,'images':[]},record)
                self.submission['status']='已提交原生队列，等待回执（未执行完成）'
            else:
                old_messages=list(record.messages);old_optimistic=record.optimistic_user
                record.messages.extend([{'role':'user','text':text,'error':False},{'role':'assistant','text':'','error':False}])
                record.optimistic_user=True
                if not self.b._command_pi('prompt',record=record,text=text,images=[]):
                    record.messages=old_messages;record.optimistic_user=old_optimistic
                    self.submission['status']='启动未成功，请核对 Desktop；不会自动重发'
                else:
                    record.body_dirty=True
                    self.submission['status']='已提交项目会话（未执行完成）'
            self.error=self.submission['status']
            self.save()
        except (OSError,RuntimeError,ValueError) as error:
            self.error=str(error)+'；结果待核对，不会自动重发。'
        finally:self.pending=False;self.changed.emit()

    def observe(self,record,event):
        if not self.submission or record.id!=self.submission.get('id') or record.workspace!=self.submission.get('workspace'):return
        kind=event.get('type')
        if kind=='queue' and any(r.get('text')==self.submission.get('body') for r in event.get('items',[])):
            self.submission['status']='已进入原生队列；可在 Desktop 查看、编辑或取消'
        elif kind=='user_start' and event.get('text')==self.submission.get('body'):
            self.submission['status']='已收到原生会话回执（未执行完成）'
        elif (kind=='queue_rejected' and event.get('text')==self.submission.get('body')) or (kind=='queue_returned' and self.submission.get('body') in [*event.get('steering',[]),*event.get('followUp',[])]):
            self.submission['status']='原生队列已返回输入；请在 Desktop 核对恢复草稿'
        else:return
        self.submission['acknowledged']=kind in ('queue','user_start')
        self.error=self.submission['status'];self.save();self.changed.emit()

    @Slot()
    def acknowledge(self):
        if self.pending:return
        previous=self.submission;self.submission={}
        if not self.save():self.submission=previous
        else:self.error='已清除发送保护；请再次核对目标后明确发送，不会自动重发。'
        self.changed.emit()

    @Slot()
    def openDesktop(self):
        identifier=self.submission.get('id') or self.selected
        if identifier:self.b.openSession(identifier)
        self.pet.restoreRequested.emit()

    @Slot()
    def close(self):
        self.opened=False;self.changed.emit()
