# 文件监听服务

这是没有右侧界面的应用级 Widget 示例。导入后在插件管理中启用，应用启动时自动运行；切换聊天和关闭面板不停止进程，停用、升级、卸载和退出应用时停止。

每段聊天可订阅自己工作区中的一个文件。后台线程只检查文件时间和大小，不读取文件内容、不修改文件；发生变化后唤醒原聊天的主 Agent。检测间隔通过 `intervalSeconds` 设置，默认 5 秒。使用完整方法说明见 [AGENT.md](AGENT.md)。

订阅保存在当前应用进程内，重新启动或修改服务配置后需要重新订阅。SDK 的 `state_dir` 为应用级固定目录，开发者可用它保存非秘密服务状态。工作目录发生改变时，旧聊天引用将拒绝投递，需在目标聊天重新订阅。

从 SDK 根目录打包：

```text
python -m umeko_plugin_sdk validate examples/application-service
python -m umeko_plugin_sdk pack examples/application-service file-watch-service.zip
```
