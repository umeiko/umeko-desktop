# 版本管理

界面以 VS Code 的 SCM 面板为参考：100% 字号下为 22px 列表行、16px Codicons、26px 提交控件，上下分区并排显示更改与提交图。提交图读取本地 Git 的真实父提交、作者和分支引用；点击提交可查看有界差异。文件图标直接使用 Seti 主题及其语言关联。字号随 Umeko 外观设置缩放。

图标来源和许可证位于 `assets/sources.json`、`assets/Codicons-LICENSE.txt` 与 `assets/Seti-ThirdPartyNotices.txt`。

Umeko 官方演示插件，使用本机 Git，在当前会话的仓库中工作。

- Source Control 风格的暂存更改、工作区更改、未跟踪文件分组。
- 分支信息、提交历史和文件文本差异；内容量受限制，大仓库不阻塞聊天界面。
- 加号暂存单个文件，减号取消暂存；提交只包含已经暂存的更改，需要用户填写说明并点击提交。
- 分支按钮提供新建分支、切换和游离检出，丢弃更改需要用户确认并先保存本地备份；不执行 push、pull 或 clean。
- diff 禁用外部 diff/textconv；提交不运行仓库钩子。命令不通过 shell 拼接。
- 后台命令有超时和输出大小上限；页面关闭或切换会话会停止其插件进程。

需要 PATH 中有 git，或在目标机器安装 Git。本演示不内置另外一套 Git。
