# 马剃天爱星（Tiara Basori）· 旧版生成记录

当前主界面素材使用 [v2](../tiara-v2/README.md)，此处保留初版提示词、参考与修订来源。

使用内置 image_gen 按官方人物参考制作，统一主界面、子智能体及桌宠风格。官方参考：https://makeine-anime.com/character/ （img_main17.png）。

完整生成提示词见 generation.json。旧版 PNG 已从当前检出移除，文件链接固定到清理前的 Git 提交，清单与校验值见 [archived-assets.json](../../archived-assets.json)。原始官方参考仍保留于 reference。build.py 兼容旧入口并转到 ../tiara-v2/build.py，只构建当前版本，避免旧稿覆盖发行素材。

主界面包含欢迎、三个头像表情、回复、加载、接文件、推及拉九张资源。普通子智能体复用头像和接文件资源，全局子智能体自动进入形象候选列表。独立的六状态桌宠在 art/desktop-pets/tiara-v1，可用其 build.py 重建透明 WebP 动画。

预览：preview.html（从仓库根目录提供 HTTP 服务）。
