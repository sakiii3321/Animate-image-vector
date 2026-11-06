# Animate Image Vector

面向插画的本地图片转 SVG 工具。使用 Potrace 描摹色块，通过浏览器界面操作，图片处理在本机完成。

## 功能

- 边缘清理、渐变分层、平涂分层与传统 Potrace 四种重构方案。
- 均衡插画、细节优先、轻量简洁、柔和渐变、线稿五种预设，以及高级参数模式。
- 独立裁剪窗口，支持拖动四角、自由比例及 16:9、9:16、4:3、3:4、1:1、自定义比例。
- 分析画面复杂度、清晰度与颜色分布，提供可由用户选择采用的重构建议。
- 转换后圈画重点区域，生成精修候选、对比、采用并另存 SVG，支持撤销。
- 可选 Real-ESRGAN 超分辨率，优先使用 CUDA GPU，GPU 不可用或推理失败时回退 CPU。
- 可选 DiffVG 后处理；当前程序使用 CPU 模式。

## 从源码运行

本仓库发布源码，不包含 Windows 便携版的 Python、Node、第三方安装目录或模型权重。首次安装依赖需要联网；安装完成后，基础转换无需联网。

需要 Python **3.12–3.14**、Node.js **至少 20.9.0**（建议使用 24 系列）和随 Node 提供的 npm。图像处理依赖需要有适合系统的 wheel。当前实际验证平台为 Windows x64，macOS/Linux 的源码启动路径尚未进行整套验证。

### Windows PowerShell

```powershell
git clone https://github.com/sakiii3321/Animate-image-vector.git
cd Animate-image-vector
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npx --yes pnpm@11.25.0 --dir runtime/potrace install --frozen-lockfile --ignore-scripts
.\.venv\Scripts\python.exe app/main.py --self-test
.\START_SOURCE_WINDOWS.bat
```

若使用 Python 3.12 或 3.13，调整创建虚拟环境命令中的版本号即可。请保持启动终端打开，关闭程序时按 Ctrl+C。

### macOS / Linux

```sh
git clone https://github.com/sakiii3321/Animate-image-vector.git
cd Animate-image-vector
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npx --yes pnpm@11.25.0 --dir runtime/potrace install --frozen-lockfile --ignore-scripts
.venv/bin/python app/main.py --self-test
sh start_source.sh
```

Node 依赖由 `runtime/potrace/pnpm-lock.yaml` 锁定。源码模式使用 PATH 中的 Node；若目录里已有便携版 `runtime/node/node.exe`，程序优先使用它。

`START_WINDOWS.bat` 和 `SELF_TEST_WINDOWS.bat` 面向含运行库的 Windows 便携包；从 GitHub 克隆后，请使用以上源码启动和自检命令。

## 可选 GPU 超分与 DiffVG

基础矢量化不需要 GPU 或 PyTorch。增强功能需要另行准备 Python 3.12 环境、PyTorch 和模型；DiffVG 还需要适配平台的原生扩展。详见 [增强功能配置](runtime/enhancement/SOURCE_SETUP.md)。本仓库不包含本机解释器路径，也不会在启动时自动安装或下载模型。

## 使用与开发

- [完整使用说明](README_使用说明.md)：界面、局部精修、参数与保存行为。
- [参数对照](参数对照.md)：参数含义与取舍。
- [打包说明](PACKAGING_README.md)：如何组织另行制作的便携包。
- [测试说明](tests/README.md)：测试依赖和环境要求。

| 目录 | 内容 |
| --- | --- |
| `app/` | 算法、Python 本地服务、浏览器界面 |
| `runtime/potrace/` | Node 依赖清单与锁文件 |
| `runtime/enhancement/` | 增强配置模板、SR 网络代码与模型获取说明 |
| `examples/` | 小型示例图片和配置 |
| `tests/` | 自动测试源码 |
| `experiments/` | 实验方法、性能基准与盲评工具源码 |

原始插画、用户评分、历史测试输出和本机算法存档不在仓库中。使用说明里提到的 `outputs/`、`test_pic/` 和历史验证记录属于本地实验资料；相关实验需自行准备输入并重新生成结果。默认路径预算可能舍弃细小纹理，低清线条和复杂噪点仍需放大检查。

## 许可

本项目源码沿用仓库原有的 [MIT License](LICENSE)。第三方组件按各自许可发布，不能用本项目的 MIT 许可替代：例如 node-potrace 为 GPL-2.0，Sharp 为 Apache-2.0，Real-ESRGAN 为 BSD-3-Clause，DiffVG 为 Apache-2.0。相关文本见 `THIRD_PARTY_NOTICES/`、SR 代码目录及各依赖包。
