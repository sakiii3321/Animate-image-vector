# 可选增强功能（源码版）

基础 Potrace 矢量化不依赖此环境。超分辨率与 DiffVG 在独立 Python 子进程中运行，不与主程序的数值库环境混装。

## Real-ESRGAN 超分辨率

1. 创建 Python 3.12 环境。例如在项目根目录执行 `py -3.12 -m venv .venv-enhancement`。
2. 在该环境安装与本机设备适配的 PyTorch，以及 `numpy Pillow scipy scikit-image matplotlib`。GPU 版安装方式见 [PyTorch 官方安装页](https://pytorch.org/get-started/locally/)，CPU 环境也可以运行超分。
3. 从 Real-ESRGAN 官方发布下载 [realesr-animevideov3.pth](https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-animevideov3.pth)，保存为 `runtime/enhancement/sr/realesr-animevideov3.pth`。
4. 校验文件 SHA256：`b8a8376811077954d82ca3fcf476f1ac3da3e8a68a4f4d71363008000a18b75d`。Windows 可运行 `Get-FileHash runtime/enhancement/sr/realesr-animevideov3.pth -Algorithm SHA256`。
5. **仅当尚未配置时**，将 `config.example.json` 复制为同目录的 `config.json`，并设置 `python` 为该环境的解释器路径。相对路径按项目根目录解析。Windows 示例：`.venv-enhancement/Scripts/python.exe`；macOS/Linux 示例：`.venv-enhancement/bin/python`。

`config.json` 必须存在。随后可以用环境变量 `IMAGEVECTOR_ENHANCEMENT_PYTHON` 覆盖配置中的解释器路径。实际配置、环境和模型不会被 Git 跟踪。

运行以下命令检查增强环境（请替换成自己配置的解释器）：

```powershell
.\.venv-enhancement\Scripts\python.exe app/enhance_worker.py --probe
```

界面会分别显示超分与 DiffVG 的可用状态。只配置超分时，DiffVG 不可用是正常状态。超分在可用时优先选择 CUDA；GPU 初始化、显存或推理失败会从原图和 FP32 权重重新用 CPU 运行，并记录实际设备和回退原因。输入或模型文件错误会直接报告，不替换为普通插值。

模型原生为 4 倍；2 倍输出在模型重建后缩小，透明通道单独处理。附带 `sr/srvgg_arch.py` 来自 [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN) 的 SRVGGNetCompact，仅移除了 BasicSR 注册器引用，许可为 BSD-3-Clause。

## DiffVG（独立可选）

本源码仓库不附带 Windows Python 3.12 专用的 `diffvg.pyd` 或其他预编译扩展。需按 [DiffVG 官方仓库](https://github.com/BachiLi/diffvg) 的说明，在上述增强环境安装/编译 `pydiffvg` 和原生扩展，以及其 SVG/CSS 依赖。程序可以从该环境的正常包目录导入它们。

本地便携版此前使用的 DiffVG 源码版本为 `85802a71fbcc72d79cb75716eb4da4392fd09532`，原生扩展仅启用 CPU；这里不提供跨平台构建成功的保证或自动编译脚本。配置后先执行 `--probe`，确认 `diffvg.available` 为 `true`，再启用对应后处理。缺少 DiffVG 不影响基础矢量化和已配置好的超分。
