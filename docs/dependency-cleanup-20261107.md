# 运行目录依赖精简与验证

日期：2026-11-07。对象为 Windows x64 图片矢量化便携目录。

## 实际删除范围

按 165 个具体目标移除 3,319 个文件，合计 **86,076,112 字节（82.09 MiB）**。运行目录从 **513.66 MiB** 降为 **431.57 MiB**，减少约 **16%**。体积按普通文件内容统计，不沿目录链接重复计数。

| 资源 | 文件数 | 字节数 |
| --- | ---: | ---: |
| Node 旧平铺安装及 `.ignored` 副本 | 1,485 | 23,131,828 |
| 指向旧副本的 9 个 CLI 包装脚本 | 9 | 7,407 |
| 第三方库部分自带测试 | 1,815 | 31,193,659 |
| 8 个独立 Python CLI 启动器 | 8 | 867,058 |
| OpenCV FFmpeg 视频插件 | 1 | 30,876,160 |
| 空 SciPy wheel 安装遗留文件 | 1 | 0 |

Node 旧副本不在当前应用依赖图内；保留的 `.pnpm` 中有 82 个物理包，全部仍可从 Potrace/Sharp 的依赖关系访问。旧 `mime`、`mkdirp`、`pixelmatch` 对应命令入口一并移除，避免留下失效启动器。

第三方测试清单保留了仍被 SciPy 开发数据工具引用的 `scipy/special/tests`。`numpy.testing`、`_testing`、`_testutils` 等运行辅助模块，以及保留包的许可证与发行元数据均未裁剪。

## 保留的依赖

`requirements.txt` 的 Pillow、NumPy、SciPy、scikit-learn、scikit-image、OpenCV headless 六项都有生产用途，其传递依赖也保留。Potrace、Sharp 的当前模块树和入口链接、Python/Node 解释器、SR 模型、DiffVG 扩展、增强 `pydeps` 均未变更。

没有修改本机外部增强 Python 环境。Playwright 继续作为测试依赖单独声明。

## 清理后的验证

- 5,185 个保留运行文件逐项核对大小和 SHA256：零缺失、零变更。
- Node 的 82 个包与两个入口解析正常；真实描摹 Worker 的串行/双线程结果完全一致。Sharp 的栅格化、孔洞和透明度检查通过。
- 视频 DLL 已实际移除。OpenCV 导入及 25 项图像操作通过，数组结果与删除前逐项一致。
- 8 项真实超分测试通过：包含 CUDA 推理、CPU 2×/4×、GPU 初始化/显存故障回退及失败报告。
- 浏览器中的五个预设全部实际转换成功；四角裁剪、常见/自定义比例、精修候选生成及三种窗口尺寸检查通过。
- 清理脚本再次预览时目标数为 0；8 个受保护或越界目标均被拒绝。

完整 Python 回归共 177 项，首次整套运行耗时 727.422 秒：168 项通过，8 项因基础 Python 不含 PyTorch 按设计跳过，1 项 HTTP 诊断自检触发客户端 30 秒超时。

这 8 项测试随后对应核对了增强 Python 中的真实执行结果，全部通过；唯一超时项在相同环境、原有 30 秒限制下单独重跑通过（整项测试含多次 HTTP 请求，耗时 36.525 秒）。没有修改应用或放宽测试超时，原始失败记录与复测记录分别保留。本次覆盖了全部 177 个测试项，但首次整套执行并非零错误；未据此声称消除了高负载下的 HTTP 自检耗时波动。

清理期间的回滚备份只用于验证，确认后移除；长期记录仅保留文档与 JSON。

## 重现与使用边界

具体规则在 [`tools/runtime-prune-rules.json`](../tools/runtime-prune-rules.json)，执行方式见 [打包说明](../PACKAGING_README.md#已审查的运行目录精简)。默认只预览，传入 `-Apply` 才删除；文件类型、数量或大小变化时停止，更新依赖后应重新审查。

精简包不提供已排除的第三方测试、独立命令工具和 FFmpeg 视频读写。它继续支持本项目的图片矢量化工作流；若以后加入视频功能，应恢复相应插件并重新测试。原始发行 `RECORD` 保留作来源记录，实际裁剪以本清单为准。

GitHub 本来就不跟踪本机安装目录，因此此提交同步清理脚本、规则和验证说明。源码用户的普通依赖安装行为保持不变。

本次主要回归入口（需要打包说明中的完整本机增强环境和测试依赖）：

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:IMAGEVECTOR_RUN_ENHANCEMENT_TESTS = '1'
.\runtime\python.exe -B -m unittest discover -s tests -p 'test_*.py' -v
$enhancementPython = (Get-Content runtime/enhancement/config.json -Raw | ConvertFrom-Json).python
& $enhancementPython -B tests/test_sr_gpu_fallback.py
.\runtime\node\node.exe tests/verify_workspace_ui.cjs
```
