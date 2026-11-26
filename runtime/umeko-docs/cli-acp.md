# Umeko CLI 与 ACP（实验版）

Umeko CLI 可在终端里与 Pi 聊天、继续桌面会话和管理供应商。`umeko acp` 让支持 Agent Client Protocol 的编辑器通过本地子进程连接同一个 Umeko 宿主。两种入口在同一用户和同一配置目录下共享供应商、模型映射及 Pi 会话。没有运行中的宿主时，启动器会尝试在后台启动桌面宿主；用 `umeko desktop` 可打开窗口。

## 打包版 CLI 与 PATH

使用带 CLI 启动器的桌面包时，可在「设置 → Agent → Umeko Desktop」点击「配置 CLI 到 PATH」。Windows 写入当前用户的 PATH；macOS 和 Linux 为当前登录 Shell 写入用户配置，支持 zsh、bash 和 fish。关闭并重新打开终端，再运行下表中的命令。移动桌面包后，请在新位置打开 Umeko 并重新配置 PATH。

| 系统 | 打包版 CLI | 配置 PATH 后验证 |
| --- | --- | --- |
| Windows | 解压目录里与 `Umeko.exe` 同级的 `Umeko-cli.exe` | `Umeko-cli --help` |
| macOS | `Umeko.app/Contents/Resources/umeko` | `umeko --help` |
| Linux | 解压目录里与桌面程序 `Umeko` 同级的 `umeko` | `umeko --help` |

保留完整的应用目录。CLI 启动器会使用包内的桌面宿主和运行时。Windows 的桌面快捷方式和 `Umeko.exe` 仍会打开桌面窗口。

### Windows 手动配置 PATH

1. 在开始菜单搜索「编辑账户的环境变量」，编辑用户变量中的 `Path`。新增包含 `Umeko-cli.exe` 的目录，例如 `C:\Apps\Umeko`。
2. 关闭所有终端窗口后重新打开 PowerShell，运行 `Get-Command Umeko-cli` 确认位置，再运行 `Umeko-cli --help`。也可以直接运行 `& 'C:\Apps\Umeko\Umeko-cli.exe' --help`。

### macOS 手动配置 PATH

把 `Umeko.app` 放到「应用程序」目录。在 zsh 的 `~/.zshrc` 或 bash 的登录配置文件中加入下面一行，并换成实际位置。重新打开终端后运行 `umeko --help`。

```sh
export PATH="/Applications/Umeko.app/Contents/Resources:$PATH"
```

### Linux 手动配置 PATH

把归档解压到固定目录。在 bash 的 `~/.bashrc` 或 zsh 的 `~/.zshrc` 中加入下面一行。路径应指向包含小写 `umeko` 启动器的目录。重新打开终端后运行 `umeko --help`。

```sh
export PATH="$HOME/apps/Umeko:$PATH"
```

macOS 或 Linux 使用 fish 时，可在终端运行 `fish_add_path "/实际的/CLI/目录"`。编辑器可能使用自己的环境，配置 ACP 时可直接填写启动器的绝对路径。

## 从源码启动 CLI

macOS 或 Linux 在 Umeko 仓库目录运行 `bash setup.sh`，再将仓库目录加入 `PATH`。随后进入要工作的项目目录运行 `umeko`。也可以用仓库中 `umeko` 启动器的绝对路径。

Windows 在仓库目录运行 `./setup.ps1`。使用虚拟环境中的 `python.exe` 作为终端入口，例如：

```powershell
& .\.venv\Scripts\python.exe .\main.py --umeko-cli --help
& .\.venv\Scripts\python.exe .\main.py --umeko-cli chat --cwd 'D:\work\my-project'
```

## 常用命令

下表使用 `umeko` 写法。Windows 打包版将命令名替换为 `Umeko-cli`。从 Windows 源码运行时，使用上述 `python.exe` 加 `main.py --umeko-cli`，从其他目录调用时请填写两个文件的绝对路径。

| 命令 | 用途 |
| --- | --- |
| `umeko` 或 `umeko chat` | 在当前目录开始聊天。可用 `--cwd` 指定已有目录。聊天需要交互式终端。 |
| `umeko chat --model <别名> --effort <档位>` | 为当前会话选择 Umeko 模型别名和该模型支持的思考档位。 |
| `umeko desktop` | 打开当前配置对应的 Umeko 桌面窗口。 |
| `umeko session list` | 列出可继续的 Pi 会话，返回 ID、标题、工作目录和模型。 |
| `umeko chat --resume <会话ID>` 或 `umeko session resume <会话ID>` | 继续原会话，使用其保存的工作目录。 |
| `umeko session compact <会话ID> [说明]` | 请求压缩该会话的上下文。 |

聊天中输入 `/models` 搜索和切换模型及思考强度，也可添加常见、自定义或 ZIP 供应商。输入 `/compact [说明]` 请求压缩，当前回合忙时进入队列。生成期间 `Enter` 排队，`Ctrl+S` 向当前回合发出优先介入，`Ctrl+Q` 将输入保留在后续队列，`Ctrl+C` 停止当前回合。`Ctrl+B` 查看只读子智能体状态，`Ctrl+O` 展开思考和工具详情，`PgUp` 进入历史视图，`Ctrl+End` 返回最新输出。

## 在 CLI 管理供应商

`umeko provider list` 列出账号及其 ID，`umeko provider packages` 列出已安装的 Provider 插件。`umeko provider install <插件.zip>` 导入插件并返回账号 ID，需要登录时从桌面完成。`umeko provider config <账号ID> <配置.json>` 更新插件配置，`umeko provider models <账号ID> <模型数组.json>` 更新映射，`umeko provider refresh <账号ID>` 请求刷新该账号的模型。

普通供应商用 `umeko provider save <配置.json>`。更新现有账号时填入其 `id`。`keyEnv` 填环境变量名，CLI 从自己的进程环境读取密钥；更新时省略该字段可保留已保存的密钥。配置文件示例：

```json
{
  "name": "Example",
  "api": "openai",
  "baseUrl": "https://api.example.com/v1",
  "keyEnv": "EXAMPLE_API_KEY",
  "models": [{"upstream": "example-model", "alias": "example"}]
}
```

## 通过 ACP 接入编辑器

在编辑器中添加自定义 ACP Agent，选择本地子进程（stdio）。打包版的命令填写 `Umeko-cli.exe`（Windows）或 `umeko`（macOS、Linux）的绝对路径，参数填写 `["acp"]`。macOS 或 Linux 从源码启动时，使用仓库中的 `umeko` 绝对路径和相同参数。Windows 源码启动示例：

```json
{
  "command": "C:\\src\\Umeko\\.venv\\Scripts\\python.exe",
  "args": ["C:\\src\\Umeko\\main.py", "--umeko-cli", "acp"]
}
```

将路径换成实际位置，按编辑器的格式填写命令和参数。由编辑器启动进程并通过标准输入输出交换逐行 JSON-RPC 2.0 消息。`initialize` 返回 ACP 协议版本 `1`。`session/new` 和 `session/load` 使用本机绝对目录 `cwd`，恢复时该目录必须与会话保存的工作目录一致。创建或恢复时传入 `mcpServers: []`，MCP 配置由 Umeko 自己管理。

| 能力 | 当前支持范围 |
| --- | --- |
| 会话 | `session/new`、`session/list`、`session/load`、`session/close`。可按 `cwd` 筛选列表，恢复时回放近期文本历史。关闭连接后，已保存的会话可再次打开。 |
| 提问与停止 | `session/prompt` 接收文本并通过 `session/update` 流式发送回复、思考和工具状态。每个会话同一时间处理一次提问。用 `session/cancel` 停止本轮，再关闭会话。图片和文件附件可在桌面会话里发送。 |
| 选模与审批 | `session/set_config_option` 提供 `model` 和 `effort`。客户端可通过 `session/request_permission` 处理确认或选项选择。 |

编辑器调用的是 Umeko 当前用户配置中的 Pi 会话，模型凭据由 Umeko 管理。DeepSeek Harness 的入口在桌面「设置 → Agent → DeepSeek Harness」，此时 Umeko 通过 ACP 连接 dsh。向其他应用提供模型接口时，使用独立的 [API 代理服务](server-updates.md)。[ACP v1 协议总览](https://agentclientprotocol.com/protocol/v1/overview)

## 常见排查

- **找不到 CLI 或 `acp`**。核对 `PATH` 和启动器位置，用启动器绝对路径运行 `--help`，确认列出了 `chat`、`session` 和 `acp`。Windows 打包版的 CLI 命令名是 `Umeko-cli`。
- **无法连接宿主或看到空会话列表**。手动启动同一构建的 Umeko，确认编辑器与桌面使用同一系统账号、同一配置目录。使用过 `UMEKO_DATA_DIR` 时，在两边配置相同路径。CLI 和 ACP 的会话列表面向普通 Pi 会话。
- **找不到模型别名**。先用 `/models` 或桌面模型菜单确认实际别名，检查供应商已配置并完成登录。
- **`cwd does not match the saved Umeko session`**。先用 `umeko session list` 查该会话的 `workspace`，再让编辑器以该绝对目录恢复。
- **编辑器报协议错误或一直等待**。确认它启动的是 `acp` 子命令，且启动脚本的标准输出只传输 ACP 消息。如需诊断输出，使用标准错误。
