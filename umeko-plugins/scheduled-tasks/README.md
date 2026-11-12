# 定时任务 / Scheduled tasks

从右下角 Widget 菜单启用并打开「定时任务」。每次触发时使用一个新的 Pi 会话，独立于当前聊天。关闭面板后仍会调度，退出 Umeko 后暂停。错过或中断的运行可在历史中看到，使用「立即运行」手动补跑。

Enable and open Scheduled Tasks from the Widget menu. Each occurrence starts a fresh Pi conversation. Closing the panel leaves schedules active while Umeko is running. Review missed or interrupted runs in history and use Run now to retry.

## 会话配置 / Session profiles

在 Umeko 退出后，在隔离或常用配置目录的 `settings.json` 顶层添加 `pluginSessionProfiles`。将示例替换为已存在的绝对目录、模型别名和 Provider ID。Widget 只选择已批准的会话配置。权限和审批由桌面宿主处理。

With Umeko closed, add `pluginSessionProfiles` at the top level of the profile's `settings.json`. Substitute an existing absolute project directory, model alias and Provider ID. The Widget selects a desktop-approved profile. The desktop host enforces the existing permission and approval policy.

```json
{
  "pluginSessionProfiles": {
    "scheduled-tasks": {
      "reports": {
        "workspace": "/path/to/project",
        "model": "report-model",
        "provider": "provider-id",
        "tools": ["read"],
        "permissionMode": "ask"
      }
    }
  }
}
```

When a local time falls in a daylight-saving gap, it moves forward by the offset change. During a repeated local hour, only the earlier occurrence is used.
