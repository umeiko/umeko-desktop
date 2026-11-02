# 马剃天爱星桌宠

内置 image_gen 生成六种状态的 3×2 透明原始动画图，提示词、身份参考和来源在 generation.json，原图在 source/。

`python3 art/desktop-pets/tiara-v1/build.py` 使用 Pillow 读取透明行间空隙，分别切出六帧、对齐脚底并缩放，输出 384×576 循环 WebP。只切帧、缩放、编码，不重绘角色或擦除背景。帧时长为 1700、1200、100、100、100、1000 毫秒。

状态：idle、thinking、working、waiting、done、error。显示及状态管理沿用现有桌宠机制，隐藏时释放动画解码器。
