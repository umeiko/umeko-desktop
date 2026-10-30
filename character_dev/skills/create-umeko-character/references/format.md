# 人设包格式 v1

```json
{
  "format": "umeko-character", "version": 1,
  "id": "my-character", "name": "我的角色",
  "assets": {
    "welcome": "welcome.png",
    "avatarSmile": "smile.png", "avatarWink": "wink.png", "avatarHappy": "happy.png",
    "reply": "reply.png", "loading": "loading.png",
    "catch": "catch.png", "push": "push.png", "pull": "pull.png",
    "background": "welcome.png"
  },
  "dialogue": "dialogue.json"
}
```

`assets`、`dialogue` 均可省略。静态支持 PNG/JPEG/WebP，动画支持 Qt 可解码的 GIF/WebP。背景只用于本来具有角色水印的主题，不会强制改变纯色主题。

| 槽位 | 用途 |
| --- | --- |
| welcome | 欢迎与点击互动，半身图 |
| avatarSmile / avatarWink / avatarHappy | 紧凑头像，聊天中轮换 |
| reply | 回复完成互动 |
| loading | 会话加载 |
| catch | 双手接用户拖入的文件 |
| push / pull | 向右推 / 向右抓住并往回拉，侧栏会按需镜像 |
| background | 主题内的低透明度水印 |
| subagent0–3 / subagentCatch0–3 | 可选子代理头像 / 接文件图 |

`dialogue.json` 只写需要覆盖的字段，例如：

```json
{
  "version": 1,
  "scenes": {
    "welcome": {"greetings":["今天一起做点什么？"],"tap":["我在听。"],"celebration":"完成啦！","dragReturn":"站稳啦。"},
    "reply": {"tap":["结果整理好了。"],"celebration":"全部做完！"},
    "layout": {"tooNarrow":"已经到边界啦。","expandLeft":"往左推。","collapseLeft":"收回来。","expandRight":"往右推。","collapseRight":"拉回来。"},
    "files": {"drop":"交给我吧。"},
    "loading": {"title":"正在翻阅记录……","tips":["做好的文档、代码和网页，可以让我通过 submit 放到侧边供你预览。"]}
  },
  "subagents":[{"name":"伙伴一","tap":["我来检查。"],"celebration":"检查完毕！","fileDrop":"接住啦。"}]
}
```

`subagents` 最多四项，按位置覆盖。包内头像通过 assets 槽位提供，不在 dialogue 中填写外部 avatar/catch 路径。文本数组 1–32 条，每条最多 500 字符；角色名 1–48 字符。

限制：清单和台词各 64 KiB；单图 12 MiB、最多 16,777,216 像素；引用资源共 96 MiB。ZIP 最多 128 条目，解压总量 96 MiB + 128 KiB，只允许 JSON 和图片。根目录或唯一一级目录中包含一个 `manifest.json`。路径必须是正常包内相对路径；禁止绝对路径、反斜杠、冒号、`..`、链接、特殊文件、重复及大小写冲突。
