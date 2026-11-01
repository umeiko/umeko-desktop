"""User-invoked composer actions; discovery runs off the GUI thread."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from PySide6.QtCore import QObject, Property, Signal, Slot, QUrl
from pypinyin import lazy_pinyin

from .skill_management import skill_command


class SlashCommands(QObject):
    changed = Signal()

    def __init__(self, backend):
        super().__init__(backend)
        self.b, self._skills, self._context, self._pending = backend, [], None, None
        backend.viewChanged.connect(self.invalidate)
        backend.desktopPlugins.changed.connect(self.invalidate)
        backend.jobDone.connect(self.finished)

    def key(self):
        r = self.b._view
        return (r.key, r.workspace, str(self.b._release), repr(self.b.store.data['agent']),
                self.b.desktopPlugins.skills_enabled(r), repr(r.skill_modes))

    @Slot()
    def invalidate(self):
        self._context = None
        self._skills = []
        self.changed.emit()

    @Property('QVariantList', notify=changed)
    def entries(self):
        english = self.b.language == 'en'
        rows = [dict(id='compact', group='命令', title='/compact', command='/compact', icon='archive',
                     description='Compact conversation context' if english else '压缩当前会话的上下文'),
                dict(id='reload', group='命令', title='/reload', command='/reload', icon='refresh',
                     description='Reload Pi resources' if english else '重新加载 Pi 资源')]
        for row in self.b.desktopPlugins.sessionPlugins:
            rows.append(dict(id='widget:'+row['id'], widgetId=row['id'], group='Widgets', title=row['name'], icon=row['iconGlyph'],
                             iconSource=row.get('iconSource', ''), description=row.get('summary', ''), scope='Widget'))
        if self._context == self.key() and self.b.desktopPlugins.skills_enabled(self.b._view):
            rows.extend(self._skills)
        return [{**row, 'titlePinyin': lazy_pinyin(row['title'])} for row in rows]

    @Slot()
    def refresh(self):
        if self.b._closing:
            return
        key = self.key()
        if self._pending or not key[4]:
            return
        release, cwd, agent_dir, agent = self.b.piManagement._context()
        r = self.b._view
        options = dict(sessionSkills=copy.deepcopy(r.skill_modes),
                       loadedSkills=copy.deepcopy(list(r.known_skills.values())))
        self._pending = key
        self.b._job('slash-skills', lambda: skill_command(release, cwd, agent_dir, agent, action='list', **options))

    def finished(self, name, result):
        if name != 'slash-skills':
            return
        key, self._pending = self._pending, None
        if self.b._closing:
            return
        if key != self.key():
            self.refresh()
            return
        self._context = key
        self._skills = []
        if result.get('ok'):
            for row in result.get('value', {}).get('skills', []):
                if row.get('attached'):
                    path = Path(row['path'])
                    title = path.parent.name if path.name == 'SKILL.md' else row['name']
                    self._skills.append(dict(id=row['id'], group='技能', title=title, icon='skill',
                        description=row['description'], path=row['path'],
                        scope=('项目' if row['scope'] == 'project' else '全局') if self.b.language != 'en'
                        else ('Project' if row['scope'] == 'project' else 'Global')))
        else:
            self.b.toast.emit('无法读取技能列表 / Could not read Skills: ' + str(result.get('value', ''))[:200])
        self.changed.emit()

    @Slot(str, result=bool)
    def choose(self, identifier):
        row = next((r for r in self.entries if r['id'] == identifier), None)
        if not row:
            return False
        if row['group'] == 'Widgets':
            return self.b.desktopPlugins.openPage(row['widgetId'])
        if row['group'] == '技能':
            path = Path(row['path'])
            if path.is_file():
                target = path.parent if path.name == 'SKILL.md' else path
                return self.b.addAttachments(json.dumps([QUrl.fromLocalFile(str(target)).toString()]))
        return False

    @Slot(str, result=bool)
    def execute(self, text):
        if self.b.busy or self.b.kernelBusy:
            self.b.toast.emit('请等待当前操作结束 / Wait for the current operation')
            return False
        if text.strip() == '/compact':
            return self.b._request_compaction()
        if text.strip() == '/reload':
            self.invalidate()
            return self.b._command_pi('reload')
        self.b.toast.emit('请选择命令、Widget 或技能 / Choose a command, Widget or Skill')
        return False
