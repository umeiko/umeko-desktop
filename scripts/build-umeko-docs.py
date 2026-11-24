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
    lines.extend(['', '等待空闲范围 `target` 表示指定的 `sessionId`，省略时使用调用会话。',
                  '', 'Python 插件会话可用 `pluginSessions.setModel` 同时设置模型路由和思考强度，也可只更新思考强度：',
                  '', '```json',
                  '{"operation":"pluginSessions.setModel","arguments":{"plugin":"session-task-service","profile":"tasks","reasoningEffort":"medium"}}',
                  '```', '', operations['pluginSessions.setModel']['description'],
                  '', '`inherit` 是清除档位的操作值，保存后配置中移除 `reasoningEffort` 字段。其他值可填写 `off`、`none`、`minimal`、`low`、`medium`、`high`、`xhigh`、`max`、`ultra` 或模型直接支持的自定义档位。省略模型时保留模型，新模型省略供应商时使用实际路由。',
                  '', '```json',
                  '{"operation":"pluginSessions.setModel","arguments":{"plugin":"session-task-service","profile":"tasks","reasoningEffort":"inherit"}}',
                  '```',
                  '', '插件会话优先使用 `pluginSessionProfiles.<plugin>.<profile>.reasoningEffort`，未配置时继承 `ui.reasoningEffort`，两者均未配置时使用 `off`。宿主在新会话或下一次输入时按模型支持的档位对齐，保存的配置值继续保留。详见 [Widget 插件](widget-plugins.md)。',
                  '', '`agent.defaultReasoning` 设置新桌面会话的默认档位；`sessions.reasoning` 设置当前或指定会话的档位。`agent.save` 的 `config` 支持 `autoCompaction`、`maxContextImages` 等局部设置。全局工具权限沿用用户界面确认。完整设置、参数范围与生效时机见 [设置说明](settings.md)。',
                  '', 'Widget 只读查询：`widgets.list`、`widgets.docs`、`widgets.messages`、`widgets.result`、`widgets.resource`。',
                  '', '`plugins.*` 管理 Provider 插件；`widgets.*` 管理桌面 Widget。`help` 的 `arguments.topic` 可为 `plugins`、`provider`、`widget`、`agents` 或 `command_rules`。'])
    return '\n'.join(lines) + '\n'


if __name__ == '__main__':
    (ROOT/'runtime/umeko-docs/operations.md').write_text(generate(), encoding='utf-8')
