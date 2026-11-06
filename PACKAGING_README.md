# Windows x64 基础便携版与可选增强运行时

本说明描述另行制作的完整便携包。GitHub 仓库仅包含源码、配置模板和依赖清单，不包含下文的便携解释器、已安装依赖或增强二进制。克隆源码后请先按 [README.md](README.md) 安装；历史测试记录不随源码发布。

## 启动
1. 将整个 ZIP 解压到可写文件夹；不要直接在压缩包中运行。
2. 双击 `START_WINDOWS.bat`。它使用随包附带的 `runtime/python.exe` 运行 `app/main.py`。基础矢量化与曲线简化不需要另装 Python、ComfyUI 或下载依赖；超分辨率与 DiffVG 还需要下文所述的可选 Python 3.12 环境。
3. 浏览器界面由本机程序打开。终端窗口请保持打开；使用 Ctrl+C 结束程序。

基础便携版是包含 Python 与 Node.js 运行时的程序目录，并非自行编译的单个 EXE。目标平台为 Windows 10/11 x64；不包含 macOS/Linux/ARM64 原生运行时。当前目录已在 Windows 上运行随包 Python、Potrace 与 Chrome 界面测试；记录见 tests/results-potrace-windows.txt 与 tests/potrace-ui-results.json。随包增强资产并不包含 PyTorch 解释器环境，因此不能将增强功能宣传为解压即用的完全便携组件。

## Potrace 运行组件

- `runtime/node/node.exe`：Node.js 24.19.0；本机已验证，启动无需下载。
- `runtime/potrace/node_modules/`：node-potrace 2.1.8 及 Jimp 等依赖；保留 `.pnpm` 实际安装和项目内相对链接，不依赖外部用户缓存。迁移前留下的旧平铺副本可按下文的已审查清单移除。
- `runtime/Lib/site-packages/`：新增 NumPy、SciPy、scikit-learn、scikit-image、OpenCV headless 及其依赖，适配随包 CPython 3.14 x64。
- `POTRACE_RUNTIME_PROVENANCE.json`：新增 wheel 与 Node 二进制的来源、版本及摘要；`DOWNLOAD_PROVENANCE.json` 是原始下载历史，其中已移除组件的条目不表示当前安装状态。
- 必须完整保留这些目录；基础矢量化与曲线简化不依赖本机 Anaconda，程序不在启动时安装任何组件。
- node-potrace 为 GPL-2.0，许可见 `THIRD_PARTY_NOTICES/POTRACE-LICENSE.txt`，库源码位于运行目录内；Node 及所含组件许可见 `THIRD_PARTY_NOTICES/NODE-LICENSE.txt`。其他新增库的许可保存在各自 dist-info / 包目录中。

## 可选超分辨率与 DiffVG 运行时

新增插画分层方案使用 `runtime/potrace/node_modules/sharp` 0.35.5，安装时已锁定版本。完整保留此目录的 pnpm 包结构和相对链接；不是对用户缓存路径的引用。`runtime/potrace/illustration-renderer-provenance.json` 记录锁文件、npm 完整性摘要、原生库摘要与许可证位置。Sharp 为 Apache-2.0，所含原生图像库还包含 LGPL 等许可；打包时须保留随包许可。边缘清理不需要 SVG 栅格化器，平涂/渐变分层依赖它进行实际重构误差检查。程序运行时不自动安装或下载组件。

- `runtime/enhancement/` 包含 Real-ESRGAN AnimeVideo-v3 权重、网络代码、CPU DiffVG 扩展、Python 包及许可。`provenance.json` 记录来源、版本与主要资产 SHA-256；`README.txt` 说明运行条件。历史来源记录中的体积不代表当前目录大小。
- 增强子进程使用 `runtime/enhancement/config.json` 的 `python`，支持绝对路径或相对程序根目录的路径；环境变量 `IMAGEVECTOR_ENHANCEMENT_PYTHON` 优先。本机配置不收入源码仓库；新环境先复制 `config.example.json` 并按 `SOURCE_SETUP.md` 配置。外部 Python 环境没有收入发布目录时，配置标记为 `portable: false`。
- 另一台电脑需要自行准备兼容的 Windows x64 Python 3.12 环境，安装 PyTorch、NumPy、Pillow、SciPy、scikit-image、matplotlib，再配置解释器路径。已验证环境为 Python 3.12.12 / PyTorch 2.10.0+cu130；随包 DiffVG 原生扩展绑定 Python 3.12，不能放入基础版 Python 3.14 运行时使用。Anaconda 不是必需条件，兼容环境即可。
- SR 可选 2x / 4x。模型原生 4x，2x 使用模型结果再缩小；透明通道单独重采样。SR 根据 CUDA 可用性选择 GPU 或 CPU；随包 DiffVG 为 CPU 版本。高分辨率补充优化也使用 DiffVG，只有开启 SR 后才能选择。
- 能力探测会实际加载模型并导入 DiffVG；缺少解释器或依赖时会说明原因。程序不自动下载、不静默替换成普通插值，也不会自动修改系统 Python 环境。

## 发布目录与检查

本目录没有 PyInstaller spec 或生成发布包的构建脚本，现有交付方式为完整程序目录 ZIP。新增模块按普通 `.py` 文件加载，不需要添加 PyInstaller hidden imports。发布时按以下目录边界收集文件，避免沿用只列出旧模块的手工清单：

1. 完整收集 `app/`（包括 UI 静态文件、`pipeline.py`、`vector_geometry.py`、`enhancement_runtime.py`、`enhance_worker.py`、`enhance_sr.py`、`enhance_optimize.py`）。
2. 收集经过验证的 `runtime/`，包括 `runtime/enhancement/` 的模型、原生扩展、`pydeps/`、各级许可证、配置和来源清单。不能只收集 `.py` 文件，也不能删掉 `.pth`、`.pyd` 或保留依赖包的元数据/许可证。仅下文的已审查附带资源可用清理脚本排除。
3. 保留启动脚本、说明文档、`requirements.txt`、`examples/`、`THIRD_PARTY_NOTICES/` 及根目录的来源清单。发布验证包还应包含 `tests/`，以及几何性能回归使用的 `experiments/performance_geometry_baseline.py`。`outputs/`、`.diagnostic-temp/` 和 `__pycache__/` 不属于运行必需内容；其余实验目录与本机增强 Python 环境无需复制。浏览器测试另需 Playwright、Chrome；依赖配置与现有便携版测试限制见 `tests/README.md`，这些工具不属于软件运行依赖。
4. 在解压后的程序根目录运行 `runtime\python.exe app\main.py --self-test` 检查基础版。增强环境配置好后，运行 `runtime\python.exe tests\test_enhancement_runtime.py`，确认真实 2x/4x 推理测试通过且没有因缺少可选环境而跳过。界面能力状态与测试中的错误原因可用于排查路径或依赖问题。

仅复制上述目录会包含新增增强代码与资产，但不会使外部 Python 环境随包迁移。发布说明应保留这一限制；只有另外准备并验证可迁移的兼容环境后，才能更改 `portable` 标记。

## 已审查的运行目录精简

`tools/runtime-prune-rules.json` 记录当前 Windows 便携版可排除的具体资源，`tools/prune_runtime.ps1` 默认只预览。请从项目根目录使用 PowerShell 执行：

```powershell
.\tools\prune_runtime.ps1
.\tools\prune_runtime.ps1 -Apply
```

清单移除的是旧 Node 重复安装及其遗留 CLI、第三方库的部分自带测试与独立命令启动器、当前图片应用不使用的 OpenCV FFmpeg 视频插件，以及一个空安装遗留文件。六项 Python 直接依赖、当前 Potrace/Jimp/Sharp 模块树、模型及增强包保持完整；`numpy.testing` 等运行辅助模块、仍被开发工具引用的 `scipy/special/tests` 也保留。

脚本逐项检查路径边界、链接、类型、文件数和字节数，拒绝内容已变化的目标；保留 `.pnpm` 和 `potrace`/`sharp` 入口链接。已经清理的目标会跳过，执行结果写入 `outputs/runtime-prune/report.json`。更新依赖版本后需重新审查清单，不能把它当作任意 Python 环境的通用清理工具。

精简后的包面向本应用，不再提供被移除的第三方测试套件、独立 CLI 或 OpenCV FFmpeg 视频功能。原始包的 `RECORD`/来源清单仍记录上游发行内容，实际排除项以清理报告为准；重新安装依赖会恢复对应文件。

本次实际删除范围与验证结果见 [依赖精简验证记录](docs/dependency-cleanup-20261107.md)。本机安装目录被 Git 忽略，GitHub 同步的是精简规则、执行脚本与验证记录。

## 依赖及来源

当前程序只支持 Potrace。VTracer 的 Python 依赖、调用入口和运行选项已移除，不应在新发布包中重新加入。原始来源清单和早期测试记录保留作历史凭据，不用它们推断当前已安装依赖。

- CPython 3.14.10 Windows x64 embeddable package，来自 python.org 官方发布。
- Pillow 11.3.0，来自 PyPI 的 `cp314-cp314-win_amd64` wheel。
- `DOWNLOAD_PROVENANCE.json` 记录原始下载 URL、大小、SHA-256 和核验方式。
- Python ZIP 的 SHA-256 与官方发行页及官方 Sigstore 文件中的摘要一致；未声称完成 Sigstore 签名/证书链验证。
- wheel 的 SHA-256 与 PyPI 版本 JSON 记录一致。所有归档检查 CRC 和路径安全后解压，未重命名平台标签。
- 无启动时 pip/install/download；离线启动不要求互联网。应用本身的浏览器与本地 HTTP 服务仍需工作。

## 源码备用方式（需要自行安装 Python 和联网安装依赖）
推荐 Python 3.12–3.14；目标平台须有 `requirements.txt` 中图像处理与数值计算包的兼容 wheel，并需要 Node.js 20.9.0 或更新版本（建议 24 系列）。当前只安装 Potrace 及其分层渲染依赖。

Windows PowerShell:
```
py -3.14 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
npx --yes pnpm@11.25.0 --dir runtime/potrace install --frozen-lockfile --ignore-scripts
.\START_SOURCE_WINDOWS.bat
```
macOS/Linux:
```
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npx --yes pnpm@11.25.0 --dir runtime/potrace install --frozen-lockfile --ignore-scripts
sh start_source.sh
```
源码备用方式的安装过程需要网络，不同于 Windows 基础便携版；不会修改 ComfyUI。`requirements.txt` 对应基础程序，安装它不会安装可选增强环境；SR / DiffVG 仍需按上节配置 Python 3.12。

## 第三方许可
完整文本位于 `THIRD_PARTY_NOTICES/`，运行时及 wheel 的原始许可/元数据也保留在 `runtime/`。
Python 使用 PSF 许可及其附带的其他组件条款；Pillow 使用 MIT-CMU，并包含其他编解码组件的许可，详见完整 LICENSE。
本便携包没有包含原 ComfyUI 节点仓库的未授权源码。
