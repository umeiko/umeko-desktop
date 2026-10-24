# Linux fcitx5 输入法：修复与验证

当前两个版本均使用 Qt **6.10.2**；Python 固定 `PySide6-Essentials==6.10.2`。此前文档中“已改用 Qt 6.12”的描述不符合当前依赖，现已更正。

## 根因与固定方案

Qt 输入法插件依赖 Qt 私有 ABI，不能把发行版 Qt 6.8 的插件直接交给应用的 Qt 6.10，也不能仅看到插件文件存在就认为可以加载。旧 Arch 二进制还可能要求比目标发行版更新的 C++ 运行库。自动改用 `ibus` 也不能保证 fcitx5 已启用对应前端。

两个项目现在都从 SHA-256 固定的 fcitx5-qt **5.1.13** 源码编译插件，使用各自应用的 Qt SDK。源码和构建规则见 `native/input-method/`，不修改系统 Qt 或输入法设置。

- `BUILD_ONLY_PLUGIN=ON` 将 DBusAddons 编入插件，不依赖系统 `libFcitx5Qt6DBusAddons`。
- 不启用私有 Qt Wayland workaround，避免额外加载系统旧版 `Qt6WaylandClient`。未指定输入法的 Wayland 会话仍交给 Qt 原生文本输入协议。
- 插件位于应用自己的 `plugins/platforminputcontexts/`；Python 源码开发使用 `build/input-method/plugins/`。启动时先选择应用自己的插件。
- 不再自动把 `fcitx` 改为 `ibus`，也不再通过启动脚本注入旧 `.local/fcitx5-qt6` 库路径。该目录不再是运行依赖。
- 发布包自带插件和许可；打包检查会在移除 SDK/外部库路径后确认 `IME_PLUGIN_READY:1`。插件源码归档中的链接会解引用复制，支持不允许符号链接的 exFAT 工作区。

## 从源码准备

桌面需已运行 fcitx5，并安装中文引擎，例如 `fcitx5-chinese-addons`。构建机还需 `extra-cmake-modules libxkbcommon-dev libxcb1-dev libx11-dev` 和 C++ 编译器。

Python：`bash setup.sh` 自动准备与 PySide 同版的 Qt SDK 并构建插件。已有 SDK 可用 `QT_ROOT=/path/to/Qt/6.10.2/gcc_64 .venv/bin/python scripts/build-input-method.py`。`Start-Umeko.sh` 和直接运行 `main.py` 均使用相同输入法配置。

C++：普通 CMake 构建自动编译并安装插件，SDK 版本与主程序一致，无需单独安装发行版 Qt 输入法插件。

保留应用级覆盖：`UMEKO_QT_IM_MODULE=ibus`、`fcitx` 或空值（Qt 平台默认）。用户显式选择始终优先。

## 验证，不能用 offscreen 替代

```bash
# Python 源码：真实 fcitx 上下文、拼音预编辑，再提交“你”到 Qt Quick TextArea。
QT_QPA_PLATFORM=xcb .venv/bin/python tests/linux_ime_smoke.py
# 同一测试也可加载 C++ 构建出的插件。
QT_QPA_PLATFORM=xcb .venv/bin/python tests/linux_ime_smoke.py --plugins ../umeko-desktop-cpp/build/plugins

# 实际应用应显示应用自带插件 loaded library，不能有该插件的 ABI/符号错误。
QT_QPA_PLATFORM=xcb QT_DEBUG_PLUGINS=1 ./Start-Umeko.sh
# C++ 项目中：
QT_QPA_PLATFORM=xcb QT_DEBUG_PLUGINS=1 build/UmekoCpp --resource-root "$PWD" --data-dir "$PWD/build/ime-profile"
```

真实桌面测试通过插件的原始 D-Bus 连接向 fcitx5 发送拼音按键，并检查预编辑和中文提交；不伪造 `QInputMethodEvent`。测试结束恢复此前输入法，不发送模型请求。

`QT_QPA_PLATFORM=offscreen` 不实例化真实桌面的输入上下文，只适合 UI 和包加载检查。它通过不能证明中文能输入。手动验收还应覆盖切换输入法、候选窗位置、长文本、回车确认和密码框。

上游：[Fcitx Qt 插件源码](https://github.com/fcitx/fcitx5-qt)、[Fcitx 5 设置](https://fcitx-im.org/wiki/Setup_Fcitx_5)。升级 Qt 时必须同步重建和复测插件，不能复用旧的二进制。
