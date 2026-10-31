# 天爱星桌宠 v2

在官方眉形修正基础上改善腿身比例。六种动作全部从同一条腿部比例已确认的待机母版派生；完整内置 image_gen 提示词见 generation.json。

python3 build.py 仅裁切、对齐、缩放和编码已有透明图。输出为 384×576、6 帧透明循环 WebP。随后运行 art/rare-scenes/v1/build.py 恢复稀有待机场景声明。
