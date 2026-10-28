# 子代理侧栏

子代理的执行仍由固定版本的 `@gotgenes/pi-subagents` 社区包负责；桌面适配层只投影原生事件和会话文件，不修改社区包源码。

- 一个主会话最多同时运行 4 个子代理，前台和后台任务共用额度。四个位置分别使用烧盐柠檬、小鞠知花、温水佳树、志喜屋梦子的头像，任务完成后位置可以复用。
- 主聊天中保留紧凑的任务卡片。点击卡片在右侧查看该子代理的消息、思考过程和工具调用；侧栏复用产物面板的 PID 动画和宽度拖动。
- 有活动任务时，右上角显示头像与数量。下拉列表只列出当前主会话的活动子代理。
- 侧栏发送框只给选中的子代理发送指引；停止按钮只中断该子代理。关闭侧栏不停止任务，进入设置或切换主会话会关闭当前侧栏。
- 已结束的历史子代理可以从原生会话文件继续，包括应用重启后。新记录保存原始提示词和工具策略；较早的 Explore/Plan 记录使用只读策略恢复。所用模型必须仍在当前供应商配置中。

历史文件由后台线程读取，大文件沿用聊天记录分页索引。实时消息合并后以 32ms 间隔刷新；消息数、文本、工具参数和工具结果均有限额，完整原生记录保留在磁盘上。后台子代理仍运行时，父会话的 Pi 进程不会被空闲回收策略淘汰。

会话加载时随机展示 18 条使用提示，连续两次不重复。Markdown 和静态 HTML 产物在顶部切换源码与渲染/网页；偏好按文件类型保存于全局 `ui.documentPreviewModes`。大文档和不可用的网页组件会降级为有界源码预览。

本地验证入口：

```sh
runtime/node/bin/node --test tests/subagent-ui.test.mjs
.venv/bin/python -m unittest tests.test_subagent_pane tests.test_static_preview tests.test_loading_tips
.venv/bin/python tests/subagent_pane_ui_smoke.py
.venv/bin/python tests/document_modes_ui_smoke.py
```

原图、生成记录和小尺寸预览位于 `art/subagent-avatars/v1`；应用仅打包 `app/icons/subagents` 中的 256px 头像。
