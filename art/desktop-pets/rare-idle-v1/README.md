# 桌宠全身彩蛋动画

四只内置桌宠（八奈见、小鞠、天爱星、鲸鱼娘）分别以当前普通待机动画的首帧作为画风、服装、头身比例和站立位置参考。由内置 image_gen 生成各自的六帧动作图，再由 build.py 切片、统一缩放/基线并编码为透明 WebP，不绘制或修改角色像素。

每段动画 6 帧、4.2 秒；人形桌宠仍为 384×576，鲸鱼娘仍为 360×360。普通待机、彩蛋动作在 preview.html 中并排展示。完整提示词、参考和原始生成路径见 generation.json，同名 .prompt.txt 是逐张提示词。

运行 `python3 art/desktop-pets/rare-idle-v1/build.py` 会更新对应桌宠的 idle-rare.webp、pet.json 与 rare-idle.provenance.json。主页半身图由 art/rare-scenes/v5/build.py 单独打包，互不覆盖。

沿用每个完整待机循环 0.005 的抽取概率，隐藏、暂停或繁忙时不抽取；动画循环结束再决定回到普通待机。只显示当前动画，隐藏时释放解码器，不增加模型调用。
