# 桌面小宠物

官方内置 Widget，默认启用后台观察，**桌宠显示默认关闭**。在本页打开显示开关即可使用。

每 1–2 秒读取已加载聊天的忙碌、思考、工具执行、等待确认、网络重试和完成状态，任何动作至少保持 3 秒。后台服务不调用模型、不扫描历史，也不把观察结果注入对话。切换聊天或隐藏主窗口后仍继续观察；退出 Umeko 时停止。

- 左键点击：角色回应并触发互动动作。
- 按住拖动：移动桌宠，松手后保存位置。移到其他屏幕也会约束在可见区域。
- 右键：打开 Umeko、进入桌宠设置、选择形象、暂停动作、置顶、重置位置或隐藏。
- 隐藏后释放动画解码器，后台观察继续运行。停用 Widget 则停止观察并隐藏。

在下面导入 WebP / GIF / PNG，或包含多种动作的 ZIP。单段动画会作为所有状态的回退。多状态形象包格式和 Agent 管理方法见包内 `AGENT.md`。自定义形象和偏好保存在用户数据目录 `desktop-plugins/state/desktop-pet/` 与 `desktop-plugins/settings.json`，升级不会覆盖。

八奈见资源是 AI 绘制的原始姿势、眨眼关键帧与周期性二维变形组合，透明 WebP 无限循环。提示词记录在 `assets/yanami/generation.json`。

内置形象包括八奈见与鲸鱼娘，可从“动画形象”或桌宠右键菜单切换，内置项不能删除或被同名导入替换。

鲸鱼娘的六种透明动画复用社区 [dsh-whale-girl-pet](https://github.com/yanzwzz/dsh-whale-girl-pet)，保留 MIT 许可与贡献者署名。原始动画转为 360×360、10 fps 的循环 WebP，无需网络或额外视频组件；只有当前动作参与播放，隐藏后释放解码器。来源版本、校验与动作映射见 `assets/whale-girl/source.json`，许可见 `assets/whale-girl/LICENSE.txt`。开发者可用 `scripts/prepare-whale-pet.py --ffmpeg <ffmpeg路径>` 重新制作资源，应用和常规构建不会自动下载。
