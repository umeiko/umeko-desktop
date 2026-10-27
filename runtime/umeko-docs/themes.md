# 主题制作与加载

Umeko 主题是 JSON 配色文件，不是 Pi 终端主题或可执行扩展。先用 `themes.list` 查询已有主题；内置 ID 为 `light`、`dark`、`yanami`。可以用 `themes.prompt` 按需取得随应用附带的完整制作提示词。

文件示例：

```json
{
  "format":"umeko-theme","version":1,
  "id":"moonlight","name":"月色","base":"dark",
  "colors":{
    "bg":"#171A24","sidebar":"#1C2030","surface":"#252A3B",
    "ink":"#EDF0FF","muted":"#A6B0CF","accent":"#9CAFFF",
    "accentBg":"#343E64","button":"#718BDD","buttonText":"#FFFFFF"
  }
}
```

`id` 仅含小写字母、数字、短横线，1–48 位；`name` 1–48 字符。`base` 为 light/dark/yanami，用它继承未指定颜色和装饰。颜色都为 `#RRGGBB`。完整可覆盖名：`bg`、`sidebar`、`surface`、`userBubble`、`hover`、`line`、`ink`、`muted`、`accent`、`accentBg`、`selectionBg`、`selectionText`、`button`、`buttonText`、`danger`。不要添加 JS、HTML、CSS、远程图片或任意未知字段。

写入本地 `.json` 文件，最多 64 KiB，然后：

```json
{"operation":"themes.import","arguments":{"path":"C:/work/moonlight.json"}}
```

导入会验证、保存并直接应用，主题选项实时出现。重复导入同一 id 更新主题，最多保存 32 个。自定义主题在选择/删除操作中的 ID 是 `custom:moonlight`。

`themes.select` 传 `id` 立即切换；`themes.remove` 传自定义 `id` 移除。确保文字、按钮、选中区域与背景有足够对比，不要只检查主题卡片的缩略图。
