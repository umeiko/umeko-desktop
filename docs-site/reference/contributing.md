# 完善这份文档 {#contribute-to-the-docs}

每页底部的「在 GitHub 上完善此页」可直接打开对应 Markdown。发现错误时也可以[提交 Issue](https://github.com/umeiko/umeko-desktop/issues/new)，注明页面、版本和正确行为。

## 内容约定 {#writing-conventions}

- 文档跟随 main。尚未发布的能力、两个版本的差异请明确标注。
- 菜单名以当前界面为准。先实际操作一遍再写教程，只写已经可用的功能。
- 截图使用演示数据，内容里只出现虚构的账号、Key、路径和聊天。
- 面向使用者的页面优先说明目标与步骤；精确接口链接到源码中的 SDK 规范。
- 修改中文页面时同步 `en/` 同路径页面。新增语言应补齐同一套页面和导航，避免语言切换落到不存在的页面。
- 中英文标题使用相同的 `{#anchor}` 标识，切换语言后会停在同一节。修改标题文字时保留原标识。

## 本地构建 {#build-locally}

```bash
cd docs-site
npm ci
npm run dev
```

正式验证运行 `npm run build`，会构建静态页面，并检查中英文页面对齐、站内目标、锚点与本地资源。发布预览使用 `npm run preview`，访问终端显示的本地地址。

站点使用 VitePress 本地全文搜索，字体和脚本都从本站加载。站点依赖与桌面运行时分开管理。部署和维护细节见[站点 README](https://github.com/umeiko/umeko-desktop/blob/main/docs-site/README.md)。
