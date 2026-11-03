# 能力与运行依赖

设置 → Agent → 能力与运行依赖。UI 与 `umeko_desktop` 共用同一检测服务。
第一版只检查当前机器的基础运行条件；不检查远程 MCP、账号授权、网络连通、OCR、字体或生成质量。
Skill 已发现不等于工作流可用。本地结果也不能代表 SSH、容器或远程服务环境。

任务开始前调用 `{"operation":"capabilities.get"}`。没有结果、过期或环境变化时，
启动后台检测并立即返回 `snapshot.state: checking`；稍后再次查询。
只有 `state: ready` 且 `stale: false` 才能使用检测结论。
用 `{"operation":"capabilities.refresh"}` 强制复查；同一环境已有检测时合并请求。
两项操作均不接受参数，不执行用户传来的命令。不得把接收检测请求报告为检测通过。

返回的 `snapshot` 包含执行目录、检测时间、Python 命令、各依赖最低版本/实际版本/路径/原因、
工作流状态、配置引导、远程未检测状态及 `qualityVerified: false`。
Agent 按**调用会话**目录检查；设置按当前会话目录查看，切换会话不会串用旧目录结果。
缓存保留最多八个环境，120 秒失效；手动复查立即生效，PATH 或浏览器缓存配置变化使用独立缓存。
最多两个并行检测，其余有界排队。应用重启后重新检测，不把历史结果当作当前证据。

## 明确的检测范围

| 工作流 | 必需依赖 | 可选检查依赖 |
| --- | --- | --- |
| Office 文件生成 | Python ≥3.10、python-docx ≥1.2.0、python-pptx ≥1.0.2、openpyxl ≥3.1.5 | LibreOffice ≥7、Poppler pdftoppm ≥0.86 |
| PDF 文本与生成 | Python ≥3.10、reportlab ≥4、pdfplumber ≥0.10、pypdf ≥3 | Poppler pdftoppm ≥0.86 |
| Git | Git ≥2.20 | 无 |
| Python Playwright | Python ≥3.10、Playwright ≥1.40、本地 Chromium 文件 | 无 |

- `available`：已声明的基础条件满足，不表示端到端任务或质量验收通过。
- `partial`：基础生成依赖满足，但可选转换/渲染依赖缺失或检测失败。
- `missing`：至少一项必需依赖缺失或低于最低版本；详情保留其他检测失败原因。
- `error`：无法完成必需检查，包括超时、无法启动、导入错误或版本无法识别。

Office 部分可用时可生成文件，但不能报告已做 PDF 转换、页面渲染或公式重算。
PDF 不包含扫描页 OCR。浏览器只检查 Python API、驱动可启动及 Chromium 文件，
不启动页面，不声称浏览器启动、系统动态库或站点登录已经验证。

## 使用和配置任务 Python

优先选择任务目录下 `.umeko-tools/bin/python`（Windows 为 `.umeko-tools/Scripts/python.exe`）；
否则 Windows 查找 `py -3`、`python3`、`python`，其他平台查找 `python3`、`python`。
使用返回的 `pythonCommand` **参数数组**执行工作，不拼接 shell 命令。
不会把打包的 Umeko 程序当作 Python CLI，也不修改它的依赖。
如果任务实际使用另一个解释器，这份结果不适用；先在目标任务环境检查，不宣称依赖齐全。

检测只读取版本、导入已安装模块、查询 Playwright Chromium 路径；每个检查有超时与输出上限，
不安装、联网探测、下载模型或调用付费供应商。Python 用隔离模式与禁写字节码运行，
避免任务目录的同名模块被导入。失败不回显子进程 stderr 或环境变量。

缺失时说明需要什么、可继续完成哪部分、哪些验证尚未进行。
**安装/修复需要用户明确授权**，通过既有工具权限流程进行，检测按钮不提供隐式安装入口。
建议在任务虚拟环境安装 Python 依赖，LibreOffice、Git、Poppler 按操作系统配置；安装完成后复查。

## 扩展检测声明

内置声明位于 `app/runtime_dependencies.py`：`PACKAGES` 声明模块、发行包与最低稳定版本；
`COMMANDS` 声明固定命令候选、只读版本参数与最低版本；`WORKFLOWS` 区分必需与可选依赖。
新增声明应包含缺失/不兼容/超时测试、配置指引及检测范围说明。
第三方 Skills 不自动继承这些结论；未声明的工作流保持未验证，不执行 Skill 自带检测脚本。
