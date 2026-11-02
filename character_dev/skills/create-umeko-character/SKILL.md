---
name: create-umeko-character
description: 为 Umeko Desktop 制作可导入的 ZIP 人设包，包括角色美术、互动台词和 manifest。用于新增或修改桌面角色，不用于模型身份或系统提示词配置。
---

# 制作 Umeko 角色

先确定用户希望的人物、画风和参考图。在可用的图像生成工具中保持同一角色的一致性；没有图像工具时使用用户提供的美术，不用代码画占位图冒充成品。按需读取 [references/format.md](references/format.md) 查看槽位、台词结构与限制。

- 产物是数据包，不包含可执行脚本、HTML 或外部网址。人物外观独立于主题；不要修改模型身份、系统提示词或供应商配置。
- 美术优先透明背景，完整头发和手部，保留适量透明边距。头像在 40px 下应可辨认；欢迎、接文件、推拉图保持一致的构图比例。推荐 256–1024px。可复用同一文件到多个槽位。
- 缺省槽位会回退八奈见。制作完整角色时补齐欢迎、三个头像、回复、加载、接文件和推拉动作；不要把加载文字烘焙到图里。静态图会沿用软件原有动画。
- `id` 使用新的小写英文 ID；`yanami`、`komari`、`kaju`、`tiara`、`whale-girl`、`kazuhiko` 是受保护的内置角色，不可覆盖或删除。
- 建议为角色写简短的场景台词。加载 tips 保留实用的 Umeko 操作知识，避免编造软件能力。台词只影响界面表现。

将 `manifest.json`、可选的 `dialogue.json` 与引用图片放在同一目录。使用 `scripts/package.py <目录> <输出.zip>` 验证基本结构并打包；最终导入仍由应用验证图片解码和路径。ZIP 根目录直接放清单与资源，不要再套多层文件夹。

使用 `submit_to_chatbox` 等当前环境可用的产物展示入口给用户审阅图片和 ZIP。用户要求应用角色时，通过 `config_umeko`：

```json
{"operation":"characters.import","arguments":{"path":"/absolute/path/my-character.zip"}}
```

导入会立即应用，同 ID 的自定义角色会被替换；保留原 ZIP 便于恢复。也可让用户在「设置 → 外观 → 主题 → 主角色 → 导入人设包」导入。切换已有角色先查询 `characters.list`，再调用 `characters.select`。不要改写程序随附的内置资源。
