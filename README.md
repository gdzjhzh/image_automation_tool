# Image Automation Tool

批量图片风格化与防重复检测（Anti-Dedup）处理工具，赋能内容运营团队在多平台高效复用热门素材，同时保持视觉一致性与数字指纹差异化。项目同时提供 **命令行（CLI）** 与 **Tkinter GUI** 双入口，支持多进程并行处理、实时进度展示、详细报告输出。

---

## 核心能力

- **风格统一**：支持比例裁剪/留白、纯色或 PNG 边框、背景颜色等一键套用。
- **防重复检测**：内置多档随机扰动（噪点、色彩抖动、旋转裁剪、镜像、水印），改变文件/感知哈希。
- **批量高效**：多进程并发执行，上千张图片亦可快速处理。
- **鲁棒可靠**：自动跳过非图片或损坏文件，记录在报告中，任务不中断。
- **人性化体验**：CLI 适合自动化脚本，GUI 满足运营同学的图形化操作习惯。

---

## 目录结构

```
image_automation_tool/
├── README.md
├── pyproject.toml
├── src/image_automation
│   ├── cli/            # Typer 命令行入口
│   ├── core/           # 配置、模型、输出管理、进度定义
│   ├── processing/     # 文件扫描、图像加载、风格化、防检测、并行任务
│   ├── gui/            # Tkinter GUI 实现
│   └── utils/          # 工具方法（颜色解析、日志）
└── tests/              # Pytest 测试用例
```

---

## 快速开始

### 1. 安装依赖

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 2. 运行测试（可选）

```bash
python -m pytest -r w
```

### 3. CLI 用法

```bash
python -m image_automation.cli.main run \
    /path/to/source1 /path/to/source2 \
    --output /path/to/output \
    --ratio 1:1 \
    --mode contain \
    --antidedup-mode heavy \
    --allow-mirror \
    --watermark-text "brand" \
    --on-conflict rename \
    --workers 4 \
    --seed 1234
```

访问 `python -m image_automation.cli.main run --help` 查看全部参数。

### 4. GUI 用法

```bash
python -m image_automation.gui.app
```

在 GUI 中选择源目录/输出目录，配置参数（见下文“GUI 参数说明”），点击「启动处理」即可。支持实时进度条、日志输出以及完成后的统计信息。

---

## 核心流程概述

1. **参数解析**：CLI/GUI 均生成 `JobConfig`，描述源目录、输出策略、防检测模式等。
2. **文件扫描**：递归遍历源目录，过滤非图片文件及重复路径，保留相对路径信息。
3. **任务构建**：根据冲突策略提前预约输出路径，生成 `ProcessingTask` 列表。
4. **并发处理**：
   - 读取图片并纠正 EXIF 方向、色彩空间。
   - 按配置执行风格化（contain/cover、边框留白等）。
   - 应用防重复扰动（颜色抖动、噪点、旋转、镜像、水印等），并记录操作说明。
   - 写入输出文件，失败时返回结构化错误信息。
5. **进度回调**：主进程捕获 `ProgressUpdate`，用于 CLI 的 Rich 进度条或 GUI 的进度条与日志。
6. **结果汇总**：输出 `BatchResult`，同时在目标目录生成 `report.csv`（记录源路径、输出路径、状态、备注）。

---

## GUI 参数说明

- **防检测模式**
  - `none`：仅执行风格化，不做防重复处理。
  - `light`：轻度随机抖动（亮度/对比度/饱和度）+ 低强度噪点。
  - `medium`：在 `light` 基础上增加微小旋转与裁剪。
  - `heavy`：在 `medium` 基础上叠加多重“数字微痕”水印（数量、位置、透明度随机）。

- **水印数量 / 透明度 / 缩放范围**  
  两个输入框表示“最小值”和“最大值”，处理时会在范围内随机取值。若希望固定值，可把两个输入框设置为同一个数字。

- **冲突策略 (`--on-conflict`)**
  - `rename`：若输出目录已有同名文件，自动重命名（如 `image.png` → `image_1.png`）。
  - `overwrite`：覆盖已有文件。
  - `skip`：跳过该文件并在报告中提示“已存在，已跳过”。

- **随机种子**  
  留空表示每次运行产生不同的随机扰动；填入任意整数（建议 0～4294967295）则可复现同一批输出，便于排查与回归。

- **字体配置补充**  
  启动 GUI 时会自动尝试使用常见的中文字体（如微软雅黑、苹方、思源黑体等），避免界面文字显示为方块。若系统缺少这些字体，可自行安装后再次启动。

---

## Report & 日志

- 输出目录下生成 `report.csv`，字段包含：
  - `source_path`
  - `output_path`
  - `status`（如 `processed`、`processed-rename`、`skip-existing`、`error-load` 等）
  - `message`（包含冲突说明、防检测操作摘要）
- CLI 使用标准日志输出，GUI 在界面下方显示日志；所有错误/跳过信息均保留在报告中，方便后续排查。

---

## 开发指南

### 阶段性递进

项目按照以下里程碑推进，每阶段均完成测试与 Git 备份：

1. **项目骨架与基础设施**：目录结构、依赖、配置。
2. **文件扫描与基础预处理**：递归扫描、EXIF 校正、颜色空间转换、异常记录。
3. **风格化与输出管理**：contain/cover、边框模板、冲突策略、报告生成。
4. **防检测引擎**：light/medium/heavy 模式、防重复扰动、水印机制。
5. **并发、GUI 与体验提升**：ProcessPool 并行、进度回调、GUI 表单/进度条、字体适配。

### 常用开发命令

```bash
# 激活虚拟环境
source .venv/bin/activate

# 运行测试
python -m pytest -r w

# 保存代码风格
ruff check .            # 如已安装 ruff
ruff format .

# 启动 CLI
python -m image_automation.cli.main run --help

# 启动 GUI
python -m image_automation.gui.app
```

### 编码约定

- Python >= 3.11，依赖通过 `pyproject.toml` 管理。
- 数据配置使用 `dataclass`，并在核心模块之间传递。
- 并发部分采用 `ProcessPoolExecutor`，任务数据需可 Pickle。
- 日志统一通过 `utils.logging.setup_logging` 初始化。
- README、代码注释与界面文案保持中英文可读性，面向运营同学优先。

---

## 后续工作建议

- 增加批量配置导入/导出功能，方便保存常用参数。
- 支持更多扰动策略（如轻度模糊、色彩 LUT、背景纹理）。
- 引入持久化任务管理或队列（Celery/RQ）用于离线处理。
- 对 GUI 添加预览功能或处理完成通知。
- 打包为可执行程序（PyInstaller / Briefcase）以便非技术同学部署。

---

## 许可证

当前项目默认采用 MIT License（见 `pyproject.toml`），可根据公司实际要求调整。

如需进一步合作或定制功能，请联系项目维护者。祝开发顺利！🚀
