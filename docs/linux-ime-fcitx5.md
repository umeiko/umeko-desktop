# Linux fcitx5 输入法：修复与验证

两个版本均使用 Qt **6.10.2**；Python 固定 `PySide6-Essentials==6.10.2`。

## 根因与固定方案

Qt 输入法插件依赖 Qt 私有 ABI，必须用与应用相同版本的 Qt 编译；发行版 Qt 6.8 的插件无法在应用的 Qt 6.10 中加载。旧 Arch 二进制还可能要求比目标发行版更新的 C++ 运行库。

两个项目都从 SHA-256 固定的 fcitx5-qt **5.1.13** 源码编译插件，使用各自应用的 Qt SDK。源码和构建规则见 `native/input-method/`，系统 Qt 和输入法设置保持原样。

- `BUILD_ONLY_PLUGIN=ON` 将 DBusAddons 编入插件，无需系统 `libFcitx5Qt6DBusAddons`。
- 未启用私有 Qt Wayland workaround，因此只加载应用自带的 Qt Wayland 组件。未指定输入法的 Wayland 会话使用 Qt 原生文本输入协议。
- 插件位于应用自己的 `plugins/platforminputcontexts/`；Python 源码开发使用 `build/input-method/plugins/`。启动时优先选择应用自己的插件。
- 输入法模块保持用户的选择；旧的 `.local/fcitx5-qt6` 目录已不再需要。
- 发布包自带插件和许可；打包检查会在移除 SDK/外部库路径后确认 `IME_PLUGIN_READY:1`。插件源码归档中的链接会解引用复制，因此可在不支持符号链接的 exFAT 工作区中构建。

## 从源码准备

桌面需已运行 fcitx5，并安装中文引擎，例如 `fcitx5-chinese-addons`。构建机还需 `extra-cmake-modules libxkbcommon-dev libxcb1-dev libx11-dev` 和 C++ 编译器。

Python：`bash setup.sh` 自动准备与 PySide 同版的 Qt SDK 并构建插件。已有 SDK 可用 `QT_ROOT=/path/to/Qt/6.10.2/gcc_64 .venv/bin/python scripts/build-input-method.py`。`Start-Umeko.sh` 和直接运行 `main.py` 均使用相同输入法配置。

C++：普通 CMake 构建自动编译并安装插件，SDK 版本与主程序一致，无需另装发行版 Qt 输入法插件。

应用级覆盖：`UMEKO_QT_IM_MODULE=ibus`、`fcitx` 或空值（Qt 平台默认）。用户显式选择始终优先。

## 验证

```bash
# Python 源码：真实 fcitx 上下文、拼音预编辑，再提交“你”到 Qt Quick TextArea。
QT_QPA_PLATFORM=xcb .venv/bin/python tests/linux_ime_smoke.py
# 同一测试也可加载 C++ 构建出的插件。
QT_QPA_PLATFORM=xcb .venv/bin/python tests/linux_ime_smoke.py --plugins ../umeko-desktop-cpp/build/plugins

# 实际应用应显示应用自带插件的 loaded library，且该插件没有 ABI/符号错误。
QT_QPA_PLATFORM=xcb QT_DEBUG_PLUGINS=1 ./Start-Umeko.sh
# C++ 项目中：
QT_QPA_PLATFORM=xcb QT_DEBUG_PLUGINS=1 build/UmekoCpp --resource-root "$PWD" --data-dir "$PWD/build/ime-profile"
```

桌面测试通过插件的原始 D-Bus 连接向 fcitx5 发送真实拼音按键，检查预编辑和中文提交。测试结束后恢复此前的输入法，不发送模型请求。

中文输入要在真实桌面会话中验证；`QT_QPA_PLATFORM=offscreen` 没有桌面输入上下文，只用于 UI 和包加载检查。手动检查时覆盖切换输入法、候选窗位置、长文本、回车确认和密码框。

上游：[Fcitx Qt 插件源码](https://github.com/fcitx/fcitx5-qt)、[Fcitx 5 设置](https://fcitx-im.org/wiki/Setup_Fcitx_5)。升级 Qt 时请同时重建并重新测试插件。
