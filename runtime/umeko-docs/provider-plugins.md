# Provider 插件：供应商接入、认证与模型

这是 Umeko 的供应商插件，与 [Widget 插件](widget-plugins.md) 分开管理。`umeko_desktop` 的 `plugins.*` 操作管理 Provider 插件；Widget 的安装、启用和方法调用使用 `widgets.*`。

需要自定义登录、签名或非标准传输时，制作 Umeko 供应商插件。插件的 Python 实现由独立 worker 运行，桌面保存账号并通过网关提供模型。通用 SDK 与示例可以公开发布；用户自己的内部认证实现、真实账号、证书和访问记录保留在用户本地的插件中，不放进公共源码或 Release。

先调用 `plugins.resource`，`kind` 分别为 `sdk` 和 `develop`，取得当前安装随附的开发包路径；用 `plugins.exportResource` 可把它复制到指定 `path`。阅读开发包 README、协议、示例和验证器，按当前包里的 API 编写 worker。

典型流程：解压开发包到工作目录 → 根据里面的示例制作 `manifest.json`、Python entrypoint、配置与 schema → 按 SDK 说明运行验证 → 压成 ZIP → 调用：

```json
{"operation":"plugins.import","arguments":{"path":"C:/work/example-provider.zip"}}
{"operation":"plugins.list"}
```

导入成功会安装包并创建账号，返回 `createdProviderIds`。插件及账号会立刻出现在 UI 中；随后 `plugins.login` 传账号 `id` 和与 manifest 一致的 `fields` 对象。该操作是后台工作，返回 `accepted` 和 `jobId` 后，用 `jobs.get` 的 `id` 查询到 `done` 或 `failed`；`done` 之后再选模型。`plugins.list` 中的 `fields` 保留字段名、类型和 secret 标记，秘密字段值不会返回。

- `plugins.addAccount`：从已安装包新增账号，传 `plugin`、`version`。
- `plugins.getConfig`：按账号 `id` 读取脱敏配置。
- `plugins.config`：传账号 `id`、完整 `config` 对象，沿用 schema 验证。
- `plugins.refreshModels`：按账号 `id` 从服务刷新模型。
- `plugins.models`：保存账号可配置模型属性，传 `id`、`models` 数组。
- `plugins.removeAccount`：只删除账号，传 `id`，保留插件包。
- `plugins.uninstall`：卸载指定 `plugin` 和 `version`，对应账号也会移除；其他版本保留。

同一版本号只对应一份内容。更新插件时提升 manifest version，或先卸载对应版本再重装。ZIP 只允许正常的相对路径，如 `./scripts/provider.py`；父级穿越、绝对路径、符号链接、冲突条目等会被拒绝，UI/错误结果会指出条目和规则。

插件通过导入生效，应用安装目录和 Pi 保持不变。Python 运行环境、账号与插件目录的位置以当前实例返回值及 SDK 为准。

## 图片与语音生成能力

生成能力通过 manifest 顶层的 `generationCapabilities` 声明，例如 `["image", "speech"]`；不声明时插件只提供聊天能力。SDK 提供 `generate_image(self, model: str, prompt: str, parameters: dict) -> list[dict]` 和 `generate_speech(self, model: str, text: str, parameters: dict) -> list[dict]`，默认均抛出不支持的 `ProviderError`。

每项结果为 `{data: bytes, mimeType: str}`，由宿主验证、传输并保存文件。图片参数为 `size`、`quality`、`count`（`1`–`10`）、`format`；语音参数为 `voice`、`format`、`speed`。空的可选参数会省略。插件应自行观察 `context.request_cancelled` 与 `context.cancelled`。完整契约见随附 SDK；生成功能的具体实现由各插件自己提供。

配置入口为 **设置 → 账号与供应商 → 多模态模型**，复用现有插件账号的凭据与网络设置。视频生成见 [供应商文档](providers.md) 中的 `video_gen`。
