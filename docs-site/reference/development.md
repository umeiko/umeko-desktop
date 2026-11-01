# 开发与 SDK {#development-sdks}

文档站共用一套用户指南；代码仍在两个独立仓库中。

| 资源 | 入口 |
| --- | --- |
| Python / Qt 源码 | [umeko-desktop](https://github.com/umeiko/umeko-desktop) |
| C++ / Qt 源码与构建 | [umeko-desktop-cpp](https://github.com/umeiko/umeko-desktop-cpp) |
| Provider SDK | [API、认证、模型发现与推理](https://github.com/umeiko/umeko-desktop/blob/main/provider_dev/README.md) |
| Widget SDK | [清单、权限、生命周期与宿主接口](https://github.com/umeiko/umeko-desktop/blob/main/plugin-runtime/README.md) |
| Widget 示例 | [文件树、Git、终端等](https://github.com/umeiko/umeko-desktop/tree/main/umeko-plugins) |
| 主题格式 | [JSON 配色与制作提示词](https://github.com/umeiko/umeko-desktop/blob/main/docs/themes.md) |
| 人物格式 | [图片、台词与 ZIP 限制](https://github.com/umeiko/umeko-desktop/blob/main/docs/characters.md) |
| submit 工具 | [参数、结果与预览边界](https://github.com/umeiko/umeko-desktop/blob/main/docs/chatbox-media.md) |
| 内嵌 Pi 命令 | [run_pi_command 行为](https://github.com/umeiko/umeko-desktop/blob/main/docs/embedded-pi-commands.md) |

## Python 版从源码启动 {#run-the-python-edition-from-source}

需要 Python 3.10+、Node.js 22.19+ 和 npm。在当前操作系统上安装依赖，不要从其他系统复制虚拟环境。

::: code-group
```bash [Linux / macOS]
bash setup.sh
bash Start-Umeko.sh
```
```powershell [Windows]
./setup.ps1
./Start-Umeko.cmd
```
:::

在目标平台使用 `build.sh` 或 `build.ps1` 构建。更完整的环境、测试与打包要求见[仓库手册](https://github.com/umeiko/umeko-desktop/blob/main/docs/user-guide.md)。开发与验收应使用隔离配置，不复用日常账号和会话。

## 选对插件接口 {#choose-the-right-plugin-interface}

- 接入账号登录、模型发现与推理：Provider SDK。
- 扩展桌面页面、应用服务、小窗以及与当前聊天通信：Widget SDK。
- 扩展 Pi 内核工具、命令与任务行为：Pi 扩展；通过内嵌 Pi 安装。

优先使用应用导出的 SDK 和示例，与本机版本保持一致。先验证包，再导入隔离环境；不要依赖宿主私有 Python 模块或把特定供应商实现写进通用 SDK。

SDK 能力不足时，提供最小复现与通用接口需求，让兼容性修补可以独立验证。
