# 测试依赖与运行条件

从项目根目录安装已有 Node 依赖：

```text
npx --yes pnpm@11.25.0 --dir runtime/potrace install --frozen-lockfile --ignore-scripts
npm --prefix tests install
```

浏览器测试使用 Playwright 1.62.1；版本取自当前验证环境。Sharp 使用应用的 `runtime/potrace/package.json` 已声明版本，不在测试目录重复添加依赖。

`node_test_dependencies.cjs` 按以下顺序解析依赖：调用脚本的本地 Node 模块、`tests/node_modules`、应用的 `runtime/potrace/node_modules`、`IMAGEVECTOR_TEST_NODE_MODULES` 指定目录。最后兼容由 `USERPROFILE` 或 `HOME` 推导的现有 Codex 缓存，正常安装后不依赖该缓存。环境变量应指向 `node_modules` 本身，多目录使用系统路径分隔符（Windows 为分号）。

可先检查依赖能否加载：

```text
node -e "const load=require('./tests/node_test_dependencies.cjs'); load('playwright'); load('sharp'); console.log('Dependencies ready');"
```

## 真实浏览器测试的限制

`verify_*.cjs` 是针对当前 Windows 便携版的回归脚本，不是跨平台 CI 入口。多数脚本会启动项目内的 `runtime/python.exe`，部分还使用 `runtime/node/node.exe`；浏览器路径为 Windows 默认安装位置下的 Google Chrome。只安装 Playwright 或其 Chromium 下载包不会自动满足这些条件。

```text
node tests/verify_local_refine_ui.cjs
node tests/verify_illustration_ui.cjs
```

超分辨率与增强测试还需要对应的本机增强运行时；GPU 相关结果依赖驱动和设备。测试会生成 `outputs/` 报告及 `.diagnostic-temp/` 临时文件，这些产物不应提交到源码仓库。

`verify_workspace_ui.cjs` 的插画截图检查还依赖本地 `test_pic/134948250_p0.png`（2285 × 3753）。原图集及个人评分不随源码发布，缺少该图片时不能直接运行这项完整回归。其他界面测试大多使用脚本生成的小型合成图。

`experiments/illustration_round2/validate_render.cjs` 需要先生成完整盲评包，包含 `data.js`、SVG 和预览图；清理后的只读报告目录无法直接作为其输入。实验脚本及源码单元测试仍保留在各自目录；这里的 npm 安装仅解决 Node 依赖，不会安装 Python 包或恢复已清理的实验媒体。
