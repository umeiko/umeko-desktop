# 显式任务入口与路由（#43）

基于已合并 #40 / PR #93 的共享任务记录，复用「全局子智能体」Widget、Pi 和原 Agent Bus。只接收用户在 Widget 的明确提交，不监听聊天、GitHub 或其他外部事件。执行队列、结构化执行尝试与人工事项仍由 #44 承担。

## 操作与关联规则

用户选择已有协调者、已连接会话的实际目录，填写目标与允许处理的范围。关联可选自动判断、新建或续接最近的已有 taskId。协调者通过 `agent_bus.route` 返回 new / continue / clarify / reject，不能改写用户目标、范围和目录。

自动续接需要目录与范围一致；含糊时返回澄清，由用户明确选择任务关联。范围不同时，需要用户选择该任务并提交新范围，宿主先停止旧路由再修改范围，其他任务保留。若有该任务的聊天工作正在执行，则先结束它，防止聊天与路由重复处理。

协调者首次用于入口后进入持久的任务协调模式：宿主阻止普通 `agent_bus.dispatch` 以及自行修改连接；它只能处理交给自己的入口请求。连接仍由用户在总线页面管理。退出任务模式会先停止该协调者及未完成路由。Pi 协调者仍只有桌面 API 小工具集；执行会话保留原工具、终端、Skills、权限及审批。

## 持久身份与故障语义

共享 `tasks.sqlite3` 从版本 1/2 迁移到 3，保留 #93 的步骤、文件及时间线时间字段。新增路由表，没有第二套任务数据库。taskId 与 accepted 路由原子保存，之后交给现有总线，没有另建调度器。

requestKey 唯一标识提交，同身份同内容返回原结果，不再请求模型、不重复创建任务或派发；同身份不同内容会被拒绝。入口保留当前身份直到内容改变或用户点击「新请求」。选中的协调者、目录、taskId 在列表刷新后保留。路由身份不会随 Bus 内存历史淘汰，也不会随用户删除任务而遗忘。

routeId 同时作为 Bus requestId。模型和执行者的真实会话身份由宿主绑定，不能用参数冒充。执行回报通过现有 `agent_bus.reply` 关联至唯一 taskId。通知增加 taskId、scope、cwd，仍为带来源的应用数据，不能提升为额外用户授权。

SQLite 与 Bus 状态文件无法跨文件原子提交：若在路由保存后、投递之前崩溃，会留下中断记录；重启和超时都不自动重发。用户检查执行会话后可明确提交新请求。不承诺外部工具副作用的 exactly-once。

协调模式或 Bus 请求未能保存时不启动/投递。任务库写入失败时也停止该派发；用户停止若无法保存，仍在当前进程留下拦截屏障，重启时由恢复逻辑中断未完成项。已执行的操作无法撤销，也不为停止单条请求而中止共用会话中的无关任务。

## 状态与边界

路由状态为 routing / clarify / rejected / cancelled / interrupted / accepted。accepted 只表示已选择任务并交给总线。

执行另记 not_started / queued / sending / running / completed / failed / cancelled / interrupted；failurePhase 区分投递和执行。running 代表已接收或报告进度，completed 代表执行者回报，不代表用户验收。普通 assistant 文本不算回执。

派发与投递前检查既有普通会话、用户开启的连接、模型、会话历史及存在的绝对目录。不会创建替代会话或选择其他目录。记录会话真实 workspace，兼容 #32 的独立 worktree。目录、范围、停止状态变化后，旧请求不会投递。

入口按 20 条分页，任务候选最多 100 条。共享任务记录的路由回报默认折叠，按 4 条分页；内部引用只在用户展开记录信息后显示。保留 #93 的卡片、工作时间线、交付预览和手动确认流程。#43 不生成文件交付或原生聊天工作记录，结构化执行尝试与用户处理事项由 #44 继续实现。

## 验证

```sh
python -m unittest tests.test_task_routing tests.test_task_records tests.test_global_agents tests.test_widget_host tests.test_desktop_plugins
node --test tests/global-agents.test.mjs tests/umeko-control.test.mjs tests/task-timeline.test.mjs
python prepare_runtime.py
python tests/task_routing_ui_smoke.py
python tests/task_records_ui_smoke.py
python tests/global_agents_ui_smoke.py
```

界面测试使用隔离配置、真实 Qt 与原生 Pi 进程，模型响应由确定性的本地夹具提供，不消耗外部模型额度，不等同于真实模型路由质量评估。新增测试覆盖明确任务入口、实际写入的原权限审批、去重、同 taskId 续接、刷新后重试、澄清及共享回报。可用 UMEKO_TEST_CJK_FONT 指定中文字体，UMEKO_ACCEPTANCE_PREVIEW=1 保留本地验收窗口。

入口仅选择已有 Pi 执行会话。当前 main 的 DSH 会话不具备本入口所需的 Agent Bus/Pi 工具协议，因此在选择、路由决定及投递前明确拒绝，不创建 Pi 替代会话。
