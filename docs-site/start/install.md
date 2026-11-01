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

安装目录及其父目录必须可写，并预留下载、解压和备份所需空间。旧安装目录保留为相邻的 `.previous-…` 备份，用户数据在安装目录之外。源码运行请通过 Git 更新源码。

## 数据与备份 {#data-and-backups}

| 版本 | 默认用户目录 |
| --- | --- |
| Python / Qt | `~/.umeko/desktop` |
| C++ / Qt | `~/.umeko/desktop-cpp` |

`~` 表示用户主目录。**设置 → 外观 → 用户数据目录** 可打开实际位置；自定义启动参数或环境变量可能改变该位置。备份前等待任务结束并退出应用，再备份该目录和项目文件。

账号密钥使用系统安全存储。仅复制数据目录到其他机器，并不能保证账号继续可用；需要重新登录或填写 Key。两个版本请保持独立配置。
