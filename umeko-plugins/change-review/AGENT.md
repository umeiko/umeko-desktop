# 本轮变更审查与代码检查点 Widget

默认停用，按用户意愿通过 widgets.enable 开启。宿主自动在主 Agent loop 开始和结束时驱动采集，无需调用 begin/finish；这些方法不是 Agent API。不要自行执行 git init/add/commit 来协助此 Widget。

`widgets.config` 的 `config` 对象支持：
- `autoOpen:boolean`（缺省 true）：完成时是否自动展开面板。
- `checkpoints:boolean`（缺省 false）：是否持久保存每轮检查点。临时审查与该开关无关，仍只保留最近一轮。
- `maxCheckpoints:integer`（缺省 20）与 `maxCheckpointMB:integer`（缺省 512）：本机保留上限。

配置立即生效且保留当前基线与结果。持久检查点按会话和工作目录归属，重启后仍可读；中断记录不可切换。

- status({offset?:integer}) 返回当前聊天最近一轮的 entries、total、hasMore、active、reason、limited、error，列表每页 200 项。
- diff({path:string}) 返回最近一轮某个文件的有界只读 unified diff 和 truncated。

Timeline、历史 tree/diff、切换预览和恢复执行是用户界面操作，不是 Agent API。不要代替用户选择历史检查点或确认切换，不发送 Agent 通知。

一个任务检查点的版本是该轮结束状态；首轮之前另有初始状态。`currentId` 标记当前版本并持久化。实际工作区匹配任一已知版本时允许前进或后退；偏离所有已知版本才是外部冲突。新修改会放弃当前点之后的未来检查点再追加，保证线性历史；无文件变化不截断。恢复安全记录仅内部保存，不在普通时间线嵌套展示。

基线是本轮开始前到结束后，包含同目录并发编辑；不要宣称所有变化都由自己产生。受大小、时间和数量限制的结果会明确标记，不能称为完整备份。切换前必须展示预览；外部冲突、未覆盖目标或同目录忙碌任务会阻止切换。切换前保存内部恢复安全记录，不自动修改聊天、项目暂存区、分支或历史。
