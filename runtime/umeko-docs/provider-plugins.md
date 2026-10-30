# Provider 插件：供应商接入、认证与模型

这是 Umeko 的供应商插件，与 [Widget 插件](widget-plugins.md) 分开管理。`umeko_desktop` 的 `plugins.*` 操作只管理 Provider 插件，不负责 Widget 的安装、启用或方法调用。

自定义登录、签名、非标准传输使用 Umeko 供应商插件，不是 Pi 扩展。插件的 Python 实现由独立 worker 运行，桌面保存账号并通过网关提供模型。通用 SDK 与示例可以发布；用户自己提供的内部认证实现、真实账号、证书和访问记录不应混入公共源码或 Release。

先调用 `plugins.resource`，`kind` 分别为 `sdk` 和 `develop`，取得当前安装随附的开发包路径；用 `plugins.exportResource` 可把它复制到指定 `path`。阅读开发包 README、协议、示例和验证器，以当前包里的 API 为准，不要猜测 worker 接口。

典型流程：解压开发包到工作目录 → 根据里面的示例制作 `manifest.json`、Python entrypoint、配置与 schema → 按 SDK 说明运行验证 → 压成 ZIP → 调用：

```json
{"operation":"plugins.import","arguments":{"path":"C:/work/example-provider.zip"}}
{"operation":"plugins.list"}
```

导入成功会安装包并创建账号，返回 `createdProviderIds`。插件及账号会立刻出现在 UI 中；随后 `plugins.login` 传账号 `id` 和与 manifest 一致的 `fields` 对象。该操作是后台工作，返回 `accepted` 和 `jobId` 后，用 `jobs.get` 的 `id` 查询至 `done` 或 `failed`，确认成功后才能选模型。`plugins.list` 中的 `fields` 保留字段名、类型和 secret 标记，秘密字段值不会返回。

- `plugins.addAccount`：从已安装包新增账号，传 `plugin`、`version`。
- `plugins.getConfig`：按账号 `id` 读取脱敏配置。
- `plugins.config`：传账号 `id`、完整 `config` 对象，沿用 schema 验证。
- `plugins.refreshModels`：按账号 `id` 从服务刷新模型。
- `plugins.models`：保存账号可配置模型属性，传 `id`、`models` 数组。
- `plugins.removeAccount`：只删除账号，传 `id`，保留插件包。
- `plugins.uninstall`：卸载指定 `plugin` 和 `version`，对应账号也会移除；其他版本保留。

同一个已安装版本不能默默替换不同内容。开发时提升 manifest version，或明确卸载对应版本后重装。ZIP 只允许正常安全相对路径，`./scripts/provider.py` 可以；父级穿越、绝对路径、符号链接、冲突条目等会被拒绝，UI/错误结果会指出条目和规则。

不要为了让插件生效而把源码复制进应用安装目录或修改 Pi。Python 运行环境、账号与插件目录的位置以当前实例返回值及 SDK 为准。内网登录细节保持在用户自己创建的本地插件中。
