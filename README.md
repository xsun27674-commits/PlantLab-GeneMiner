---
title: PlantLab-GeneMiner
emoji: 🌱
colorFrom: green
colorTo: green
sdk: docker
app_port: 7860
---

# PlantLab-GeneMiner

面向植物功能基因挖掘的候选基因筛选与分析平台，当前版本为 **v3.0 Beta**。支持 FASTA 与 NCBI Datasets CDS ZIP 导入、成对序列比对、项目内 BLAST+、候选筛选、交互图表及 CSV、Excel、PNG 和 SVG 导出。

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

## Streamlit Community Cloud

**公开网址**：部署完成并验证后，在此填写 Community Cloud 分配的地址。

**备用入口**：[V3.0 Binder 教学预览](https://mybinder.org/v2/gh/xsun27674-commits/PlantLab-GeneMiner/v3.0-preview?urlpath=proxy%2F8501%2F)。

1. 在 [Streamlit Community Cloud](https://share.streamlit.io/) 登录并连接拥有该仓库访问权限的 GitHub 账户。
2. 选择 **Create app / Deploy a public app from GitHub**，填写下列值。

   | 字段 | 值 |
   | --- | --- |
   | Repository | `xsun27674-commits/PlantLab-GeneMiner` |
   | Branch | `community-cloud` |
   | Main file path | `app.py` |
   | Advanced settings → Python version | `3.11` |

3. 公开游客版的 **Secrets** 留空，使用平台分配的网址或为此应用选择可用的子域名，再点击 **Deploy**。
4. 应用就绪后，用无痕窗口打开地址，确认游客可直接进入首页。用模拟数据验证上传、成对比对、BLAST 搜索及下载，然后公布实际网址。

仓库根目录的 `packages.txt` 让 Community Cloud 通过 APT 安装 `ncbi-blast+` 和 `util-linux`。前者提供 `blastn` 与 `makeblastdb`，后者提供 Linux 资源限制工具 `prlimit`。`requirements.txt` 沿用固定的 Python 依赖版本，`.streamlit/config.toml` 保留 10 MiB 上传上限。图表卡片的 PNG/SVG 由浏览器渲染，公开部署无需安装服务端 Chromium。Docker 和 Binder 继续使用各自的依赖清单及启动配置。

可上传 FASTA、NCBI Datasets CDS ZIP、UTF-8 CSV 或 XLSX 序列表。外部 BLAST 支持标准 outfmt 6 以及带表头的 CSV、TSV、XLSX。内置 BLAST+ 只搜索用户为当前任务选中的目标序列，搜索范围不含完整 NCBI 数据库。

公开游客版按浏览器会话管理上传文件与分析结果。每次 BLAST 搜索使用独立的临时目录，正常完成、失败或超时退出时清理。公开环境请使用适合公开服务处理的数据。游客会话结束后，建议依赖已下载文件留存结果。服务可能休眠，首次部署和唤醒可能需要等待。平台 CPU、内存和运行时配额仍适用。应用已有上传和分析任务上限、批量比对进度及取消入口，较大任务可选择较小的查询或目标集合。工作进程级别的限制不等同于站点配额或访客限流。

## Hugging Face Spaces 部署

1. 创建一个 **Docker** 类型的 Space。需要访问控制时选择相应可见性。
2. 把项目文件上传到 Space 仓库根目录，保留 `Dockerfile`、`app.py`、`src/`、`data/`、`requirements.txt` 和 `.streamlit/config.toml`。跳过本地 `.venv`、缓存及研究数据。
3. 保留 Space README 顶部的平台配置，设置 `sdk: docker` 与 `app_port: 7860`。提交后在 Space 的构建和运行日志中查看结果。
4. Space 启动后，用模拟教学数据检查筛选、图表及下载。

Docker 配置使用 Python 3.11，并在 `0.0.0.0:7860` 上启动 Streamlit。部署无需 API 凭据。

## 使用范围

应用导入已有 BLAST 结果，数据与记录在当前会话内存中处理。刷新连接或重启后需要重新载入文件。工作流适用于可在内存中交互分析的数据，Excel 每个工作表受 1,048,576 行限制。BLAST 命中仅提供序列相似性证据，基因功能和直系同源关系需要独立验证。

## V1.1 图表、比对与导出

- FASTA 小样本按序列显示独立柱形。可手动切换柱状图、散点图和直方图。核酸数据可绘制 GC 含量。
- 可编辑图表颜色、标题、坐标轴和布局，并导入或导出独立的样式 JSON。交互 HTML 包含离线所需脚本。PNG 使用 2 倍像素输出；SVG 和图表 PDF 适用于排版。
- 使用 Python 3.11 安装更新后的 `requirements.txt`。静态图需要 Kaleido 与 Chrome/Chromium。若已有浏览器，可设置 `BROWSER_PATH` 指向其可执行文件；也可在虚拟环境中运行 `kaleido_get_chrome` 安装浏览器。中文导出建议安装 Noto Sans CJK SC。Dockerfile 安装 Chromium 和 CJK 字体。
- 「成对序列比对」支持双序列粘贴或从 FASTA 选择，提供全局与局部比对。每条序列最多 10,000 字符，两条长度之积最多 400 万。同分时采用 Biopython 返回的首个解。一致性分母包含 gap 列。
- FASTA 和 BLAST 上传每个文件限 10 MB，比对页面的 FASTA 限 5 MB。应用在服务器会话内处理数据，上传文件及分析结果不会由应用转发给外部服务。
- 目前提供 BLAST 表格导入及未来搜索实现接口。本地 BLAST+ 搜索需要可执行程序和参考数据库。尚未提供多维证据综合评分或 PDF 报告。

### 验证与在线预览

运行 `python -m pytest -q` 检查应用与核心分析逻辑。确认环境具备可用 Chrome 后，使用 `GENEMINER_TEST_IMAGES=1 python -m pytest -q` 一并验证 PNG、SVG和图表 PDF。

[打开 V1.1 教学预览](https://mybinder.org/v2/gh/xsun27674-commits/PlantLab-GeneMiner/v1.1-preview?urlpath=proxy%2F8501%2F)。首次启动可能需要构建容器。Binder 使用轻量模式，支持交互图表、HTML/CSV/JSON、候选导出。PNG/SVG/PDF可在本地或 Docker 使用。预览会话会过期，建议用模拟数据体验。

## V3.0

游客可直接运行 FASTA 质检、成对序列比对和 BLAST 结果筛选，游客会话不会自动长期保存。可切换中文和英文界面，相似性指标只描述输入和筛选结果，不能证明基因功能或直系同源关系。

### 本地开发与 Docker

使用 Python 3.11 创建虚拟环境，安装 `requirements.txt`，在项目目录执行 `python -m streamlit run app.py`。每张图表卡片可直接在浏览器下载 PNG（2 倍清晰度）或 SVG。服务端 PNG/SVG/PDF需要 Chrome/Chromium 与 Kaleido，Docker 已包含浏览器和 CJK 字体：

```bash
docker build -t plantlab-geneminer:v3 .
docker run --rm -p 7860:7860 plantlab-geneminer:v3
```

使用 `GENEMINER_DEV_DB=/absolute/private/path/development.sqlite3` 可启用开发账户和持久化项目。该模式供本机调试，不具备公共运营需要的邮件确认、反滥用和限流。不要对互联网启用。备份开发数据库时同时保护其文件及相关卷。将正式横版 PNG 放到 `assets/logo.png`，或用 `GENEMINER_LOGO_PATH` 指定文件。首页、账号页、关于页、侧边栏会自动使用该文件。可另放方形图标 `assets/logo-icon.png`，或用 `GENEMINER_LOGO_ICON_PATH` 指定浏览器图标。正式资源缺失或无法读取时只显示品牌文字。

### 正式部署及数据存储

1. 在专用 Supabase 项目运行 [deploy/supabase.sql](deploy/supabase.sql)。确认 Email Auth 已启用，开启邮件确认，配置站点 URL、邮件发送服务、密码和速率限制。密码重置模板使用 `{{ .TokenHash }}` 给用户显示一次性的凭证，用户可在「账户 → 忘记密码」提交凭证与新密码。上线前验证注册确认和密码重置邮件。
2. 在 Hugging Face 创建 Docker Space，上传项目文件。在 Space 的 Variables / Secrets 中设置 `GENEMINER_SUPABASE_URL` 和 `GENEMINER_SUPABASE_PUBLIC_KEY`。使用 HTTPS 项目地址及 publishable 或 legacy anon 客户端密钥，禁止使用 service role。让 Docker 在 7860 端口监听。Space 无需持久磁盘来保存科研项目。
3. 使用两个浏览器及两个账户验收。账户 A 保存后，在另一浏览器用 A 登录并恢复；用 B 登录，确认无法读写或删除 A 的项目。再验证账户删除及图像下载。正式部署前核对供应商费用、服务区域、备份保留期和研究数据条款。关闭开发数据库变量。

项目表为 `public.geneminer_projects`。记录 UUID 项目 ID、`auth.users` 所有者、名称、物种、目标、分析状态、创建和修改时间、版本化 JSON 快照。账户的删除通过受限 RPC 执行，外键级联删除项目。PostgreSQL 使用 RLS 检查当前 JWT 的 `auth.uid()`。SQLite 开发库用服务器会话校验并按所有者查询。Supabase 按服务配置的备份周期保留备份。

V3.0 将上传文件（编码在快照中）、分析参数、结果和图表原子地保存在访问隔离的 PostgreSQL 行中。单项目快照限 32 MiB，未配置独立对象存储。自动保存可选，每两分钟检查现有项目，跳过未改动的快照。改动时写入整份快照，多设备同时编辑为最后成功保存者生效。应用使用经过校验的 JSON 恢复状态，不反序列化可执行对象。Supabase 登录凭证留在服务器会话，访问令牌到期后须重新登录。

### 教学预览及测试

[打开 V3.0 Binder 教学预览](https://mybinder.org/v2/gh/xsun27674-commits/PlantLab-GeneMiner/v3.0-preview?urlpath=proxy%2F8501%2F)。Binder 不带生产账户配置，由图表卡片直接导出 PNG/SVG。Binder 请使用模拟数据。正式在线部署和 Supabase 双设备验收须由所有者配置后验证。

```bash
python -m pytest -q
GENEMINER_TEST_IMAGES=1 python -m pytest -q
```

### 批量序列输入与部署验收

FASTA 分析接收 FASTA、UTF-8 CSV 和 XLSX。表格默认识别 `Sequence ID` 与 `Sequence`，也可手动映射两列。在线表格可直接编辑，也可通过「粘贴两列文本」从电子表格导入制表符分隔的数据，然后点击「分析表格」。序列表最多 5,000 行，上传文件最多 10 MB。编号应使用无空格的标识；保留前导零的编号在 Excel 中应存为文本。从首页选择研究路径后，两个流程均使用项目中已导入的序列。

面向公众的完整 Beta 可部署为 Docker Space。镜像使用 Python 3.11，安装 Chromium 与 CJK 字体，在 `0.0.0.0:7860` 启动 Streamlit。以 `/_stcore/health` 验证启动，再在独立浏览器会话验证真实上传、图例及 PNG/SVG。Binder 是无需登录的教学启动入口，首次构建有冷启动时间。GitHub 推送不会自动更新外部 Space。

### 从 NCBI Datasets 导入 CDS ZIP

在「数据导入与管理」点击「从 NCBI 获取序列」，搜索基因并选择物种，在 Download Package 勾选 CDS (FASTA)，下载后直接上传 ZIP。文件在当前会话内解析，使用包内 CDS 标题和可匹配的 `data_report.jsonl`。基因数按确认的 GeneID 去重，转录本数按确认的转录本 accession 去重。匹配不到的字段显示「待核实」。编辑序列编号、序列或删行后，可下载 Excel/CSV，或点击「应用序列到项目」后继续分析。

ZIP 上限为 10 MiB、512 个成员、总解压大小 64 MiB；CDS 内容总大小限 8 MiB，最多 5,000 条。系统不会把 ZIP 成员写入磁盘。Excel 单元格上限为 32,767 字符，超长序列完整存放在 `PlantLab Sequence Parts` 工作表，由 PlantLab 重新导入时自动拼合。CSV 始终在一个字段中保留完整序列。

### 项目序列与批量比对

在「数据导入与管理」中应用 FASTA、常规序列表或 NCBI ZIP 后，当前项目会记录标准化序列和来源。明确带 CDS 或 Length (bp) 字段的表格自动按核酸处理，普通表格可选择核酸或蛋白质。下一步进入从首页选择的路径。游客使用当前会话，已配置持久化服务的登录用户可以通过原有的「保存项目」操作持久化。

首页提供「序列比较与相似性筛选」和「BLAST 搜索与候选筛选」。两条路径共享项目导入的序列，分别保存候选结果。序列比较依次进入 FASTA 序列统计、成对序列比对和本地比对候选筛选。BLAST 路径由搜索直接进入 BLAST 候选筛选。两条路径均可在「分析结果」下载 CSV，并在「可视化与导出」选择对应来源、查看图表并下载数据和参数。替换项目序列时，系统会清除依赖旧序列的结果。

批量核酸比对支持全部或指定记录、All-vs-All、One-vs-All 和按已核实基因分组。All-vs-All 默认跳过自比对及重复方向，63 条共 1,953 对。资源预算为 12,000 对、每对 6,400 万及整批 120 亿估算动态规划单元。超过预算可缩小范围、用单查询或按基因分组。单个独立工作进程运行比对，网页显示任务数量、进度和耗时。取消后可在当前会话以相同参数续算。关闭会话或重启应用会丢失未完成进度，已保存项目可恢复当前已完成批次。

Biopython PairwiseAligner 使用全局或局部模式。一致性以包含缺口的全部比对列为分母，覆盖度以比对消耗的碱基数除以对应序列全长计算。局部无正分结果时一致性留空。默认名称为基因符号与登录号，方括号用于区分重名的界面记录。矩阵支持基因排序、平均连接相似性排序、缩放、按格查看碱基级比对及 PNG/SVG 导出。相似性聚类只用于探索。完整矩阵可下载为 CSV/XLSX。

本地候选页支持参考序列、排除自比对以及一致性、长度、覆盖度、原始得分及缺口数筛选。分析记录保留来源、参数、结果和序列标识。标准 BLAST CSV/XLSX 可重新导入 BLAST 模块。

### 项目内 BLAST 候选筛选

在首页选择「开始 BLAST 分析」，进入「BLAST 搜索」并点击「使用当前序列运行 BLAST」。查询和目标均默认使用当前项目全部有效序列，也可分别选择子集。系统用 `makeblastdb` 创建临时数据库，再运行 `blastn`；搜索范围只包括选中的项目序列。命中会自动进入筛选、可视化与导出，原始 TSV 下载为可选操作。「外部 BLAST 命中表」仍可上传。默认隐藏自命中以及所有完全相同序列之间的命中。

Binder 通过 `binder/apt.txt` 安装 `ncbi-blast+` 和 `util-linux`，Dockerfile 同样安装这两项。本地 Debian/Ubuntu 可运行 `sudo apt-get install ncbi-blast+ util-linux`。启动前可用 `blastn -version` 和 `makeblastdb -version` 检查 PATH。

本地搜索每次使用一个线程，每次最多 128 条查询和 128 条目标序列，每侧总长最多 500,000 bp，单条最长 50,000 bp。建库超时 15 秒，搜索超时 45 秒。Linux 上可用 `prlimit` 时限制进程虚拟内存为 768 MiB。搜索固定 E-value 上限为 10，每对最多保留 5 个 HSP。临时目录在任务完成或失败后清理。

### AI 辅助开发说明

本项目使用 AI 工具辅助编写、审查代码与测试。分析数值由项目的 Biopython、NCBI BLAST+ 和数据处理代码计算，研究结论应结合独立证据核实。
