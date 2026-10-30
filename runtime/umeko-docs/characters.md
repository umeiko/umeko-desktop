# 动画形象、角色美术资源与第三方形象包

这里配置的是 Umeko 桌面中的欢迎形象、聊天头像、回复完成互动、接文件、加载、推拉和背景美术。它独立于主题配色，不改变 Agent 的身份或系统提示词。用户可在「设置 → 外观 → 主题 → 主角色」切换或导入 ZIP 人设包，也可以让 Agent 通过 `config_umeko` 应用。此处可导出角色制作 Skill，供 Agent 制作新的人设包。

## 查询和切换

先调用 `{"operation":"characters.list"}` 查询当前可用 ID；`characters.get` 返回正在使用的资源及台词。内置 `yanami` 为八奈见，`komari` 为小鞠知花，`kaju` 为温水佳树，三者都是不可删除或覆盖的内置完整角色。切换示例：

```json
{"operation":"characters.select","arguments":{"id":"komari"}}
```

切换立即应用，不需要重启。恢复默认使用 `id: "yanami"`。没有配置、选中包已不存在、某个资源未提供或失效时，对应位置自动回退八奈见。切换配色主题保留所选形象。

## 场景台词与四个子代理的 JSON 配置

`characters.config` 返回当前完整的 `config` 模板、用户自定义的 `overrides`，以及当前用户目录中的 `character-config.json` 路径。该 JSON 持久化用户覆盖项；默认场景和四个角色定义在应用随附的 `app/character-defaults.json`，小鞠自己的各场景台词在其资源包的 `dialogue.json`。修改由工具即时应用，无需改写程序、提示词或新增 UI 控件。

`config.scenes` 的可配置项目：

| 场景 | 字段 |
| --- | --- |
| 欢迎 | `welcome.greetings`（随机欢迎语）、`welcome.tap`（点击口头禅）、`welcome.celebration`（连续点击/长按）、`welcome.dragReturn`（拖动松开） |
| 回复完成 | `reply.tap`、`reply.celebration` |
| 推拉与边界 | `layout.tooNarrow`、`expandLeft`、`collapseLeft`、`expandRight`、`collapseRight` |
| 拖入文件 | `files.drop` |
| 打开聊天 | `loading.title`、`loading.tips`（随机提示，不连续重复） |

`config.subagents` 按现有四个角色位置排列。每一项均可配置 `name`、`avatar`、`catch`、`tap`、`celebration`、`fileDrop`。名称更新已有任务的显示标签，重复角色仍自动附加序号；不改变子代理任务或身份提示词。`tap` 为口头禅数组，`celebration` 是连续点击/长按台词。`avatar` 与 `catch` 可传本地图片/GIF 的绝对路径或 file URL，主机验证后复制进用户目录，后续不依赖原文件。空字符串恢复该位置的默认美术。

例如，在当前覆盖项基础上更改几个场景和第一个子代理：

```json
{
  "operation":"characters.configure",
  "arguments":{"config":{
    "version":1,
    "scenes":{"reply":{"tap":["我在这里。"],"celebration":"做完啦！"},"layout":{"tooNarrow":"已经到边界啦。"}},
    "subagents":[{"name":"检查员","avatar":"C:/work/portrait.png","catch":"C:/work/catch.gif","tap":["检查完毕。"],"celebration":"全部通过！"}]
  }}
}
```

先取 `overrides`，保留用户其他覆盖项后再提交。`characters.configure` **替换**整个覆盖配置，不是向已有文件追加；只需修改部分字段时，先在本地合并。传 `config: {}` 清除所有用户覆盖，恢复当前形象包的默认台词及四个默认子代理。数组按位置定义角色；可用空对象跳过前面的角色。每个文本数组支持 1–32 条，每条最多 500 字符，角色名称最多 48 字符。配置用于界面表现，不写入模型常驻提示词。

## 第三方或自己生成的形象

准备一个目录，包含 `manifest.json` 和图片。使用透明背景、完整轮廓与留白，建议每张 256–1024px；支持 PNG/JPEG/静态 WebP，以及 Qt 图片插件可解码的 GIF/动画 WebP。静态图片会继续使用原有的点击、弹性、推拉和加载动作；动画文件由界面在可见时播放，不把所有帧常驻缓存。不要把视频、HTML、脚本、网络 URL 或模型代码放进形象包。

```json
{
  "format": "umeko-character", "version": 1,
  "id": "my-character", "name": "我的形象",
  "assets": {
    "welcome": "welcome.png",
    "avatarSmile": "smile.png", "avatarWink": "wink.png", "avatarHappy": "happy.png",
    "reply": "reply.png", "loading": "loading.gif",
    "catch": "catch.png", "push": "push.png", "pull": "pull.png",
    "background": "welcome.png"
  },
  "dialogue": "dialogue.json"
}
```

`assets`、`dialogue` 和它们的每个项目都可以省略；省略的美术使用八奈见，省略的台词使用原有默认值。`dialogue.json` 使用上面 `config` 对象的相同结构，可以只提供要改的场景、角色名称和口头禅；包内角色图片统一放在 `assets.subagent0`–`subagent3`（头像与完成图）、`assets.subagentCatch0`–`subagentCatch3`（接文件），不要在包内台词 JSON 引用外部头像文件。`background` 只在当前主题原本展示人物水印的区域出现，不给纯色主题强行增加背景。主形象不会自动覆盖子代理各自的角色。

资源路径相对于清单目录，只能指向包内实际文件，不能是绝对路径、`..`、符号链接或远程地址。清单、台词 JSON 各最多 64 KiB，每张图片最多 12 MiB、1600 万像素，引用总量最多 96 MiB。`id` 为 1–48 位小写字母/数字/短横线，不能覆盖内置 `yanami`/`komari`/`kaju`；名称最多 48 字符。

将清单与图片放在 ZIP 根目录或唯一的一级目录中，导入 ZIP 或清单后直接应用。ZIP 最多 128 条目、解压总量 96 MiB + 128 KiB；只允许 JSON 和图片，拒绝符号链接、重复或冲突路径。

导入示例（path 也可以是 ZIP）：

```json
{"operation":"characters.import","arguments":{"path":"C:/work/my-character/manifest.json"}}
```

Umeko 验证并将引用图片复制到当前用户数据目录的 `characters/<id>/`，升级软件和移动原始制作目录都不会使已导入资源丢失。同 ID 再次导入会更新资源。用 `characters.remove` 和自定义 `id` 删除；删除当前包后恢复默认。不要直接编辑应用安装目录或 settings.json。

制作后请实际查看欢迎图、长回复结尾、附件拖入、加载和两侧推拉，小尺寸下应能识别角色。先确认用户希望更换形象，再调用选择/导入；仅生成配色主题时保留当前形象。
