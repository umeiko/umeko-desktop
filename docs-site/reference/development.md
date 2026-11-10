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

需要 Python 3.10+、Node.js 22.19+ 和 npm。虚拟环境与系统绑定，请在要运行的系统上执行安装脚本。

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

在目标平台使用 `build.sh` 或 `build.ps1` 构建。更完整的环境、测试与打包要求见[仓库手册](https://github.com/umeiko/umeko-desktop/blob/main/docs/user-guide.md)。开发和测试时使用单独的配置目录，与日常账号和会话分开。

## 选对插件接口 {#choose-the-right-plugin-interface}

- 接入账号登录、模型发现与推理：Provider SDK。
- 扩展桌面页面、应用服务、小窗以及与当前聊天通信：Widget SDK。
- 扩展 Pi 内核工具、命令与任务行为：Pi 扩展；通过内嵌 Pi 安装。

使用应用导出的 SDK 和示例，与本机版本保持一致。先验证包，再导入单独的测试环境。插件只调用公开的 SDK 接口，特定供应商的实现放在各自的插件里。

需要 SDK 增加能力时，请提交最小复现和通用的接口需求。
