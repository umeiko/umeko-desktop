# 主题、角色与外观 {#themes-characters}

## 先把文字调舒服 {#make-text-comfortable}

**设置 → 外观** 可切换简体中文和 English，调整 50%–200% 的文字大小。偏好立即保存；聊天内容、项目名和自定义供应商数据不会被翻译。

[![语言与字号设置](/images/appearance-zh.png)](/images/appearance-zh.png)

## 配色和角色分别选择 {#choose-colors-and-characters-separately}

主题负责颜色，主角色负责欢迎图、头像、回复互动、加载与接文件等美术。切换主题不会更改已选角色，也不会改变 Agent 的身份或能力。

「海盐蓝」是配色名称，主题预览不绑定八奈见。在 **外观 → 主题 → 主角色** 中选择内置形象或导入 ZIP 人设包。内置完整主角色包括八奈见、小鞠、温水佳树、马剃天爱星和鲸鱼娘，不能删除或覆盖。

普通子智能体的四个形象槽位可以分别设置。全局子智能体在创建或设置时选择形象；温水和彦是子智能体候选。桌宠使用自己的形象设置。

[![主题卡片和主角色入口](/images/themes-zh.png)](/images/themes-zh.png)

*先选择配色，需要更换人物时点击「主角色」。教程使用的[纯白主题](/examples/pure-white.umeko-theme.json)也可以下载导入。*

[![主角色选择和人设包导入](/images/characters-zh.png)](/images/characters-zh.png)

*内置角色可直接切换，底部可导入 ZIP 或导出人物制作 Skill。*

## 制作和导入主题 {#create-and-import-themes}

从外观设置复制「制作提示词」，或直接对 Agent 说：

> 生成一个纯白、低饱和绿色强调的主题，保证文字清晰，并应用它。保留当前角色。

主题是声明颜色的 JSON，不包含脚本。导入后应用；相同 ID 更新已有主题，删除当前自定义主题后恢复基础配色。

## 制作人设包 {#create-character-packs}

角色窗口可导出人物制作 Skill。把它交给 Agent，准备透明图片、清单与可选台词后打包为 ZIP。导入包复制到用户目录，不依赖原始制作文件夹。

角色包只包含 JSON 和图片；不接受脚本或外部资源路径。详细格式与大小上限见[角色资源规范](https://github.com/umeiko/umeko-desktop/blob/main/docs/characters.md)。
