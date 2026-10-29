# Umeko Plugin SDK · API v1

Umeko 插件扩展桌面应用和会话；它与 Pi 扩展、MCP、供应商插件是独立的扩展类型。Python 和 C++ 两个桌面版使用相同的 ZIP、SDK 和 JSONL 工作进程协议。

## 包结构

```text
my-plugin/
  manifest.json
  README.md
  config.json
  config.schema.json
  scripts/plugin.py
  qml/Main.qml            # 可选；没有页面的插件在启用的当前会话中运行
  bin/linux-x64/tool      # 可选：按操作系统和架构声明的程序
  bin/windows-x64/tool.exe
  vendor/                 # 可选：与目标 Python / OS / 架构兼容的依赖
```

清单范例：

```json
{
  "kind": "umeko-plugin",
  "apiVersion": 1,
  "id": "my-plugin",
  "name": "我的插件",
  "description": "插件的功能介绍",
  "author": "Your name",
  "version": "1.0.0",
  "entrypoint": "scripts/plugin.py:create_plugin",
  "page": "qml/Main.qml",
  "readme": "README.md",
  "config": "config.json",
  "configSchema": "config.schema.json",
  "permissions": ["workspace.read", "session.read", "session.write"],
  "executables": {}
}
```

`config.json` 是非秘密的 JSON 对象，`config.schema.json` 支持 type、properties、required、additionalProperties、items、enum。账号密码和密钥不要放入配置、Markdown、公开返回值或日志。示例和 SDK ZIP 可在插件管理页面导出，导出包中包含文件树与 Git 示例。

```bash
python -m umeko_plugin_sdk validate my-plugin
python -m umeko_plugin_sdk pack my-plugin my-plugin.zip
```

在“设置 → Umeko 插件管理”导入 ZIP，再勾选“在当前会话启用”。导入、读取说明和保存配置均不执行插件入口。内置插件不能被第三方 ZIP 覆盖。升级请使用新的版本号；已有配置必须通过新版本 schema 校验，否则保留旧版本。卸载清除插件包和设置，不触碰会话工作目录中的文件。

## Python 接口

```python
from umeko_plugin_sdk import Plugin

class MyPlugin(Plugin):
    def handle(self, method, arguments):
        if method == "greet":
            self.context.send_message("请检查这个项目", steering=True)
            return {"message": "已发给当前会话"}
        return {"workspace": str(self.context.workspace)}

def create_plugin(context):
    return MyPlugin(context)
```

每个实例都绑定用户启用它的当前会话，`context.session` 提供 id、token、title、workspace、busy；有 `session.read` 时还提供最近 8 条文本消息（每条最多 2000 字符）。没有 API 密钥、供应商凭据或完整系统提示词。token 是本次会话实例的标识；不要把它当作长期会话 ID。主会话新获得 id 时启用设置会随之迁移。

- `context.config`：已校验的配置。
- `context.package_dir`：安装包目录，视为只读资源。
- `context.state_dir`：按插件和会话划分的持久状态目录。
- `context.resolve_workspace(relative)`：要求 `workspace.read`，校验解析后的路径处于会话目录内，拒绝目录穿越和指向外部的符号链接。
- `context.send_message(text, steering=False)`：要求 `session.write`，将消息发送到绑定会话，支持 steering。
- `context.attach_file(relative)`：要求 `workspace.read` 和 `session.write`，附加文件到绑定会话。
- `context.preview_file(relative)`：要求 `workspace.read`，在 Umeko 文档预览器中打开文件，替换插件面板。
- `context.notify(message)`：显示简短通知。
- `context.run_executable(name, args, timeout=12, limit=524288)`：要求 `process.execute`，按清单解析程序，不使用 shell 拼接；限制执行时间、输出和进程生命周期。
- `context.cancelled`：关闭或切换时的取消事件。覆盖 `Plugin.close()` 时调用 `super().close()` 并停止线程和监听。

可声明能力：`workspace.read`、`session.read`、`session.write`、`process.execute`、`git.read`、`git.write`。后两项用于 Git 插件自己的操作约束。宿主再次检查会话写入和文件预览事件的权限及会话 token，丢弃旧会话的晚到事件。

可执行文件范例：

```json
{"executables":{"helper":{"windows-x64":"bin/windows-x64/helper.exe","linux-x64":"bin/linux-x64/helper","linux-arm64":"bin/linux-arm64/helper","macos-arm64":"bin/macos-arm64/helper","macos-x64":"bin/macos-x64/helper"},"git":{"system":"git"}}}
```

使用 `context.run_executable("helper", ["--version"])`；返回 `{code, text, truncated}`。系统程序只允许清单中的简单程序名，通过 PATH 查找。原生依赖必须由插件作者按目标平台随包提供，宿主不自动执行 pip 或安装程序。

## QML 页面

页面根项必须声明 `required property var sdk`。宿主异步加载页面，只有当前一个插件页面被呈现。

```qml
import QtQuick
import QtQuick.Controls
Rectangle {
    required property var sdk
    color: sdk.colors.surface
    property string request: ""
    Button {
        text: "发送到会话"
        onClicked: request = sdk.call("greet", {})
    }
    Connections {
        target: sdk
        function onResponse(id, value) {
            if (id !== request) return
            // value = {ok: true, result: {...}} 或 {ok: false, error: "..."}
        }
    }
}
```

`sdk.call(method, arguments)` 立即返回请求 ID，结果通过 `sdk.response(id, value)` 异步送达。`sdk.session` 是当前绑定的会话快照；`sdk.config` 是只读的已校验配置；`sdk.colors` 提供 bg、surface、ink、muted、line、hover、accent、accentBg、danger、dark；`sdk.scale` 为字体比例；`sdk.active` 表示页面当前可交互；`sdk.copyText(text)` 供用户操作复制内容。不要依赖宿主内部 backend、私有 QML 组件或未公开路径。

页面的打开、收起和拖动宽度复用 Umeko 现有 PID 右侧栏。网页、文档、子代理、插件四种模式互斥。切换会话、进入设置、关闭页面、停用、升级、卸载和退出都会撤销页面及其工作进程。无页面插件仅为当前启用的会话运行，不在所有历史会话中常驻。

## 性能与信任边界

- 包最多 128 MiB 解压数据、2048 个 ZIP 条目，拒绝绝对路径、穿越、符号链接、特殊文件、重复路径和大小写冲突。安装前完整校验。
- 每个会话最多启用 8 个插件；页面最多 8 个待完成调用，初始化和调用 20 秒超时，管理操作 30 秒超时。单条 JSONL 返回最多 2 MiB。
- QML 在 UI 线程中执行：使用 ListView、按需加载和后台 Python；不要在 QML 中同步扫描目录或生成巨大模型。独立工作进程使 Python 查询不阻塞聊天，但**不是操作系统权限沙箱**。Python、QML 和原生程序均是用户选择执行的可信本机代码。
- 官方文件树逐层加载，默认每层 1000 项、总缓存 10000 项、可见模型 4000 项、深度 32 层；Git 状态最多 2000 项，读取差异最多 256 KiB，未跟踪文件最多 128 KiB；渲染进一步限制为 48000 字符、1000 行、每行 2000 字符。大型差异关闭高亮，并明确显示截断提示。
- 后台进程和回调不得越过已结束的会话。使用 SDK 管理的进程以获得超时与清理；自行启动的线程、文件监听、进程由插件作者负责停止。

开发时务必使用临时工作目录和假数据测试错误、超时、切换会话、关闭页面、卸载和大文件行为。Git 示例不会联网推送或自动清理工作文件。
