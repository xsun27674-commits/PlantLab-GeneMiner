---
title: PlantLab-GeneMiner
emoji: 🌱
colorFrom: green
colorTo: green
sdk: docker
app_port: 7860
---

# PlantLab-GeneMiner

面向植物功能基因挖掘的候选基因筛选与分析平台。V1.1 支持 FASTA 序列检查、BLAST 表格导入、交互式筛选、Plotly 图表及科研记录导出。

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

## 使用范围

应用导入已有 BLAST 结果，数据与记录在当前会话内存中处理。刷新连接或重启后需要重新载入文件。工作流适用于可在内存中交互分析的数据，Excel 每个工作表受 1,048,576 行限制。BLAST 命中仅提供序列相似性证据，基因功能和直系同源关系需要独立验证。

## V1.1 图表、比对与报告

- FASTA 小样本按序列显示独立柱形。可手动切换柱状图、散点图和直方图。核酸数据可绘制 GC 含量。
- 可编辑图表颜色、标题、坐标轴和布局，并导入或导出独立的样式 JSON。交互 HTML 包含离线所需脚本。PNG 使用 2 倍像素输出；SVG 和图表 PDF 适用于排版。
- 使用 Python 3.11 安装更新后的 `requirements.txt`。静态图和 Word 插图需要 Kaleido 与 Chrome/Chromium。若已有浏览器，可设置 `BROWSER_PATH` 指向其可执行文件；也可在虚拟环境中运行 `kaleido_get_chrome` 安装浏览器。中文导出建议安装 Noto Sans CJK SC。Dockerfile 安装 Chromium 和 CJK 字体。
- 「成对序列比对」支持双序列粘贴或从 FASTA 选择，提供全局与局部比对。每条序列最多 10,000 字符，两条长度之积最多 400 万。同分时采用 Biopython 返回的首个解。一致性分母包含 gap 列。
- 在「分析记录与导出」选择已生成的图表及结果表，可生成带页码的 Word 报告。Word 每表最多显示 1,000 行，完整筛选结果另见 CSV 和 Excel。
- FASTA 和 BLAST 上传每个文件限 10 MB，比对页面的 FASTA 限 5 MB。应用在服务器会话内处理数据，上传文件及分析结果不会由应用转发给外部服务。
- 目前提供 BLAST 表格导入及未来搜索实现接口。本地 BLAST+ 搜索需要可执行程序和参考数据库。尚未提供多维证据综合评分或 PDF 报告。

### 验证与在线预览

运行 `python -m pytest -q` 检查应用与核心分析逻辑。确认环境具备可用 Chrome 后，使用 `GENEMINER_TEST_IMAGES=1 python -m pytest -q` 一并验证 PNG、SVG、图表 PDF 和 Word 插图。

[打开 V1.1 教学预览](https://mybinder.org/v2/gh/xsun27674-commits/PlantLab-GeneMiner/v1.1-preview?urlpath=proxy%2F8501%2F)。首次启动可能需要构建容器。Binder 使用轻量模式，支持交互图表、HTML/CSV/JSON、候选导出及无插图 Word。PNG/SVG/PDF 和 Word 插图可在本地或 Docker 使用。预览会话会过期，建议用模拟数据体验。

## V3.0

游客可直接运行 FASTA 质检、成对序列比对和 BLAST 结果筛选，游客会话不会自动长期保存。可切换中文和英文界面，报告可独立选择中文或英文、简洁或完整模式。报告中的相似性指标只描述输入和筛选结果，不能证明基因功能或直系同源关系。

### 本地开发与 Docker

使用 Python 3.11 创建虚拟环境，安装 `requirements.txt`，在项目目录执行 `python -m streamlit run app.py`。每张图表卡片可直接在浏览器下载 PNG（2 倍清晰度）或 SVG。服务端 PNG/SVG/PDF 和 Word 插图需要 Chrome/Chromium 与 Kaleido，Docker 已包含浏览器和 CJK 字体：

```bash
docker build -t plantlab-geneminer:v3 .
docker run --rm -p 7860:7860 plantlab-geneminer:v3
```

使用 `GENEMINER_DEV_DB=/absolute/private/path/development.sqlite3` 可启用开发账户和持久化项目。该模式供本机调试，不具备公共运营需要的邮件确认、反滥用和限流。不要对互联网启用。备份开发数据库时同时保护其文件及相关卷。将正式横版 PNG 放到 `assets/logo.png`，或用 `GENEMINER_LOGO_PATH` 指定文件。首页、账号页、关于页、侧边栏和 Word 封面会自动使用该文件。可另放方形图标 `assets/logo-icon.png`，或用 `GENEMINER_LOGO_ICON_PATH` 指定浏览器图标。正式资源缺失或无法读取时只显示品牌文字。

### 正式部署及数据存储

1. 在专用 Supabase 项目运行 [deploy/supabase.sql](deploy/supabase.sql)。确认 Email Auth 已启用，开启邮件确认，配置站点 URL、邮件发送服务、密码和速率限制。密码重置模板使用 `{{ .TokenHash }}` 给用户显示一次性的凭证，用户可在「账户 → 忘记密码」提交凭证与新密码。上线前验证注册确认和密码重置邮件。
2. 在 Hugging Face 创建 Docker Space，上传项目文件。在 Space 的 Variables / Secrets 中设置 `GENEMINER_SUPABASE_URL` 和 `GENEMINER_SUPABASE_PUBLIC_KEY`。使用 HTTPS 项目地址及 publishable 或 legacy anon 客户端密钥，禁止使用 service role。让 Docker 在 7860 端口监听。Space 无需持久磁盘来保存科研项目。
3. 使用两个浏览器及两个账户验收。账户 A 保存后，在另一浏览器用 A 登录并恢复；用 B 登录，确认无法读写或删除 A 的项目。再验证账户删除、图像下载及 Word 插图。正式部署前核对供应商费用、服务区域、备份保留期和研究数据条款。关闭开发数据库变量。

项目表为 `public.geneminer_projects`。记录 UUID 项目 ID、`auth.users` 所有者、名称、物种、目标、分析状态、创建和修改时间、版本化 JSON 快照。账户的删除通过受限 RPC 执行，外键级联删除项目。PostgreSQL 使用 RLS 检查当前 JWT 的 `auth.uid()`。SQLite 开发库用服务器会话校验并按所有者查询。Supabase 按服务配置的备份周期保留备份。

V3.0 将上传文件（编码在快照中）、分析参数、结果、图表和报告原子地保存在访问隔离的 PostgreSQL 行中。单项目快照限 32 MiB，未配置独立对象存储。自动保存可选，每两分钟检查现有项目，跳过未改动的快照。改动时写入整份快照，多设备同时编辑为最后成功保存者生效。应用使用经过校验的 JSON 恢复状态，不反序列化可执行对象。Supabase 登录凭证留在服务器会话，访问令牌到期后须重新登录。

### 教学预览及测试

[打开 V3.0 Binder 教学预览](https://mybinder.org/v2/gh/xsun27674-commits/PlantLab-GeneMiner/v3.0-preview?urlpath=proxy%2F8501%2F)。Binder 不带生产账户配置，由图表卡片直接导出 PNG/SVG，轻量报告不内嵌图表。Binder 请使用模拟数据。正式在线部署和 Supabase 双设备验收须由所有者配置后验证。

```bash
python -m pytest -q
GENEMINER_TEST_IMAGES=1 python -m pytest -q
```

### 批量序列输入与部署验收

FASTA 分析接收 FASTA、UTF-8 CSV 和 XLSX。表格默认识别 `Sequence ID` 与 `Sequence`，也可手动映射两列。在线表格可直接编辑，也可通过「粘贴两列文本」从电子表格导入制表符分隔的数据，然后点击「分析表格」。序列表最多 5,000 行，上传文件最多 10 MB。编号应使用无空格的标识；保留前导零的编号在 Excel 中应存为文本。FASTA 基础分析不会产生 BLAST 命中，下一步需要另行上传外部结果。

面向公众的完整 Beta 可部署为 Docker Space。镜像使用 Python 3.11，安装 Chromium 与 CJK 字体，在 `0.0.0.0:7860` 启动 Streamlit。以 `/_stcore/health` 验证启动，再在独立浏览器会话验证真实上传、图例、PNG/SVG 及嵌图 DOCX。Binder 是无需登录的教学启动入口，首次构建有冷启动时间，Word 导出在其轻量配置下不带图。GitHub 推送不会自动更新外部 Space。
