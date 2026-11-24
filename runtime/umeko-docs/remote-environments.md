# 远程环境

在本机 OpenSSH 配置里准备好主机别名、密钥和已信任的主机密钥。如果需要跳板机，在 OpenSSH 配置里设置 `ProxyJump`。Umeko 使用这个别名连接，设置里只保存别名、环境名和系统类型。

Umeko 按终端的 PATH 查找 OpenSSH。Windows 上的代理命令或密钥路径采用 POSIX 写法时，Umeko 会使用已安装的 Git for Windows OpenSSH。桌面设置显示实际使用的客户端路径和连接失败时的 OpenSSH 错误。

用 `umeko_desktop` 调用 `remote-environments.add`，传入 `name`、`host` 和 `platform`。`platform` 取 `linux` 或 `windows`。用 `remote-environments.list` 查看环境和连接状态，用 `remote-environments.test` 加 `name` 连接测试，用 `remote-environments.remove` 加 `name` 移除配置。桌面设置里的「远程环境」同步显示连接状态。

`remote_command` 的 `run` 操作接受环境名 `environment`、命令 `command`，以及可选的远程工作目录 `cwd` 和等待时间 `yieldMs`（毫秒）。Linux 使用远端 shell，Windows 使用 PowerShell。若返回 `running`，用同一个环境名和 `sessionId` 调用 `read` 读取新增输出。用 `write` 的 `input` 字段传入标准输入，命令按行读取时在结尾加换行。用 `kill` 停止该会话。

`remote_files` 支持 `read`、`write`、`list`、`search`、`upload` 和 `download`。用 `environment` 选环境，`path` 指远程路径，`localPath` 指传输时的本机路径。读文件支持 `offset` 和 `maxBytes`，查找文字时用 `query`。传输按分块推进，文件经 SHA-256 验证后写入目标。目录按文件合并，空目录也会复制。

首次连接时 Umeko 会将官方 Codex exec-server 复制到远端用户目录。连接断开时工具会尝试重连，已启动的远程命令继续运行。保持 Umeko 的会话打开，可继续读命令输出或等待传输。
