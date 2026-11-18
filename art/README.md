# 美术源文件与历史稿

这里保留当前发行素材的制作源文件、参考图、许可、提示词和生成记录。运行时只读取 `app/icons/` 与 `umeko-plugins/desktop-pet/assets/`；本次清理不改动这些资源。

- 当前主角色源稿：`characters/doubao-v1`、`characters/whale-girl-v1`、`characters/tiara-v2`；温水和彦使用 `characters/kazuhiko-v2`。
- 当前主页彩蛋：`rare-scenes/v5/generation.json` 选定的五张原稿，以及豆包主角色目录中的独立彩蛋。v6 保留天爱星脸部修订原稿，v7 的重复输出引用 v5 的同一份手部修订原稿。
- 桌宠源稿和所有仍使用的动画、参考及许可保留在 `desktop-pets/`。目录中的 `v1` 不代表废弃，不能按版本号批量删除。
- 子智能体源稿、预览 HTML、生成与授权记录保留；预览截图等可再生成的导出不重复保存。

被新版替代的旧图与完全相同的副本列在 [archived-assets.json](archived-assets.json)。清单记录清理前的仓库、固定提交、Git blob、SHA-256、字节数及可复用的本地原稿。历史生成记录里的旧图链接指向该固定提交，提示词保持原样；重复图的引用改用仍在本地的唯一原稿。不要把归档链接作为当前生成脚本的输入。

需要找回旧稿时，从清单的 `revision` 与 `files[].path` 读取原始内容：

```sh
git show <revision>:<path> > /tmp/restored-art.png
sha256sum /tmp/restored-art.png
```

浅克隆需要先获取清单中的提交。这里只缩减当前检出与源码归档体积，不重写 Git 历史，也不承诺等量减少完整 clone 的大小。

以后保留选定原稿及必要参考，避免提交被替代的试稿、相同图片的多个副本和一次性的预览导出。清理前必须核对生成脚本、预览、元数据和许可引用。
