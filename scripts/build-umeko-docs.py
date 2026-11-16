"""Generate the on-demand operation reference from the shared desktop allowlist."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def generate():
    operations = json.loads((ROOT/'runtime/umeko-operations.json').read_text(encoding='utf-8'))['operations']
    lines = ['# 操作与参数参考', '', '本页由 `umeko-operations.json` 生成。语义、示例和状态处理见相应分类文档。', '',
             '动态查询可用 `operations.list`，按 prefix 筛选。参数传在 arguments 中，JSON 类型直接传对象/数组。', '',
             '只读及组合操作：`help`、`operations.list`、`batch`、`settings.get`、`providers.list`、`models.list`、`characters.list`、`characters.get`、`characters.config`、`plugins.list`、`plugins.getConfig`、`themes.list`、`themes.prompt`、`projects.list`、`sessions.list`、`sessions.get`、`mcp.get`、`status.get`、`jobs.get`。', '',
             '会话专用：`models.select(provider, model, sessionId?)`、`sessions.reasoning(value, sessionId?)`。缺省关联调用会话。', '',
             '| operation | arguments（类型；=默认值） | 等待空闲范围 | 启动后台工作 |',
             '| --- | --- | --- | --- |']
    for name, spec in operations.items():
        args = []
        for field in spec['args']:
            default = '=' + json.dumps(field[2], ensure_ascii=False) if len(field) > 2 else ''
            args.append(f'`{field[0]}: {field[1]}{default}`')
        label = f'`{name}`' + ('（仅 ' + ', '.join(spec['editions']) + '）' if spec.get('editions') else '')
        lines.append('| ' + ' | '.join((label, ', '.join(args) or '无', spec.get('idle', '无'), '是' if spec.get('async') else '否')) + ' |')
    lines.extend(['', 'Widget 只读查询：`widgets.list`、`widgets.docs`、`widgets.messages`、`widgets.result`、`widgets.resource`。',
                  '', '`pluginSessions.setModel` 修改已有插件会话配置的模型路由和思考档位。`reasoningEffort` 为空字符串或省略时不修改档位；通用值为 `off`、`none`、`minimal`、`low`、`medium`、`high`、`xhigh`、`max`、`ultra`。`model` 和 `provider` 均留空时可只修改档位：',
                  '', '```json',
                  '{"operation":"pluginSessions.setModel","arguments":{"plugin":"example-service","profile":"tasks","reasoningEffort":"high"}}',
                  '```',
                  '', '配置中的 `pluginSessionProfiles.<plugin>.<profile>.reasoningEffort` 优先于 `ui.reasoningEffort`；未配置时继承后者，两者均未配置时使用 `off`。实际使用时按所选模型支持的档位对齐，详见 [插件独立会话](widget-plugins.md#应用服务管理独立会话)。',
                  '', '`plugins.*` 管理 Provider 插件；`widgets.*` 管理桌面 Widget。`help` 的 `arguments.topic` 可为 `plugins`、`provider`、`widget` 或 `agents`。'])
    return '\n'.join(lines) + '\n'


if __name__ == '__main__':
    (ROOT/'runtime/umeko-docs/operations.md').write_text(generate(), encoding='utf-8')
