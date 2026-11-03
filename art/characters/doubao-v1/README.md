# 豆包

按用户提供的五张画风与表情参考制作精致的 3D 动画电影质感。发型和服装使用豆包经典的深棕色齐下巴短发、黑色针织上衣与红色围巾，造型参考来自 [App Store 产品页](https://apps.apple.com/cn/app/id6459478672)。完整提示词及原图记录见 `generation.json`。

主界面槽位覆盖欢迎、头像、回复、加载、接文件、推和拉；另有独立的主页半身彩蛋。角色同时可用于主聊天、普通子智能体和全局子智能体；不修改用户当前选择。桌宠六状态和全身彩蛋见 `art/desktop-pets/doubao-v1`。

选择窗口、聊天头像和子智能体头像统一使用 `picker.png`：保留经典蓝色圆底与大头构图，五官使用用户选定的精致版本，外侧白底为透明。此封面通过可选的 `assets.picker` 槽位声明，三个头像槽位复用同一张图片。

回复底部独立使用 `reply.png`，按用户最新参考制作盘发、珍珠花饰与浅蓝衣领的头肩图。肩部下缘自然收拢，带柔和透明过渡，不使用平直截边；原图见 [source/reply-shoulders.png](source/reply-shoulders.png)，参考图与完整提示词记录在 `generation.json` 的 `reply` 条目中。

底部图案使用 72px 的显示区域，考虑透明留白后，角色轮廓比 40px 聊天头像稍大，并沿用界面缩放比例。

运行 `python build.py` 从保留的原图重建发行 PNG。脚本只等比缩放、添加透明边距与编码，保留原图的透明通道，不重绘角色。

互动台词使用用户指定的共情、排比和郑重承诺口吻；完整中文台词见 `app/icons/characters/doubao/dialogue.json`，对应英文保存在 `translations.json` 并接入应用翻译表。`preview.html` 同时展示主界面美术、主页彩蛋和七种二维桌宠动画。

完整生成提示词：[主角色与头像](generation.json)、[二维桌宠动作](../../desktop-pets/doubao-v1/generation.json)。均使用内置 image_gen 生成。
