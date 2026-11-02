# 鲸鱼娘 · 主角色美术与台词

本地验收稿，包含主页、三个头像、回复、加载、接文件和推拉侧栏九张透明插画。已接入本地版本的主角色、普通及全局子智能体候选，内置角色不可删除。dialogue.json 使用现有角色包台词格式，仅覆盖主角色场景，不改其他子智能体的名字或台词。

口吻：总以“人”称呼用户，惦记“米”；短句、停顿偏多，衔接略生硬，语气理直气壮。避免流畅长句、过多撒娇语气词和表情符号。涉及操作时仍清楚说出入口或按键。

preview.html 同时展示九张美术、小尺寸头像及按场景分组的台词。稀有彩蛋继续使用用户指定的原句：“人，你给我吃米，人，日后我会放你一马的”。桌宠仍使用自身的全身动画，不使用这些主角色半身图。

美术由内置 image_gen 生成。完整提示词、参考和原始输出位置见 generation.json；同名 .prompt.txt 记录各张提示词。角色外观参考既有鲸鱼娘素材，社区来源与 MIT 许可保存在 reference；应用随附 provenance.json 保留许可全文。打包脚本只做确定性的缩放、透明边距排版和 PNG 编码。

重新打包运行 `python3 art/characters/whale-girl-v1/build.py`，输出 app/icons/characters/whale-girl。主页稀有图由 art/rare-scenes/v5/build.py 单独打包，桌宠彩蛋由 art/desktop-pets/rare-idle-v1/build.py 单独打包。
