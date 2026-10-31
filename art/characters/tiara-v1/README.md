# 马剃天爱星（Tiara Basori）

使用内置 image_gen 按官方人物参考制作，统一主界面、子智能体及桌宠风格。官方参考：https://makeine-anime.com/character/ （img_main17.png）。

完整生成提示词与源文件见 generation.json；透明 PNG 原稿保留于本目录。build.py 仅等比缩放为 768 px 并压缩 PNG，输出至 app/icons/characters/tiara，不重新绘画或替换透明通道。

主界面包含欢迎、三个头像表情、回复、加载、接文件、推及拉九张资源。普通子智能体复用头像和接文件资源，全局子智能体自动进入形象候选列表。独立的六状态桌宠在 art/desktop-pets/tiara-v1，可用其 build.py 重建透明 WebP 动画。

预览：preview.html（从仓库根目录提供 HTTP 服务）。
