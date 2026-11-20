"""Target-bound discovery for existing pet entries; never executes commands.

Only existing project, timer and local reminder paths are advertised.
This is not the main composer's view-bound command/Widget/Skill dispatcher.
"""
import copy
import secrets

from PySide6.QtCore import QObject, Slot
from pypinyin import lazy_pinyin


class PetCommands(QObject):
    def __init__(self, pet):
        super().__init__(pet)
        self.pet = pet
        self._ticket = ''
        self._target = None

    def _identity(self):
        status = self.pet.assistantStatus
        if not status.get('bound'):
            raise ValueError('桌宠助手不可用，请重新选择目标')
        project = self.pet.projectEntry
        if project.selected:
            if not project.valid():
                raise ValueError('项目目标已失效，请重新选择；草稿保留')
            return (status['id'], 'project', copy.deepcopy(project.captured), project.project_identity)
        return (status['id'], 'assistant')

    def _entries(self):
        manager = self.pet.manager
        timer = manager.entries.get('scheduled-tasks', {})
        timer_enabled = (timer.get('builtin') and manager.enabled('scheduled-tasks')
                         and 'create' in timer.get('agent', {}).get('methods', {}))
        rows = [dict(id='project', title='/项目', command='/项目',
                     semantics='select-target', enabled=True, reason=''),
                dict(id='timer', title='/定时任务', command='/定时任务',
                     semantics='prepare-operation', enabled=bool(timer_enabled),
                     reason='' if timer_enabled else '请先启用内置定时任务 Widget'),
                dict(id='reminder', title='/提醒', command='/提醒',
                     semantics='prepare-operation', enabled=True, reason='')]
        return [{**row, 'titlePinyin': lazy_pinyin(row['title'])} for row in rows]

    @Slot(str, result='QVariantMap')
    def query(self, binding):
        # Every new query retires previous candidates, including failed queries.
        self._ticket, self._target = '', None
        try:
            target = self._identity()
            if target[0] != binding:
                raise ValueError('桌宠绑定已变化，请重新打开菜单')
        except ValueError as error:
            return {'ok': False, 'error': str(error), 'entries': []}
        self._target = target
        self._ticket = secrets.token_hex(16)
        return {'ok': True, 'ticket': self._ticket, 'entries': self._entries(),
                'target': {'kind': target[1], 'id': target[2]['id'] if len(target) > 2 else target[0]}}

    @Slot(str, str, result='QVariantMap')
    def choose(self, ticket, identifier):
        # Selection only returns an explicit preparation command. Existing
        # entry handlers must still revalidate when the user actually submits.
        if not ticket or ticket != self._ticket:
            return {'ok': False, 'error': '菜单已过期，请重新打开；草稿保留'}
        self._ticket = ''
        try:
            if self._identity() != self._target:
                raise ValueError('目标已变化，请重新打开菜单；草稿保留')
            row = next((row for row in self._entries() if row['id'] == identifier), None)
            if row is None:
                raise ValueError('未知入口，不会执行或自动发送正文')
            if not row['enabled']:
                raise ValueError(row['reason'])
            return {'ok': True, 'command': row['command'], 'semantics': row['semantics']}
        except ValueError as error:
            return {'ok': False, 'error': str(error)}
