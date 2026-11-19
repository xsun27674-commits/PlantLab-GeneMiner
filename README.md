---
title: PlantLab-GeneMiner
emoji: 🌱
colorFrom: green
colorTo: green
sdk: docker
app_port: 7860
---

# PlantLab-GeneMiner

面向植物功能基因挖掘的候选基因筛选与分析平台。V1.0 支持 FASTA 序列检查、BLAST 表格导入、交互式筛选、Plotly 图表及科研记录导出。

## 本地运行

在项目目录中使用 Python 3.11。

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Windows PowerShell 可用 `.venv\Scripts\Activate.ps1` 激活环境。打开终端显示的本地地址。运行测试使用 `python -m pytest -q`。

## 使用流程

1. 在首页下载模拟教学数据，或在分析页面直接载入示例。
2. 在 FASTA 页选择核酸或蛋白质。查看长度分布、重复 ID、空序列和非法字符报告，然后下载 CSV。核酸接受 IUPAC 字符与 U。GC 计算排除无法归入 GC 或 AT 类别的模糊碱基，S 和 W 分别计为 GC 和 AT。非法字符、空序列和没有可统计碱基的记录留空。
3. 在 BLAST 页上传 UTF-8 CSV 或 TSV。无表头的 12 列表按标准 outfmt 6 解释。自定义列顺序、无表头扩展格式或非标准表头可在预览中手动调整。导出采用映射后的标准字段。
4. 设置筛选阈值。边界值计入结果，E-value 按十进制比较，阈值为 0 时仅保留 E-value 等于 0 的命中。覆盖度有实际数值时可选用 qcovs 或 qcovhsp，空白覆盖度不会通过已启用的覆盖度筛选。候选数按每个 Query 的唯一 Subject ID 计算。
5. 查看筛选结果、各 Query 最佳命中和可视化。最佳命中依次按 Bit score 降序、E-value 升序、Identity 降序、比对长度降序、Subject ID 升序和输入行序决胜。
6. 填写分析记录并下载 JSON、筛选结果 CSV 或包含筛选结果、最佳命中和分析参数的 Excel。分析时间标注为 UTC。

示例 FASTA 含 6 条人工序列。示例 BLAST 含 60 条模拟命中，覆盖 6 个 Query 和 10 个 Subject。模拟命中由程序生成。

## Hugging Face Spaces 部署

1. 创建一个 **Docker** 类型的 Space。需要访问控制时选择相应可见性。
2. 把项目文件上传到 Space 仓库根目录，保留 `Dockerfile`、`app.py`、`src/`、`data/`、`requirements.txt` 和 `.streamlit/config.toml`。跳过本地 `.venv`、缓存及研究数据。
3. 保留 Space README 顶部的平台配置，设置 `sdk: docker` 与 `app_port: 7860`。提交后在 Space 的构建和运行日志中查看结果。
4. Space 启动后，用模拟教学数据检查筛选、图表及下载。

Docker 配置使用 Python 3.11，并在 `0.0.0.0:7860` 上启动 Streamlit。部署无需 API 凭据。

## V1.0 范围

应用导入已有 BLAST 结果，数据与记录在当前会话内存中处理。刷新连接或重启后需要重新载入文件。工作流适用于可在内存中交互分析的数据，Excel 每个工作表受 1,048,576 行限制。BLAST 命中仅提供序列相似性证据，基因功能和直系同源关系需要独立验证。
