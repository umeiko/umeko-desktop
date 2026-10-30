"""CodeArts plugin strings; host and SDK stay provider independent."""

STRINGS = {
    "title": ("连接 CodeArts", "Connect CodeArts"),
    "checking": ("正在检查 CodeArts CLI…", "Checking CodeArts CLI…"),
    "guide": ("右上角用户名 → 我的凭证 → 访问密钥 → 新增访问密钥 → 下载访问密钥\n访问密钥仅能下载一次；验证成功并安全保存后，本插件会删除本次下载的 CSV。也可在此私密粘贴 CSV 内容或依次粘贴 AK、SK。", "In Huawei Cloud Console, choose Username → My Credentials → Access Keys → Create Access Key → Download Access Key. The key can only be downloaded once. After verification and protected storage succeed, this plugin deletes the newly downloaded CSV. You can also privately paste its contents or AK followed by SK here."),
    "installing": ("正在下载并安装官方 CodeArts CLI…", "Downloading and installing the official CodeArts CLI…"),
    "installed": ("CodeArts CLI 安装完成。", "CodeArts CLI installed."),
    "install_failed": ("CodeArts CLI 下载或安装失败，请检查网络后重试。", "CodeArts CLI download or installation failed. Check your network and retry."),
    "verifying": ("正在通过官方 CodeArts CLI 验证凭据…", "Verifying credentials with the official CodeArts CLI…"),
    "verify_failed": ("CodeArts 凭据验证失败，未保存凭据。", "CodeArts credential verification failed. Credentials were not saved."),
    "connected": ("CodeArts 已连接。", "CodeArts connected."),
    "saved": ("CodeArts 已连接；凭据已安全保存。", "CodeArts connected; credentials are stored securely."),
    "deleted_csv": ("CodeArts 已连接；凭据已安全保存，新下载的 CSV 已删除。", "CodeArts connected; credentials are stored securely and the new CSV was deleted."),
    "delete_csv": ("CodeArts 已连接；凭据已安全保存，请手动删除新下载的 CSV。", "CodeArts connected; credentials are stored securely. Please delete the new CSV manually."),
    "connect_failed": ("无法连接 CodeArts，请检查 CLI、网络和安全凭据存储。", "Cannot connect to CodeArts. Check the CLI, network and protected credential storage."),
    "read_failed": ("无法读取新下载的 CSV，请重新下载或私密粘贴凭据。", "Cannot read the new CSV. Download it again or paste credentials privately."),
    "invalid": ("无法识别凭据，请选择官方 CSV 或依次粘贴 AK、SK。", "Unrecognized credentials. Use the official CSV or paste AK followed by SK."),
    "cancelled_file": ("操作已取消，下载文件已保留。", "Cancelled; the downloaded file was kept."),
    "save_failed": ("CodeArts 验证或安全保存失败，下载文件已保留。", "CodeArts verification or protected storage failed. The downloaded file was kept."),
    "cli_unavailable": ("CodeArts CLI 未就绪。", "CodeArts CLI is not ready."),
    "cancelled": ("操作已取消。", "Operation cancelled."),
    "connect_first": ("请先完成 CodeArts 连接。", "Connect CodeArts first."),
    "empty": ("请输入凭据 CSV 或两项凭据。", "Enter the credentials CSV or both credentials."),
    "one_row": ("CSV 必须包含一组完整凭据。", "The CSV must contain one complete credential pair."),
    "missing": ("CSV 中缺少凭据。", "Credentials are missing from the CSV."),
    "headers": ("CSV 中缺少 AK/SK 凭据表头。", "The CSV is missing AK/SK credential headers."),
    "open_console": ("打开华为云控制台", "Open Huawei Cloud Console"),
    "paste": ("私密粘贴凭据", "Paste credentials privately"),
    "open_failed": ("无法打开浏览器，请私密粘贴 CSV 内容或两项密钥。", "Cannot open the browser. Paste the CSV contents or both keys privately."),
    "status_unconnected": ("CodeArts 尚未连接。", "CodeArts is not connected."),
    "credential_label": ("CSV 内容或 AK、SK", "CSV contents or AK and SK"),
    "watching": ("正在等待新下载的访问密钥 CSV…", "Waiting for a newly downloaded access-key CSV…"),
    "import_cancel": ("取消导入", "Cancel import"),
    "transport_request": ("CodeArts 请求未能完成，请重试。", "The CodeArts request could not be completed. Please retry."),
    "transport_timeout": ("CodeArts 长时间没有返回内容，请重试。", "CodeArts did not return content in time. Please retry."),
    "transport_abort": ("已取消 CodeArts 请求。", "The CodeArts request was cancelled."),
    "transport_tool": ("无法继续这次工具调用，请重新发送问题。", "This tool call cannot continue. Please send the question again."),
    "transport_stream": ("CodeArts 响应提前结束，请重试。", "The CodeArts response ended early. Please retry."),
    "server_not_connected": ("请先导入 CodeArts 凭据并完成连接。", "Import CodeArts credentials and connect first."),
    "server_start_failed": ("CodeArts 本地服务启动失败，请检查 CLI 安装后重试。", "The local CodeArts service could not start. Check the CLI installation and retry."),
    "server_closed": ("CodeArts 本地服务已关闭。", "The local CodeArts service is closed."),
    "server_cancelled": ("CodeArts 请求已取消。", "The CodeArts request was cancelled."),
    "server_started": ("CodeArts 本地服务已就绪。", "The local CodeArts service is ready."),
    "server_starting": ("正在启动 CodeArts 本地服务…", "Starting the local CodeArts service…"),
    "server_invalid_id": ("CodeArts 请求标识无效。", "The CodeArts request ID is invalid."),
    "server_duplicate_id": ("CodeArts 请求标识已使用。", "The CodeArts request ID has already been used."),
    "server_queue_timeout": ("等待 CodeArts 并发名额超时，请重试。", "Timed out waiting for an available CodeArts request slot. Please retry."),
    "server_invalid_request": ("CodeArts 控制请求无效。", "The CodeArts control request is invalid."),
    "server_cancel_target": ("请指定要取消的 CodeArts 请求。", "Specify the CodeArts request to cancel."),
    "server_unsupported": ("不支持的 CodeArts 控制操作。", "This CodeArts control operation is not supported."),
}


def tr(language, key, **values):
    """Default to Chinese; the host's language can be a value or callable."""
    language = language() if callable(language) else language
    return STRINGS[key][1 if str(language or "zh").lower().startswith("en") else 0].format(**values)


CONSOLE_URL = "https://console.huaweicloud.com/console/?locale=zh-cn"
