"""Team roster, direct mentions, and task transitions for the Agent Bus."""

# Adapted from @tintinweb/pi-subagents 0.26.3, src/mention.ts and src/index.ts.
# MIT notice: licenses/tintinweb-pi-subagents-MIT.txt.
# Task transitions and graph checks adapted from @deepseek-ai/dsh-agent-team
# 0.2.2-rc.5, packages/team/agent-team/src/{task-board,task-graph}.ts.
# MIT notice: licenses/dsh-agent-team-and-subagent-control-MIT.txt.
import re
import sqlite3

HANDLE = re.compile(r'[a-z0-9_-]{1,64}', re.ASCII)
MENTION = re.compile(r'(?:^|[\s,，。、？！(（])@([a-z0-9_-]{1,64})(?=$|[\s,!?;:，。、？！；：)）]|\.(?=\s|$))', re.IGNORECASE | re.ASCII)
DIRECT = re.compile(r'^@([a-z0-9_-]{1,64})\s+\S', re.IGNORECASE | re.ASCII)
RESERVED = {'all', 'main'}


def handle(value):
    if not isinstance(value, str) or not HANDLE.fullmatch(value.lower()) or value.lower() in RESERVED:
        raise ValueError('团队名称须为 1–64 个 ASCII 字母、数字、下划线或连字符，且不能用 all 或 main')
    return value.lower()


def roster(coordinator_id, coordinator_name, members):
    if not isinstance(members, list) or not 1 <= len(members) <= 15:
        raise ValueError('请选择 1–15 位团队成员')
    lead = {'targetId': coordinator_id, 'name': handle(coordinator_name), 'role': 'coordinator', 'groups': []}
    rows = [lead]
    for member in members:
        if not isinstance(member, dict) or set(member) - {'targetId', 'name', 'groups'}:
            raise ValueError('成员只支持 targetId、name 和 groups')
        target = member.get('targetId')
        groups = member.get('groups', [])
        if not isinstance(target, str) or not isinstance(groups, list) or len(groups) > 16:
            raise ValueError('成员地址或群组无效')
        rows.append({'targetId': target, 'name': handle(member.get('name')), 'role': 'member',
                     'groups': list(dict.fromkeys(handle(group) for group in groups))})
    names = {row['name'] for row in rows}
    if len(names) != len(rows) or len({row['targetId'] for row in rows}) != len(rows):
        raise ValueError('团队成员地址和名称必须唯一')
    if names.intersection(group for row in rows for group in row['groups']):
        raise ValueError('群组与成员不能使用同一名称')
    return rows


def recipients(text, members, sender, *, leading=False):
    direct_match = DIRECT.match(text) if leading else None
    if leading and not direct_match:
        return []
    addresses = {'all': members}
    for member in members:
        addresses[member['name']] = [member]
        for group in member['groups']:
            addresses.setdefault(group, []).append(member)
    if leading:
        direct = direct_match[1].lower()
        if direct not in addresses and (not direct.startswith('agent-') or direct[6:] not in addresses):
            return []
    targets = {}
    for match in MENTION.finditer(text):
        name = match[1].lower()
        selected = addresses.get(name)
        if selected is None and name.startswith('agent-'):
            selected = addresses.get(name[6:])
        for member in selected or []:
            if member['targetId'] != sender:
                targets[member['targetId']] = member
    return list(targets.values())


def task_ready(task, tasks):
    return all(tasks[blocker]['status'] == 'completed' for blocker in task['blockedBy'])


def validate_task_graph(tasks, candidate):
    tasks = tasks | {candidate['id']: candidate}
    visiting, visited = set(), set()

    def visit(identifier):
        if identifier in visiting:
            raise ValueError(f'任务依赖成环：{identifier}')
        if identifier in visited:
            return
        visiting.add(identifier)
        blockers = tasks[identifier]['blockedBy']
        if len(blockers) != len(set(blockers)):
            raise ValueError(f'任务依赖重复：{identifier}')
        for blocker in blockers:
            if blocker not in tasks:
                raise ValueError(f'任务依赖不存在：{blocker}')
            visit(blocker)
        visiting.remove(identifier)
        visited.add(identifier)

    for identifier in tasks:
        visit(identifier)


def next_task(tasks, kind, fields, actor, members):
    if kind == 'task':
        task = {'id': fields['taskId'], 'version': 1, 'status': 'pending', 'owner': None,
                'title': fields['title'], 'description': fields['text'], 'blockedBy': fields['blockedBy']}
        validate_task_graph(tasks, task)
        return task

    current = tasks.get(fields['taskId'])
    if not current:
        raise ValueError('团队任务不存在')
    if fields['expectedVersion'] != current['version']:
        raise ValueError(f"团队任务版本已变化，当前版本为 {current['version']}")
    task = {**current, 'version': current['version'] + 1}

    if kind == 'claim':
        if current['status'] != 'pending' or not task_ready(current, tasks):
            raise ValueError('只能认领依赖已完成的待认领任务')
        task.update(status='in_progress', owner=actor['name'])
        return task

    if actor['role'] != 'coordinator' and current['owner'] != actor['name']:
        raise ValueError('只有任务负责人和协调者可以更新任务')
    if kind == 'dependencies':
        if current['status'] != 'pending':
            raise ValueError('只能修改待认领任务的依赖')
        task['blockedBy'] = fields['blockedBy']
        validate_task_graph(tasks, task)
        return task
    if current['status'] != 'in_progress':
        raise ValueError('只能更新进行中的团队任务')
    if kind == 'handoff':
        target = fields['to']
        if target == current['owner'] or not any(member['name'] == target for member in members):
            raise ValueError('请选择另一位团队成员接手任务')
        task['owner'] = target
    if kind == 'result':
        task.update(status='completed', result=fields['text'])
    return task


EVENT_FIELDS = {
    'message': {'text'},
    'task': {'title', 'text', 'blockedBy'},
    'claim': {'taskId', 'expectedVersion'},
    'dependencies': {'taskId', 'expectedVersion', 'blockedBy'},
    'progress': {'taskId', 'expectedVersion', 'text'},
    'handoff': {'taskId', 'expectedVersion', 'text', 'to'},
    'result': {'taskId', 'expectedVersion', 'text'},
}
OPERATION_FIELDS = {
    'team_create': {'name', 'coordinatorName', 'members'},
    'team_members': {'teamId'},
    'team_board': {'teamId', 'after', 'limit'},
    'team_post': {'teamId', 'event'},
}


class TeamBoard:
    def __init__(self, bus):
        self.bus = bus

    @property
    def enabled(self):
        return self.bus.b.store.data.get('desktop', {}).get('teamCollaborationEnabled') is True

    def storage(self):
        store = self.bus.b._task_records._storage()
        if store is None:
            raise ValueError('无法打开团队任务记录')
        return store

    def member_status(self, member):
        identifier = member['targetId'].removeprefix('agent:')
        agent = self.bus.agents.get(identifier)
        record = self.bus.records.get(identifier)
        if not agent:
            return 'unavailable'
        if record and record.busy:
            return 'running'
        # Adapted from @deepseek-ai/dsh-tool-subagent-control 0.2.2-rc.5,
        # packages/subagent/tool-subagent-control/src/wait-agent.ts. Waiting is
        # owned by this recipient's inbox. An idle session needs no waiting turn,
        # timer or model tool. Only directed delivery starts its next team turn.
        return 'waiting' if (record and record.id) or agent.get('sessionId') else 'not_started'

    def for_identity(self, store, identity):
        return [(team, member) for team in store.teams() for member in team['members']
                if member['targetId'] == identity]

    def execute(self, method, args, identity=None):
        if not self.enabled:
            raise ValueError('请先在 Umeko Desktop 设置中开启团队协作')
        # With no bound agent identity, callers are the built-in Widget host.
        fields = OPERATION_FIELDS.get(method)
        if fields is None or set(args) - (fields if identity else fields | {'coordinatorId', 'actorId'}):
            raise ValueError('未知团队操作或参数')
        try:
            return self._execute(self.storage(), method, args, identity)
        except (sqlite3.Error, OSError) as error:
            raise ValueError('无法读写团队任务记录') from error

    def _execute(self, store, method, args, identity):
        if method == 'team_create':
            name = self.bus.text(args, 'name', 100)
            lead = identity or self.bus.text(args, 'coordinatorId', 80)
            members = roster(lead, args.get('coordinatorName', 'lead'), args.get('members'))
            for member in members:
                target = member['targetId']
                if not target.startswith('agent:') or target[6:] not in self.bus.agents:
                    raise ValueError('请选择现有全局子智能体加入团队')
            return store.create_team(name, members)

        team_id = self.bus.text(args, 'teamId', 40, method != 'team_members')
        if method == 'team_members' and not team_id:
            teams = [team for team, _ in self.for_identity(store, identity)] if identity else store.teams()
            return {'teams': [{key: team[key] for key in ('id', 'name', 'created')} for team in teams]}
        team = store.team(team_id)
        actor_id = identity or args.get('actorId')
        actor = next((member for member in team['members'] if member['targetId'] == actor_id), None) if team else None
        if team is None or ((identity or method == 'team_post') and actor is None):
            raise ValueError('团队不存在，或当前身份未加入团队')
        if method == 'team_members':
            return {**team, 'members': [{**member, 'status': self.member_status(member)} for member in team['members']]}
        if method == 'team_board':
            after, limit = args.get('after', 0), args.get('limit', 20)
            if type(after) is not int or not 0 <= after < 2**63 or type(limit) is not int or not 1 <= limit <= 50:
                raise ValueError('after 须为非负整数，limit 须为 1–50')
            return store.team_board(team_id, after, limit)
        return self.post(store, team, actor, args.get('event'))

    def post(self, store, team, actor, event):
        kind = event.get('kind') if isinstance(event, dict) else None
        if not isinstance(kind, str) or kind not in EVENT_FIELDS or set(event) - EVENT_FIELDS[kind] - {'kind'}:
            raise ValueError('未知团队看板事件或字段')
        fields = EVENT_FIELDS[kind]
        text = self.bus.text(event, 'text', 8000, 'text' in fields)
        values = {'text': text}
        if 'expectedVersion' in fields:
            version = event.get('expectedVersion')
            if type(version) is not int or version < 1:
                raise ValueError('expectedVersion 须为正整数')
            values.update(expectedVersion=version, taskId=self.bus.text(event, 'taskId', 40))
        if 'title' in fields:
            values['title'] = self.bus.text(event, 'title', 200)
        if 'blockedBy' in fields:
            blockers = event.get('blockedBy', [] if kind == 'task' else None)
            if not isinstance(blockers, list) or len(blockers) > 128 or any(not isinstance(v, str) or len(v) > 40 for v in blockers):
                raise ValueError('blockedBy 须为任务 ID 数组')
            values['blockedBy'] = blockers
        if 'to' in fields:
            values['to'] = handle(event.get('to'))

        targets = recipients(text, team['members'], actor['targetId'])
        available = [member for member in targets if member['targetId'][6:] in self.bus.agents]
        if available and len(self.bus.outbox) + len(available) > 256:
            raise ValueError('智能体总线投递队列已满')
        row = store.post_team_event(team, actor, kind, values, [member['name'] for member in targets])
        deliveries = []
        for member in targets:
            if member in available:
                self.bus.enqueue_team_message(team['id'], actor, member, row)
            deliveries.append({'name': member['name'], 'status': 'queued' if member in available else 'unavailable'})
        self.bus.changed(persist=False)
        return {'event': row, 'deliveries': deliveries}

    def direct(self, identity, text):
        if not self.enabled or not DIRECT.match(text):
            return None
        try:
            store = self.storage()
            matches = [(team, member) for team, member in self.for_identity(store, identity)
                       if recipients(text, team['members'], identity, leading=True)]
            if len(matches) > 1:
                raise ValueError('多个团队匹配此点名，请在指定团队的看板中发送')
            if matches:
                team, actor = matches[0]
                return self.post(store, team, actor, {'kind': 'message', 'text': text})
            return None
        except (sqlite3.Error, OSError) as error:
            raise ValueError('无法读写团队任务记录') from error
