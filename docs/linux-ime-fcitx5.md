# Linux 下 fcitx5 中文输入法不可用：完整排障记录

> 结论：**PySide6 自带 Qt 与系统输入法插件的 ABI 对齐问题**，根治方案是 vendored 同版本插件 + 库搜索路径修正。
> 本文件适用于任何「Qt/PySide 应用在 Linux 下打不了中文」的场景。

## 问题现象

应用输入框只接受英文按键，Ctrl+空格等输入法切换键无效；其他应用（浏览器、Electron 应用）中文输入正常。

## 根因分层

Linux 中文输入链路：`Qt 平台输入上下文插件(.so)` → `DBus` → `fcitx5 守护进程`。本项目上每一层都有坑：

| 层 | 问题 | 典型错误 |
|---|---|---|
| 1 | PySide6 自带 Qt 只打包 ibus/compose 插件，**没有 fcitx5 插件** | 输入法完全无反应，无任何报错 |
| 2 | Debian 系插件按 Qt 6.8 编译，其 DBusAddons 链接 Qt **私有 API**，与运行时 6.10 冲突 | `undefined symbol: _ZTI20QGenericUnixServices, version Qt_6_PRIVATE_API` |
| 3 | 换 Arch 的插件：Arch 已按 **Qt 6.12** 构建，超过运行时 6.10 | `Plugin uses incompatible Qt library (6.12.0)`（Qt 拒绝比运行时新的插件） |
| 4 | 插件 NEEDED 的 `libQt6WaylandClient.so.6` 被动态链接器解析到**系统 6.8 旧库**而非 PySide6 自带的 6.12 库 | 又是第 2 层的私有符号错误 |

关键教训：**Qt6 插件兼容性 = 同主版本 + 构建版本 ≤ 运行时版本 + 整条依赖链的 Qt 库同源**。

## 解决方案（本项目已实施）

1. **Vendored Qt6.12 构建的 fcitx5 插件**：从 Arch Linux `fcitx5-qt` 包提取
   `libfcitx5platforminputcontextplugin.so` 和 `libFcitx5Qt6DBusAddons.so.1`，
   存放于 `.local/fcitx5-qt6/`（已入库，约 1MB），`setup.sh` 自动安装到 PySide6 插件目录。
2. **Qt 版本对齐**：`requirements.txt` 锁定 `PySide6-Essentials==6.12.0`（自带 Qt 6.12.0，与插件精确同版）。
   ⚠️ 升级 PySide6 时必须同步更换插件构建版本。
3. **库搜索路径修正**：`start.sh` 把 PySide6 自带 Qt 库目录置于 `LD_LIBRARY_PATH` 最前，
   插件的 Qt 依赖全部解析到版本一致的库，系统其他 Qt 应用不受影响。

## 验证方法

```bash
# 1. 插件加载过程（失败会打印 cannot load / incompatible）
QT_QPA_PLATFORM=xcb QT_IM_MODULE=fcitx QT_DEBUG_PLUGINS=1 \
  LD_LIBRARY_PATH=<PySide6的Qt/lib>:.local/fcitx5-qt6/lib \
  ./.venv/bin/python -c "from PySide6.QtWidgets import QApplication,QTextEdit; \
  app=QApplication([]); t=QTextEdit(); t.show(); t.setFocus(); app.exec()"

# 2. fcitx5 侧注册表（应出现 program:python / Umeko，聚焦时 focus:1）
dbus-send --print-reply --dest=org.fcitx.Fcitx5 /controller \
  org.fcitx.Fcitx.Controller1.DebugInfo | grep program:
```

**探针陷阱**：`QT_QPA_PLATFORM=offscreen` 不会实例化输入上下文，用它做探针会得到「零报错」的假阴性——必须用真实 xcb 窗口。

## 维护注意

- `.local/fcitx5-qt6/` 是运行所必需，勿删除
- PySide6 升降级时检查插件 Qt 构建版本是否仍 ≤ 运行时版本；不满足时重新从 Arch 拉对应构建
- 用户侧仅需装好 fcitx5（`fcitx5` + 中文引擎如 `fcitx5-chinese-addons`），无其他配置

## 相关文件

- `.local/fcitx5-qt6/` — vendored 插件与 DBusAddons 库
- `setup.sh` 第 5 步 — 插件安装逻辑
- `start.sh` — LD_LIBRARY_PATH 注入逻辑
