# 远程环境

在本机 OpenSSH 配置里准备好主机别名、密钥和已信任的主机密钥。如果需要跳板机，在 OpenSSH 配置里设置 `ProxyJump`。Umeko 使用这个别名连接，设置里只保存别名、环境名和系统类型。

Umeko 按会话保存的终端 PATH 查找 OpenSSH，取不到终端环境时使用应用继承的 PATH。Windows 上的代理命令或密钥路径采用 POSIX 写法时，Umeko 会使用已安装的 Git for Windows OpenSSH。桌面设置显示实际使用的客户端路径和连接失败时的 OpenSSH 错误。

用 `umeko_desktop` 调用 `remote-environments.add`，传入 `name`、`host` 和 `platform`。`platform` 取 `linux` 或 `windows`。用 `remote-environments.list` 查看环境和连接状态，用 `remote-environments.test` 加 `name` 连接测试，用 `remote-environments.remove` 加 `name` 移除配置。桌面设置里的「远程环境」同步显示连接状态。

`remote_command` 的 `run` 操作接受环境名 `environment`、命令 `command`，以及可选的远程工作目录 `cwd` 和等待时间 `yieldMs`（毫秒）。Linux 使用远端 shell，Windows 使用 PowerShell。若返回 `running`，用同一个环境名和 `sessionId` 调用 `read` 读取新增输出。用 `write` 的 `input` 字段传入标准输入，命令按行读取时在结尾加换行。用 `kill` 停止该会话。

`remote_files` 支持 `read`、`write`、`list`、`search`、`upload` 和 `download`。用 `environment` 选环境，`path` 指远程路径，`localPath` 指传输时的本机路径。读文件支持 `offset` 和 `maxBytes`，查找文字时用 `query`。传输按分块推进，文件经 SHA-256 验证后写入目标。目录按文件合并，空目录也会复制。

首次连接时 Umeko 会将官方 Codex exec-server 复制到远端用户目录。SSH 断开后，设置和工具显示「正在重新连接」、重试次数和下次重试时间。只要环境仍在使用，间隔从 2 秒逐步增加，最多每分钟重试一次。等待中的工具在连接恢复后继续，连续断线 10 分钟时返回 SSH 错误，环境仍在后台尝试连接。

已启动的远端命令在断线期间继续执行。重新连上后，用原会话号从上次已读的位置继续读。正在等待的文件传输会从上次确认的分块继续。

服务器无法访问外网时，Umeko 会通过现有 SSH 连接共享本机网络。服务器恢复连接时会重新建立转发。可以在桌面设置的「远程环境」关闭共享，也可以用 `umeko_desktop` 调用 `network.remoteSharing`。共享启用时，普通下载命令无需添加代理参数，服务器的系统和用户配置照常保留。

`remote_network` 用 `status` 查看出口和远端端口，用 `test` 加 `url` 测试 HTTP 或 HTTPS 地址。`on`、`off` 和 `auto` 可以在当前连接中临时切换。`network.remoteProxy` 可以指定本机出口，传入空地址恢复系统代理。找不到系统代理时，内置代理访问公网地址。

Linux 上不读取代理设置的 TCP 程序可用 `remote_network` 的 `proxychains` 操作，传入 `command`。它使用服务器上已安装的 proxychains-ng，无需管理员权限。
