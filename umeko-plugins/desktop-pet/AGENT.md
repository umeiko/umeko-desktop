# 管理桌面小宠物 / 自定义桌宠动画

官方 Widget ID 为 `desktop-pet`，使用 `umeko_desktop` 的现有 Widget 接口。先 `widgets.docs {"id":"desktop-pet"}`，再 `widgets.call {"id":"desktop-pet","method":"status","arguments":{}}`。调用返回 requestId，使用 `widgets.result` 读取完成结果。无需新增 Pi 工具或修改系统提示词。

## 方法

### 本机提醒与待办

先读取 `widgets.docs {"id":"desktop-pet"}`。调用仍使用 `widgets.call`，取得 requestId 后通过 `widgets.result` 读取完成结果，确认保存成功。不要把调用已受理当作已经保存。

- `listItems {"status":"open"}`：返回 `{items,now,localNow}`；status 可为 open（默认）、completed、all。items 包含完整事项和 overdue，按逾期、未来提醒、无时间待办排序。
- `getItem {"id":"..."}`：返回 `{item,now,localNow}`。
- `createItem {"title":"取快递","notes":"带取件码","dueAt":"2026-11-02T17:00:00+08:00"}`：返回 `{item}`。title 去空白后 1–200 字符，notes 最多 2000 字符；不传 dueAt 创建普通待办。
- `updateItem {"id":"...","dueAt":"2026-11-02T18:00:00+08:00"}`：返回 `{item}`，未传字段不变。也可更新 title、notes；至少修改一项。用 `clearDueAt:true` 清除时间，不能同时传非空 dueAt。原生调用也接受 dueAt:null；公开参数 schema 沿用现有 SDK 支持的单一类型，因此推荐使用 clearDueAt。
- `completeItem {"id":"..."}`：返回 `{item}`，标为已完成并取消未触发提醒；重复完成保持原状态。
- `deleteItem {"id":"..."}`：返回 `{deletedId}`；不存在的 id 返回错误。

修改和删除使用查询结果的 id，不按标题猜测。dueAt 必须是带 Z 或 UTC 偏移的 ISO 8601 时间；计算“两分钟后”等相对时间，先从 status/listItems 获取宿主当前时间。无时区输入会被拒绝，过去时间立即按逾期处理。时间结果规范化为 UTC，本地时区变化不会移动已保存的绝对时刻。

事项包含 id、title、notes、dueAt、completed、createdAt、updatedAt、revision、occurrence、firedOccurrence、processedAt 和 notificationOutcome。只有 title、notes、dueAt 可编辑；处理标记和版本由宿主管理。新普通待办 occurrence=0，此后设置、改变或清除时间都会增加 occurrence。

定时由桌宠后台服务负责，不需要模型等待、持续查询或派全局子智能体。改期、完成和删除取消旧计划。重启和休眠恢复后仅处理尚未处理的 occurrence；已处理不等于已完成。先保存处理标记再显示的顺序避免重复，但崩溃可能使一次气泡未显示，事项仍保留在逾期列表。

`status` 还返回 `{reminders:{openCount,overdueCount,nextDueAt,error},now,localNow}`。通过既有 `configure {"reminderNotificationsEnabled":false}` 控制到期气泡；隐藏桌宠或关闭气泡时抑制该次提示，重新显示不补播。Widget 停用或应用退出则停止调度，启用/启动后恢复。首版不发系统通知，不支持重复周期、稍后提醒或重开已完成项。

### 桌宠与形象

- `status {}`：实际动作、活动计数、形象列表、显示设置、导入中状态与最后导入错误。
- `show {}` / `hide {}`：保存显示偏好。隐藏不停止后台服务。
- `configure {"size":192,"alwaysOnTop":true,"paused":false,"sampleIntervalMs":1500,"minimumStateMs":3000}`：局部更新，立即生效。size 96–320px；观察间隔 1000–2000ms；状态保持 3000–30000ms。`visible` 与 `appearance` 也可配置。
- `appearances {}`：列出可用 id、名称、是否内置。
- `importAppearance {"path":"C:/absolute/path/pet.zip"}`：异步导入本机形象。Widget 请求完成后结果包含新 id；导入不会自动改选、显示或执行任何代码。导入失败保留现有形象。
- `selectAppearance {"id":"my-pet"}`：切换形象，偏好跨重启保存。内置 id 为 `yanami`（八奈见杏菜）和 `komari`（小鞠知花），均不可删除、不可通过导入覆盖。
- `removeAppearance {"id":"my-pet"}`：删除用户形象；当前形象先切回八奈见。不能删除内置资源。
- `interact {"kind":"tap"}`：可选 tap、hover、drag；仍遵守最短状态保持。
- `resetPosition {}`：回到屏幕右下方。

通过 `widgets.enable` 停用/启用服务，`widgets.config` 也可更新配置。该 Widget 是应用常驻服务，没有聊天侧栏页面，不调用 `widgets.open`。用户界面位于“设置 → Agent → 插件管理 → 桌面小宠物”。不改变应用或任务栏图标。

## 制作第三方或自己生成的形象

可直接导入单段透明循环 WebP、GIF 或静态 PNG。需要按活动变化时，把以下 `pet.json` 和动画文件打包为 ZIP；也可导入本机 `pet.json`：

```json
{
  "format": "umeko-pet",
  "version": 1,
  "id": "my-pet",
  "name": "我的桌宠",
  "states": {
    "idle": "idle.webp",
    "thinking": "thinking.webp",
    "working": "working.webp",
    "waiting": "waiting.webp",
    "done": "done.webp",
    "error": "error.webp"
  },
  "dialogue": {
    "tap": ["我在这里。"],
    "hover": ["正在看着任务进展。"],
    "drag": ["换个位置。"]
  }
}
```

只必须提供 idle；其他状态缺省时使用当前形象的 idle。建议所有动作统一透明画布、人物基线与尺寸，使用无限循环的 WebP / GIF。建议 384×576、12–24fps、3–5 秒。每个资源最多 1024px、240 帧、30 秒、32 MiB，ZIP 最多 64 文件且解压后 128 MiB；另有总解码像素上限。只保留清单声明的图像数据，不执行包内脚本、QML 或网页。id 不能与已安装形象重复。

活动观察是确定性后台服务，不是另一个 LLM。动作不会逐 token 切换：所有状态至少持续 3 秒；点击时先给出即时轻摇与台词，动画在保持时间到达后变化。停止/取消任务不会伪装成成功。任务完成动作短暂保持后回到待机。

`dialogue` 可选 `done`、`error` 台词，仅在实际任务结束或失败的状态变化时播报一次；点击互动不会误报任务完成。内置图片元数据的 `contentTop` 用于将气泡贴近可见角色上缘，不在运行时扫描像素。
