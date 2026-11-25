# 子代理侧栏

需要指定不同模型委派任务时，先看 [委派子代理与正确调用名称](../runtime/umeko-docs/delegate-subagents.md)。运行中 `umeko_desktop help` 返回的同名文档会动态包含当前实例可用的模型，调用时使用其中的名称。

子代理由固定版本的 `@gotgenes/pi-subagents` 社区包执行；桌面界面读取它的原生事件和会话文件来显示。

- 子代理数量默认不限；在社区包中设置了并发上限时按该设置执行。四个角色分别使用烧盐柠檬、小鞠知花、温水佳树、志喜屋梦子的头像，重复角色通过序号区分。
- 主聊天中保留紧凑的任务卡片。点击卡片在右侧查看该子代理的消息、思考过程和工具调用；侧栏复用产物面板的 PID 动画和宽度拖动。
- 有活动任务时，右上角显示头像与数量。下拉列表只列出当前主会话的活动子代理。
- 一次启动超过 4 个子代理时，主聊天折叠为集合入口；点击后打开可滚动的任务矩阵，再次点击相同入口会收起。
- 侧栏输入复用主聊天逻辑：Enter 排队，Ctrl+S 立即打断并优先介入；输入为空时，Ctrl+S 提升队列首条。队列显示在输入框上方，支持编辑、删除和引导。草稿、附件和队列按子代理隔离，停止后待发送内容会退回相应草稿。
- 侧栏支持拖入文件与图片，显示对应角色的接取形象。停止按钮只中断该子代理。关闭侧栏后任务继续运行；进入设置或切换主会话会关闭当前侧栏。
- 已结束的历史子代理可以从原生会话文件继续，包括应用重启后。新记录保存原始提示词和工具策略；较早的 Explore/Plan 记录使用只读策略恢复。所用模型必须仍在当前供应商配置中。

历史文件由后台线程读取，大文件沿用聊天记录分页索引。实时消息合并后以 32ms 间隔刷新；消息数、文本、工具参数和工具结果均有限额，完整原生记录保留在磁盘上。后台子代理运行期间，父会话的 Pi 进程保持运行。

会话加载时随机展示 18 条使用提示，连续两次不重复。Markdown 和静态 HTML 产物在顶部切换源码与渲染/网页；偏好按文件类型保存于全局 `ui.documentPreviewModes`。大文档和不可用的网页组件会降级为有界源码预览。

本地验证入口：

```sh
runtime/node/bin/node --test tests/subagent-ui.test.mjs
.venv/bin/python -m unittest tests.test_subagent_pane tests.test_static_preview tests.test_loading_tips
.venv/bin/python tests/subagent_pane_ui_smoke.py
.venv/bin/python tests/document_modes_ui_smoke.py
```

原图、生成记录和小尺寸预览位于 `art/subagent-avatars/v1`；应用仅打包 `app/icons/subagents` 中的 256px 头像。
