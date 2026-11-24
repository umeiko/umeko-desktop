"""Explicit one-shot pet handoff to an existing global conversation.

This UI does not bind the companion, stream replies, approve or stop runs.
Those actions remain in the existing target conversation.
"""
from PySide6.QtCore import QObject, Property, Signal, Slot
from .pet_agent_target import PetAgentTarget

REASONS = {
    'unavailable': '全局智能体服务不可用；请在 Desktop 检查配置。',
    'target_changed': '目标或配置已变化，请重新选择；草稿已保留。',
    'already_submitted': '本次已尝试提交；请在目标会话核对，不会自动重发。',
    'busy': '目标正在执行或等待审批；本入口不插话，草稿已保留。',
    'run_changed': '原运行已变化，未追加；草稿已保留，请重新预览。',
    'capacity': '全局智能体并发已满；草稿已保留。',
    'invalid_text': '请输入 1–16000 字符。',
    'uncertain': '提交结果待核对，请打开目标会话；不会自动重发。',
    'failed': '未能启动，请打开目标会话核对；不会自动重发。',
}


class PetAgentEntry(QObject):
    changed = Signal()

    def __init__(self, pet):
        super().__init__(pet)
        self.pet = pet
        self.opened = False
        self.options = []
        self.target = None
        self.drafts = {}
        self.draft_key = None
        self.body = ''
        self.notice = ''
        self.preview = False
        self.attempted = False
        self.preview_run = None
        self.follow_up_pending = None
        self.pet.manager.b._pool.event.connect(self.observe)

    @property
    def bus(self):
        return self.pet.manager.global_agents

    @Property('QVariantMap', notify=changed)
    def state(self):
        row = self.target.row if self.target else {}
        record = self.target.record if self.target else None
        return {'opened': self.opened, 'options': self.options,
                'selected': self.target.identifier if self.target else '',
                'name': (row or {}).get('name', ''), 'body': self.body,
                'workspace': record.workspace if record else '',
                'model': record.model if record else '', 'notice': self.notice,
                'preview': self.preview, 'attempted': self.attempted,
                'followUp': self.preview_run is not None}

    @Slot()
    def open(self):
        self.refresh()
        self.opened = True
        self.changed.emit()

    @Slot()
    def refresh(self):
        bus = self.bus
        self.options = []
        # Inspect only. Never call record/ensure or enable a service.
        if not bus.m.closed and bus.active and bus.m.enabled('global-agents'):
            for identifier, row in bus.agents.items():
                if identifier == bus.pet_assistant_id:
                    continue
                target = PetAgentTarget(bus, identifier)
                reason = target._unavailable(allow_follow_up=True)
                self.options.append({'id': identifier, 'name': row.get('name') or identifier,
                                     'available': not reason, 'reason': REASONS.get(reason, '')})
        if not self.options:
            self.notice = '没有可选的已有全局智能体。请在 Desktop 配置；此处不会自动创建或启用。'
        self.changed.emit()

    @Slot(str)
    def select(self, identifier):
        if not self.opened or self.follow_up_pending:
            return
        target = PetAgentTarget(self.bus, identifier)
        if identifier == self.bus.pet_assistant_id or target._unavailable(allow_follow_up=True):
            self.notice = REASONS.get(target._unavailable(allow_follow_up=True), '请选择已有的其他全局智能体。')
            self.changed.emit()
            return
        if self.draft_key is not None:
            self.drafts[self.draft_key] = self.body
        self.target = target
        self.draft_key = (identifier, id(target.row))
        self.body = self.drafts.get(self.draft_key, '')
        self.preview = self.attempted = False
        self.preview_run = None
        self.notice = ''
        self.changed.emit()

    @Slot(str)
    def setBody(self, text):
        self.body = text
        if self.draft_key is not None:
            self.drafts[self.draft_key] = text
        self.preview = False
        self.changed.emit()

    @Slot()
    def prepare(self):
        if not self.opened or not self.target or self.attempted:
            return
        reason = self.target._unavailable(allow_follow_up=True)
        if not reason and (not self.body.strip() or len(self.body) > 16000):
            reason = 'invalid_text'
        self.notice = REASONS.get(reason, '')
        self.preview = not reason
        self.preview_run = self.target.follow_up_identity() if self.preview else None
        self.changed.emit()

    @Slot()
    def confirm(self):
        if not self.opened or not self.preview or not self.target or self.attempted:
            return
        run = self.preview_run
        result = self.target.submit_follow_up(self.body, run) if run else self.target.submit(self.body)
        self.preview_run = None
        if result['ok'] and result['status'] == 'pending':
            self.follow_up_pending = (self.target.record, run, result['messageId'], self.body)
            self.preview = False
            self.attempted = True
            self.notice = '正在核对后续消息是否进入队列；暂时保留草稿。'
            self.changed.emit()
            return
        self.preview = False
        self.attempted = self.target.consumed
        if result['ok']:
            self.body = ''
            self.drafts[self.draft_key] = ''
            self.notice = '已提交到所选会话，不代表完成。回复、审批与停止请在该会话处理。'
        else:
            self.notice = REASONS.get(result['status'], '未提交；草稿已保留。')
        self.changed.emit()

    def observe(self, record, event):
        pending = self.follow_up_pending
        if not pending or record is not pending[0]:
            return
        _, run, message_id, body = pending
        kind = event.get('type')
        if kind == 'pet_follow_up_receipt':
            if event.get('runId') != run[1] or event.get('messageId') != message_id:
                return
            queued = (event.get('status') == 'queued' and record.process is run[0]
                      and self.target._unavailable(allow_follow_up=True) == 'already_submitted'
                      and record.pet_follow_up_run == run[1])
        elif kind in ('done', 'exit'):
            queued = False
        else:
            return
        self.follow_up_pending = None
        if queued and self.body == body:
            self.body = self.drafts[self.draft_key] = ''
            self.notice = '后续消息已进入所选会话队列，不代表开始或完成。'
        else:
            self.notice = REASONS['uncertain']
        self.changed.emit()

    @Slot(result=bool)
    def openDesktop(self):
        target = self.target
        if (not target or self.bus.m.closed or not self.bus.active
                or not self.bus.m.enabled('global-agents')
                or self.bus.agents.get(target.identifier) is not target.row
                or self.bus.records.get(target.identifier) is not target.record):
            self.notice = '原目标已不可用；不会打开替代会话。'
            self.changed.emit()
            return False
        manager = self.pet.manager
        if not manager.openPage('global-agents'):
            self.notice = '无法打开全局智能体页面；草稿已保留。'
            self.changed.emit()
            return False
        manager._agent_navigation = {'id': target.identifier,
                                     'serial': manager._agent_navigation.get('serial', 0) + 1}
        manager.pageChanged.emit()
        self.pet.restoreRequested.emit()
        return True

    @Slot()
    def close(self):
        self.opened = False
        self.preview = False
        self.changed.emit()
