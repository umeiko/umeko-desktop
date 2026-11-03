# 安装与更新 {#install-update}

## 选择版本 {#choose-an-edition}

| 版本 | 下载入口 | 说明 |
| --- | --- | --- |
| Python / Qt | [稳定版 Release](https://github.com/umeiko/umeko-desktop/releases/latest) | 本文档所在仓库，完整 Qt 桌面应用 |
| C++ / Qt | [稳定版 Release](https://github.com/umeiko/umeko-desktop-cpp/releases/latest) | 原生 C++ 宿主，界面与大部分功能共用 |

按自己的系统和 CPU 选择资源。不要把两个版本覆盖安装在同一目录；它们有独立的数据与凭据格式。

## 各平台安装 {#install-on-your-platform}

| 平台 | 操作 |
| --- | --- |
| Windows x64 | 解压完整 ZIP 到可写目录，运行 `Umeko.exe` 或 `UmekoCpp.exe`。不要只复制 EXE。 |
| macOS Apple Silicon / Intel | 选择匹配架构的 DMG，打开后拖入 Applications；也可使用完整 ZIP。当前包尚未公证，首次打开可能需要在系统隐私与安全设置中确认。 |
| Linux x64 | 解压完整 `tar.gz`，在图形桌面中运行 `Umeko` 或 `UmekoCpp`。保留同目录的库、插件与运行时。 |

Linux 仍需要桌面的 Qt 平台依赖与可用密钥环。中文输入问题见[故障排查](../troubleshooting#linux-input-methods)。安装版已经携带模型运行所需的 Pi、Node.js/npm、搜索程序和对应运行时。

## 在应用中更新 {#update-inside-the-app}

1. 在 **设置 → 关于** 检查稳定版本并下载。下载器使用系统代理，校验包大小与 SHA-256。
2. 校验成功后点击 **安装新版本**，确认 **停止并安装**。此时所有 Agent 停止，主窗口关闭，独立安装器接手。
3. 完成后点击启动新版本。未完成的模型任务需要重新发起。

安装目录及其父目录必须可写，并预留下载、解压和备份所需空间。旧安装目录保留为相邻的 `.previous-…` 备份，用户数据在安装目录之外。自行维护的源码目录仍通过自己的 Git 流程更新。

## Release 与 Preview 通道 {#release-and-preview-channels}

Python 版在 **设置 → 关于 → 更新通道** 中可选择 **正式版** 或 **预览版**。Windows、macOS、Linux 安装包和此功能管理的源码目录支持切换；普通源码目录会说明应由你自行通过 Git 更新。

Release 使用已发布的稳定包。Preview 使用官方仓库最新 `main`，尚未发布，可能不稳定。首次切换前，先等待任务结束、退出应用，备份下文中的实际用户目录和项目文件。两个通道共用配置，旧 Release 不保证能理解新版设置；保留旧程序不等于配置也已回退。

选择 Preview 后，应用先检查 Git、带 `venv` 的 Python 3.10+、Node.js 22.19+ 和 npm、平台安装脚本所需的 shell、至少 2 GiB 可用空间及官方仓库网络连接。检查完成后先审阅，再确认准备。应用会在用户目录下的专用 Preview 源码目录克隆 `https://github.com/umeiko/umeko-desktop.git`，运行其中的 `setup.ps1` 或 `setup.sh`；过程显示进度并可取消。准备失败或取消时仍保留 Release，依赖安装失败可重试。

准备成功后，通道状态单独保存，不写入 `settings.json`。下次从保留的 Release 程序启动，会直接使用 Preview 虚拟环境的 Python 运行 `main.py`，不经过可能优先选择旧 `dist` 包的源码启动脚本。

Preview 的 **检查更新** 会获取官方提交，展示当前提交 → 目标提交及提交摘要。确认后仅快进到已确认的目标；存在本地修改、暂存修改、未跟踪文件覆盖风险、错误来源或分叉历史时停止，不丢弃本地工作。只有依赖输入变化时才重新运行安装脚本；安装失败会保留待重试状态。

切回 Release 使用保留的原程序，继续保留共用的用户数据和设置；切回不会自动撤销 Preview 的配置迁移。默认保留源码；若 Preview 仍在运行，可选的删除操作会等它退出且 Release 重启后执行；只删除受管理的源码和依赖，有本地改动时保留，不删除配置或用户目录。

若 Preview 无法启动，可给保留的安装包传入 `--release-channel`，直接选择并打开正式版，保留设置与会话。例如 Windows 使用 `Umeko.exe --release-channel`，macOS 使用 `Umeko.app/Contents/MacOS/Umeko --release-channel`，Linux 使用 `./Umeko --release-channel`。

准备与更新使用的网络设置各有范围：应用中的 npm 源、`.npmrc` 和 CA 覆盖只传给 npm；模型供应商代理不控制 Git 克隆或 pip 安装。Git、pip 使用各自的配置、代理和 CA，更新器的系统代理会传给准备进程。应用不改写全局配置，也不会在配置的端点失败后自动切换公共源。

## 数据与备份 {#data-and-backups}

| 版本 | 默认用户目录 |
| --- | --- |
| Python / Qt | `~/.umeko/desktop` |
| C++ / Qt | `~/.umeko/desktop-cpp` |

`~` 表示用户主目录。**设置 → 外观 → 用户数据目录** 可打开实际位置；自定义启动参数或环境变量可能改变该位置。备份前等待任务结束并退出应用，再备份该目录和项目文件。

账号密钥使用系统安全存储。仅复制数据目录到其他机器，并不能保证账号继续可用；需要重新登录或填写 Key。两个版本请保持独立配置。
