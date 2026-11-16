"""Bounded catalog/import jobs for independently configured global agents."""
import json
import os
from pathlib import Path
import subprocess
from .skill_import import import_local


def execute(request):
    context = request['context']
    def node(**action):
        env = dict(os.environ, PI_OFFLINE='1')
        env.pop('NODE_OPTIONS', None)
        env.pop('NODE_PATH', None)
        result = subprocess.run([context['node'], str(Path(context['release']) / 'coordinator-skills.mjs')],
            input=json.dumps({**context, **action}), capture_output=True, text=True, encoding='utf-8',
            timeout=45, env=env, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        payload = json.loads(result.stdout)
        if result.returncode or not payload.get('ok'):
            raise ValueError(payload.get('error', 'Skill catalog failed'))
        return payload
    catalog = node()
    if request['operation'] == 'importSkills':
        destination = Path(context['coordinatorSkillRoots']['imported'])
        rows = [row for row in catalog['skills'] if row['source'] == 'imported']
        result = import_local(request['source'], destination, rows,
            lambda documents: node(action='validateText', documents=documents)['documents'], plan_store={})
        if result['errors']:
            raise ValueError('\n'.join(row['name'] + ': ' + row['error'] for row in result['errors'][:8]))
        if not result['imported']:
            raise ValueError('没有导入新 Skill；同名的已有 Skill 不会被覆盖')
        catalog = node()
        catalog['imported'] = result['imported']
    return catalog


