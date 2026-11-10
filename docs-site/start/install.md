# 安装与更新 {#install-update}

## 选择版本 {#choose-an-edition}

| 版本 | 下载入口 | 说明 |
| --- | --- | --- |
| Python / Qt | [稳定版 Release](https://github.com/umeiko/umeko-desktop/releases/latest) | 本文档所在仓库，完整 Qt 桌面应用 |
| C++ / Qt | [稳定版 Release](https://github.com/umeiko/umeko-desktop-cpp/releases/latest) | 原生 C++ 宿主，界面与大部分功能共用 |

按自己的系统和 CPU 选择资源。两个版本的数据与凭据格式各自独立，请分别安装在不同目录。

## 各平台安装 {#install-on-your-platform}

| 平台 | 操作 |
| --- | --- |
| Windows x64 | 把完整 ZIP 解压到可写目录，运行其中的 `Umeko.exe` 或 `UmekoCpp.exe`。程序需要同目录的其他文件。 |
| macOS Apple Silicon / Intel | 选择匹配架构的 DMG，打开后拖入「应用程序」；也可使用完整 ZIP。安装包未经公证，首次打开时可能需要在系统的「隐私与安全性」中确认。 |
| Linux x64 | 解压完整 `tar.gz`，在图形桌面中运行 `Umeko` 或 `UmekoCpp`。保留同目录的库、插件与运行时。 |

Linux 需要桌面的 Qt 平台依赖与可用的密钥环。中文输入问题见[故障排查](../troubleshooting#linux-input-methods)。安装包已携带 Pi、Node.js/npm、搜索程序和对应运行时。

## 在应用中更新 {#update-inside-the-app}

1. 在 **设置 → 关于** 检查稳定版本并下载。下载器使用系统代理，并校验包大小与 SHA-256。
2. 校验成功后点击 **安装新版本**，确认 **停止并安装**。此时所有 Agent 停止，主窗口关闭，由独立安装器接手。
3. 完成后点击启动新版本，再重新发起之前未完成的模型任务。

安装目录及其父目录需要可写，并预留下载、解压和备份所需空间。旧版本保留在旁边的 `.previous-…` 备份目录中；用户数据保存在安装目录之外。自己维护的源码目录通过 Git 更新。

## Release 与 Preview 通道 {#release-and-preview-channels}

Python 版在 **设置 → 关于 → 更新通道** 中可选择 **正式版** 或 **预览版**。Windows、macOS、Linux 安装包和由此功能管理的源码目录都可以切换；普通源码目录请自行用 Git 更新，界面会给出提示。

Release 使用已发布的稳定包。Preview 使用官方仓库最新的 `main`，包含尚未发布的改动，稳定性较低。首次切换前，等任务结束、退出应用，备份下文所述的用户目录和项目文件。两个通道共用同一份配置；Preview 写入的新设置可能是旧 Release 读不懂的，需要回到旧配置时用这份备份恢复。

选择 Preview 后，应用先检查 Git、带 `venv` 的 Python 3.10+、Node.js 22.19+ 和 npm、平台安装脚本所需的 shell、至少 2 GiB 可用空间，以及到官方仓库的网络连接。查看检查结果并确认后，应用在用户目录下的专用 Preview 源码目录克隆 `https://github.com/umeiko/umeko-desktop.git`，运行其中的 `setup.ps1` 或 `setup.sh`，并显示进度，可随时取消。准备失败或取消时继续使用 Release；依赖安装失败可以重试。

准备成功后，通道状态单独保存在 `settings.json` 之外。之后从保留的 Release 程序启动时，应用直接用 Preview 虚拟环境中的 Python 运行 `main.py`，不经过源码启动脚本（该脚本会优先选用已打包的 `dist`）。

Preview 的 **检查更新** 会获取官方提交，展示当前提交 → 目标提交及提交摘要。确认后快进到该目标提交。遇到本地修改、暂存修改、会被覆盖的未跟踪文件、非官方来源或分叉历史时，更新会停下并保留你的本地工作。依赖相关的文件变化时才会重新运行安装脚本；安装失败时保留待重试状态。

切回 Release 时使用保留的原程序，用户数据和设置保持不变，包括 Preview 迁移过的设置。Preview 源码默认保留。你也可以选择删除它：若 Preview 正在运行，删除会在它退出、Release 重启后进行；只删除受管理的源码和依赖，有本地改动时保留源码，配置和用户目录保持不变。

若 Preview 无法启动，可给保留的安装包传入 `--release-channel`，直接选择并打开正式版，设置与会话照常保留。例如 Windows 使用 `Umeko.exe --release-channel`，macOS 使用 `Umeko.app/Contents/MacOS/Umeko --release-channel`，Linux 使用 `./Umeko --release-channel`。

准备与更新时，各项网络设置分别作用于不同工具：应用中的 npm 源、`.npmrc` 和 CA 设置只用于 npm；模型供应商代理只用于模型请求。Git 和 pip 使用各自的配置、代理和 CA，更新器的系统代理也会传给准备过程。应用只使用你配置的端点，全局配置保持不变。

## 数据与备份 {#data-and-backups}

| 版本 | 默认用户目录 |
| --- | --- |
| Python / Qt | `~/.umeko/desktop` |
| C++ / Qt | `~/.umeko/desktop-cpp` |

`~` 表示用户主目录。**设置 → 外观 → 用户数据目录** 可打开实际位置；自定义启动参数或环境变量可以改变该位置。备份前等待任务结束并退出应用，再备份该目录和项目文件。

账号密钥保存在系统安全存储中。把数据目录复制到其他机器后，请重新登录或填写 Key。两个版本各自保持独立配置。
