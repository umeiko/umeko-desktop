# Preview 发布

## main 的滚动 Windows 预览包

日常 `Desktop packages` CI 保留完整共享测试，只构建 Windows x64 安装包。`main` 的测试和打包验证全部通过后，最后一个发布任务会更新固定的 [preview 预发布版](https://github.com/umeiko/umeko-desktop/releases/tag/preview)。PR 不执行发布，其他分支的手动 CI 也不会替换它。

发布任务仅下载本次 CI 的 Windows 包，核对源码提交、打包后的 GUI/Pi/终端结果及 SHA-256，再上传到临时草稿。确认 GitHub 上的文件大小和校验和后，删除旧 `preview` Release 和标签，将已上传的新包发布到同名 `preview`。上传或校验失败时旧包仍然保留；切换发布时出错会保留已验证的草稿供恢复。版本始终标记为 Pre-release，不替换正式版 Latest，也不修改应用版本号。

发布前会再次核对 `main`：过时 CI 不会覆盖新提交的预览包。发布任务串行执行，避免两个 CI 同时替换 `preview`。

正式版需要多平台构建时，在 **Desktop packages → Run workflow** 勾选 `all_platforms`，再按现有正式发布流程选择这个成功的运行。

## 手动实验 Preview

在 [Actions → Preview desktop release](https://github.com/umeiko/umeko-desktop/actions/workflows/preview.yml) 点击 **Run workflow**：

1. 工作流分支保留 `main`。
2. `source_ref` 填本仓库要测试的分支、标签或提交 SHA，例如 `codex/preview-pr72-r2`。
3. 勾选需要的平台。默认仅 Windows x64；Linux x64、macOS Apple Silicon、macOS Intel 可以按需多选。全部取消会直接失败。
4. 在 `notes` 填实验功能说明，然后运行。

仅重试发布时，可在 `build_run` 填之前的 Preview 运行 ID，保留相同 `source_ref` 提交及平台选择。流程会验证该运行的选中平台打包任务成功，复用它的包，并再次核对源码提交和校验和；不会重新构建。留空则正常构建。

流程先固定源码提交，只为选中平台构建。Preview 用于快速实验，不运行全量单测、完整 UI 测试或额外原生回归；仅保留打包后启动、运行时、终端及源码已提供的 HTTPS 基础验证。基础验证通过且归档校验和正确后，发布 GitHub **Pre-release**。上传后还会核对 GitHub 返回的文件大小和 SHA-256。正式版继续使用原有完整 CI。

每次运行使用独立标签 `preview-v<应用版本>-<run_id>-<attempt>`，包含对应包、构建报告及校验和。重跑不会覆盖已有预览版。Preview 不设为 Latest，不修改正式发布下载链接，也不改应用版本号；正式版仍由原发布流程管理。应用现有的源码预览切换功能与这个安装包发布流程相互独立。

命令行示例：

```sh
gh workflow run preview.yml --ref main \
  -f source_ref=codex/preview-pr72-r2 \
  -f windows_x64=true -f linux_x64=false \
  -f macos_arm64=false -f macos_x64=false \
  -f notes='PR #72 历史记录修复、输入框简化及 HTTPS 打包修复'
```

源码需要包含现有 `setup`、`build`、`package-release.py` 和支持 `--preview` 的 `ci-smoke.py`（旧分支可先同步此脚本选项）。Preview 跳过额外浏览器界面和后台任务生命周期场景，默认的正式版 smoke 检查不变。失败时查看对应任务日志及 `preview-diagnostics-*` artifact；发布失败可能保留未公开的草稿，不会把未经验证的包发布出去。
