# 手动 Preview 发布

在 [Actions → Preview desktop release](https://github.com/umeiko/umeko-desktop/actions/workflows/preview.yml) 点击 **Run workflow**：

1. 工作流分支保留 `main`。
2. `source_ref` 填本仓库要测试的分支、标签或提交 SHA，例如 `codex/preview-pr72-r2`。
3. 勾选需要的平台。默认仅 Windows x64；Linux x64、macOS Apple Silicon、macOS Intel 可以按需多选。全部取消会直接失败。
4. 在 `notes` 填实验功能说明，然后运行。

流程先固定源码提交，复用现有共享测试，只为选中平台构建。所有共享测试、选中平台的原生测试和打包后验证成功，且归档校验和正确后，才发布 GitHub **Pre-release**。上传后还会核对 GitHub 返回的文件大小和 SHA-256。

每次运行使用独立标签 `preview-v<应用版本>-<run_id>-<attempt>`，包含对应包、构建报告及校验和。重跑不会覆盖已有预览版。Preview 不设为 Latest，不修改正式发布下载链接，也不改应用版本号；正式版仍由原发布流程管理。应用现有的源码预览切换功能与这个安装包发布流程相互独立。

命令行示例：

```sh
gh workflow run preview.yml --ref main \
  -f source_ref=codex/preview-pr72-r2 \
  -f windows_x64=true -f linux_x64=false \
  -f macos_arm64=false -f macos_x64=false \
  -f notes='PR #72 历史记录修复、输入框简化及 HTTPS 打包修复'
```

源码需要包含现有 `setup`、`build`、`ci-smoke.py` 和 `package-release.py` 流程。失败时查看对应任务日志及 `preview-diagnostics-*` artifact；发布失败可能保留未公开的草稿，不会把未经验证的包发布出去。
