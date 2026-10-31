# 本轮变更审查 Widget

默认停用，按用户意愿通过 widgets.enable 开启。宿主自动在主 Agent loop 开始和结束时驱动采集，无需调用 begin/finish；这些方法不是 Agent API。不要自行执行 git init/add/commit 来协助此 Widget。

`widgets.config` 的 `config` 对象支持 `autoOpen:boolean`（缺省 true）。它控制完成时是否自动展开面板；false 时仍采集结果，用户可手动打开。配置立即生效且保留当前基线与结果。

- status({offset?:integer}) 返回当前聊天拥有的最近一轮的 entries、total、hasMore、active、reason、limited、error，列表每页 200 项。
- diff({path:string}) 返回该文件的有界只读 unified diff 和 truncated。

基线是本轮开始前到结束后，包含同目录并发编辑；不要宣称所有变化都由自己产生。开启前的任务没有基线。受大小、时间和数量限制的结果会明确标记。全应用只保留最近一轮的临时结果，下一轮开始即替换；退出应用清空，不保存历史。用户关闭面板仍采集；停用插件后不采集。不发送通知给 Agent，不自动修改项目文件、暂存区或历史，不提供回滚。
