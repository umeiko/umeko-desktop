# 命令规则

Pi 会话可以用命令前缀规则控制 Bash、PowerShell 和后台命令的启动。用户规则放在 Umeko 用户数据目录的 `command-rules.json`。工作区规则放在工作区根目录的 `.umeko/command-rules.json`。保存后，下一次命令调用就会读取当前规则。

每个文件是一个 JSON 数组。`pattern` 按顺序填写命令名和参数，支持命令后面跟更多参数。`decision` 可为 `allow`、`ask` 或 `forbid`。可以用 `shell` 指定 `bash` 或 `powershell`，省略时两者都适用。PowerShell 的命令名忽略大小写，其余参数按原字面匹配。

```json
[
  {"pattern": ["git", "status"], "decision": "allow"},
  {"pattern": ["git", "push"], "decision": "ask"},
  {"pattern": ["Set-Content", "protected.txt"], "decision": "forbid", "shell": "powershell"}
]
```

Umeko 先应用内置危险操作规则。普通命令按每一段匹配用户和工作区规则，`forbid` 优先于 `ask`，`ask` 优先于 `allow`。复合命令的任意一段命中禁止规则时，整条命令都不会开始执行。未命中规则的部分沿用当前的自动或询问模式。安全模式下，工作区规则可增加限制，工作区的允许规则需要信任该工作区才生效。

询问模式中，可识别的简单命令会显示「以后都允许这类命令」。例如，批准 `git status --short` 时可以保存 `git status`，以后 `git status -s` 也适用。`Get-ChildItem` 只保存命令名。文件名、路径和其他参数值不会加入前缀。模型可提供 `prefix_rule`，Umeko 会按实际命令核对，并在提议缺失或无效时自行派生。选择该选项会写入用户规则并运行本次命令。

解释器、脚本入口、无法识别的命令、复合命令、含变量替换等复杂语法的命令，以及已有询问规则要求确认的命令，使用单次审批。

可以直接调用以下 `umeko_desktop` 操作。`scope` 为 `user` 或 `workspace`，`list` 省略 `scope` 时返回两级规则。

- `command_rules.list` 查看规则。
- `command_rules.add` 添加规则，参数为 `scope`、`pattern`、`decision` 和可选的 `shell`。
- `command_rules.remove` 删除规则，传入列表中该条规则的相同字段。

通过 Agent 添加允许规则或删除询问、禁止规则时，Umeko 会请用户确认。
