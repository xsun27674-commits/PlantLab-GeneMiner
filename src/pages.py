"""Chinese Streamlit views for the analysis workflow."""

from html import escape
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import pandas as pd

import streamlit as st

from src.i18n import display_frame, tr, translator
from src.brand import NAME, TAGLINE, brand_banner, brand_mark_uri
from src.account_page import navigate, save_button

from src import visualization as charts
from src.analysis_record import VERSION, build_record
from src.chart_editor import ChartStyle, chart_panel, image_bytes, static_images_enabled
from src.report import word_report
from src.blast_utils import (
    COVERAGE, REQUIRED, Thresholds, best_hits, candidate_counts, filter_hits,
    normalize_hits, parse_evalue, read_blast, rejection_reasons, suggest_mapping,
)
from src.export_utils import csv_bytes, excel_bytes, json_bytes
from src.fasta_utils import analyze_fasta
from src.sequence_input import read_sequence_table, table_to_fasta

DATA = Path(__file__).resolve().parents[1] / "data"
EXAMPLES = {
    "fasta": ("example_sequences.fasta", "FASTA 序列"),
    "blast": ("example_blast.tsv", "BLAST 命中表"),
}
NOTICE = "BLAST 命中仅提供序列相似性证据。基因功能和直系同源关系需要独立验证。"
METADATA = (
    "项目名称", "研究物种", "目标基因或基因家族", "数据来源",
    "BLAST 程序及版本", "参考数据库及版本", "分析备注",
)


def source(kind, extensions):
    name, label = EXAMPLES[kind]
    path = DATA / name
    use_example = st.checkbox(tr("载入模拟教学数据"), key=f"{kind}_example")
    if use_example:
        return name, path.read_bytes(), "模拟教学数据"
    widget_key = f"{kind}_upload"
    cache_key = f"{kind}_source"

    def remember_upload():
        upload = st.session_state[widget_key]
        if upload is None:
            st.session_state[cache_key] = None
            return
        content = upload.getvalue()
        origin = "模拟教学数据" if content == path.read_bytes() else "用户上传"
        st.session_state[cache_key] = (upload.name, content, origin)

    upload = st.file_uploader(f"{tr('上传')} {tr(label)}", type=extensions, key=widget_key,
                              on_change=remember_upload)
    cached = st.session_state.get(cache_key)
    if upload is None and cached is not None:
        st.caption(f'{tr("当前文件")} · {cached[0]}')
        if st.button(tr("清除当前文件"), key=f"clear_{kind}"):
            st.session_state.pop(cache_key)
            return None
    if cached is not None and len(cached[1]) > 10 * 1024 * 1024:
        st.error(tr("文件超过 10 MB，请拆分后再上传。"))
        return None
    return cached


def home():
    with st.container(key="home_intro"):
        copy, illustration = st.columns([1.45, 1], vertical_alignment="center")
        with copy:
            st.html(f"""<div class="plantlab-hero">
                <h1>{NAME}</h1>
                <h2>{escape(tr("植物序列分析与候选基因筛选平台"))}</h2>
                <p>{TAGLINE}</p>
            </div>""")
            if st.button(tr("开始使用 →"), key="home_start", type="primary"):
                navigate("FASTA 序列分析")
        with illustration:
            st.html(f'<img class="plantlab-hero-art" src="{brand_mark_uri()}" alt="">')


def run_time():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sequence_source():
    mode = st.radio(tr("序列输入方式"), ("upload", "grid"), key="sequence_input_mode",
                    format_func={"upload": tr("上传文件"), "grid": tr("在线表格")}.get,
                    horizontal=True)
    if mode == "upload":
        upload = source("fasta", ["fasta", "fa", "fna", "faa", "fas", "txt", "csv", "xlsx"])
        if not upload or Path(upload[0]).suffix.lower() not in (".csv", ".xlsx"):
            return upload
        name, data, origin = upload
        rows = read_sequence_table(name, data)
        options = list(rows.columns)
        normalized = {str(column).strip().casefold().replace("_", " "): index
                      for index, column in enumerate(options)}
        suffix = sha256(data).hexdigest()
        left, right = st.columns(2)
        identifier = left.selectbox(tr("序列编号列"), options, key=f"mapping_seqid_{suffix}",
                                    index=normalized.get("sequence id", normalized.get("序列编号", 0)))
        sequence = right.selectbox(tr("序列内容列"), options, key=f"mapping_sequence_{suffix}",
                                   index=normalized.get("sequence", normalized.get("序列内容", 1)))
        with st.expander(tr("输入预览")):
            st.dataframe(rows.head(10), hide_index=True)
        return name, table_to_fasta(rows, identifier, sequence), origin

    st.caption(tr("可从 Excel 复制多行两列，粘贴到表格中。也可使用下方文本入口。"))
    columns = ("Sequence ID", "Sequence")
    base = st.session_state.get("sequence_grid_base", pd.DataFrame([["", ""]], columns=columns))
    revision = st.session_state.get("sequence_grid_revision", 0)
    edited = st.data_editor(base, num_rows="dynamic", hide_index=True, width="stretch",
                            column_config={columns[0]: tr("序列编号"), columns[1]: tr("序列内容")},
                            key=f"sequence_grid_editor_{revision}")
    with st.expander(tr("粘贴两列文本")):
        text = st.text_area(tr("每行格式：序列编号、Tab、序列内容"), key="sequence_input_paste",
                            max_chars=10_000_000)
        if st.button(tr("导入表格")):
            pairs = [line.split("\t") for line in text.splitlines() if line.strip()]
            if pairs and [part.strip().casefold() for part in pairs[0]] in (
                ["sequence id", "sequence"], ["序列编号", "序列内容"]
            ):
                pairs.pop(0)
            if not pairs or len(pairs) > 5000 or any(len(pair) != 2 for pair in pairs):
                st.error(tr("请粘贴最多 5,000 行的两列表格。"))
            else:
                st.session_state["sequence_grid_base"] = pd.DataFrame(pairs, columns=columns)
                st.session_state["sequence_grid_revision"] = revision + 1
                st.rerun()
    if st.button(tr("分析表格")):
        canonical = table_to_fasta(edited, *columns, ignore_blank_rows=True)
        st.session_state["sequence_grid_source"] = ("sequence_table.fasta", canonical, "在线表格")
        st.session_state["sequence_grid_base"] = edited
        st.session_state["sequence_grid_revision"] = revision + 1
        st.rerun()
    return st.session_state.get("sequence_grid_source")


def next_step(label, destination):
    if st.button(tr(label), key=f"workflow_next_{destination}"):
        navigate(destination)


def fasta():
    st.title(tr("FASTA 序列分析"))
    previous = st.session_state.pop("fasta_result", None)
    figures = st.session_state.setdefault("report_figures", {})
    for chart in ("fasta_length", "fasta_gc"):
        figures.pop(chart, None)
    try:
        selected = sequence_source()
    except ValueError as exc:
        st.error(tr(str(exc)))
        return
    labels = {"nucleotide": "核酸", "protein": "蛋白质"}
    sequence_type = st.radio(tr("序列类型"), labels, index=None, format_func=lambda key, translate=translator(): translate(labels[key]),
                             horizontal=True, key="sequence_type")
    if selected is None or sequence_type is None:
        st.info(tr("请载入 FASTA 文件并明确选择序列类型。"))
        return
    name, data, origin = selected
    fingerprint = (name, sha256(data).hexdigest(), origin, sequence_type)
    try:
        frame = analyze_fasta(data, sequence_type)
    except ValueError as exc:
        st.error(tr(str(exc)))
        return
    timestamp = previous["分析时间（UTC）"] if previous and previous["key"] == fingerprint else run_time()
    st.session_state["fasta_result"] = {
        "key": fingerprint, "上传文件名称": name, "文件来源": origin, "序列类型": labels[sequence_type],
        "分析时间（UTC）": timestamp, "序列数": len(frame),
        "最短序列": int(frame["序列长度"].min()), "最长序列": int(frame["序列长度"].max()),
        "重复 ID 记录数": int(frame["重复 ID"].sum()),
        "非法字符记录数": int(frame["非法字符"].ne("").sum()),
    }
    if origin == "模拟教学数据":
        st.caption(tr(origin))
    duplicate_count = int(frame["重复 ID"].sum())
    invalid_count = int(frame["非法字符"].ne("").sum())
    empty_count = int(frame["空序列"].sum())
    for column, label, value in zip(st.columns(4), ("序列数", "重复 ID 记录", "非法字符记录", "空序列"),
                                    (len(frame), duplicate_count, invalid_count, empty_count)):
        column.metric(tr(label), value)
    if duplicate_count or invalid_count or empty_count:
        st.warning(tr("请检查表中标记的重复 ID、非法字符和空序列。"))
    if sequence_type == "nucleotide":
        st.caption(tr("GC 使用 Biopython 的模糊碱基排除规则，S 与 W 按已知 GC 类别计入。无法计算时留空。"))
    st.dataframe(display_frame(frame.assign(**{tr("行号"): range(1, len(frame) + 1)})), width="stretch", hide_index=True)
    frame = frame.assign(序列类型=labels[sequence_type])
    plot_distribution(frame, "fasta_length", "序列长度", "序列长度", "序列 ID")
    if sequence_type == "nucleotide" and frame["GC (%)"].notna().any():
        plot_distribution(frame.dropna(subset=["GC (%)"]), "fasta_gc", "GC (%)", "GC 含量", "序列 ID")
    st.download_button(tr("下载 FASTA 序列统计 CSV"), csv_bytes(frame.drop(columns="序列类型")), "fasta_statistics.csv", "text/csv")
    st.caption(tr("FASTA 分析不会产生 BLAST 命中。请提供外部 BLAST 结果文件。"))
    next_step("下一步：导入 BLAST 结果 →", "BLAST 候选筛选")


def coverage_options(hits):
    return [field for field in COVERAGE if field in hits and hits[field].notna().any()]


def blast():
    st.title(tr("BLAST 候选筛选"))
    st.info(tr(NOTICE))
    previous = st.session_state.pop("blast_result", None)
    figures = st.session_state.setdefault("report_figures", {})
    saved_figures = {key: figures.pop(key) for key in list(figures) if key.startswith("blast_")}
    selected = source("blast", ["csv", "tsv", "txt", "tab", "out"])
    if selected is None:
        st.info(tr("请上传 BLAST 表格或载入模拟教学数据。"))
        return
    name, data, origin = selected
    if origin == "模拟教学数据":
        st.caption(tr(origin))
    file_key = sha256(data).hexdigest()
    with st.expander(tr("表格格式与字段映射"), expanded=True):
        left, right = st.columns(2)
        delimiter = left.selectbox(tr("分隔符"), ["\t", ","], index=int(name.lower().endswith(".csv")),
                                   format_func=lambda value, translate=translator(): translate({"\t": "制表符（TSV）", ",": "逗号（CSV）"}[value]),
                                   key=f"delimiter_{file_key}")
        header = right.selectbox(tr("表头"), ["auto", "yes", "no"],
                                 format_func=lambda value, translate=translator(): translate({"auto": "自动识别", "yes": "有表头", "no": "无表头"}[value]),
                                 key=f"header_{file_key}")
        try:
            raw = read_blast(data, delimiter, header)
        except ValueError as exc:
            st.error(tr(str(exc)))
            return
        st.dataframe(raw.head(5), width="stretch", hide_index=True)
        suggested = suggest_mapping(raw.columns)
        options = [None, *raw.columns]
        mapping = {}
        columns = st.columns(4)
        for index, field in enumerate((*REQUIRED, *COVERAGE)):
            selected_col = columns[index % 4].selectbox(
                field, options, index=options.index(suggested.get(field)),
                format_func=lambda value, translate=translator(): translate("未映射") if value is None else value,
                key=f"mapping_{file_key}_{ord(delimiter)}_{header}_{field}",
            )
            if selected_col is not None:
                mapping[field] = selected_col
        try:
            hits = normalize_hits(raw, mapping)
        except ValueError as exc:
            st.error(tr(str(exc)))
            return

    st.subheader(tr("筛选阈值"))
    st.caption(tr("一致性 pident 表示比对区段中相同位置的百分比；比特得分 bitscore 越高通常表示比对得分越高。"))
    presets = {"自定义筛选": None, "宽松筛选": (30.0, "1e-3", 30, 30.0),
               "严格筛选": (75.0, "1e-20", 100, 70.0)}
    preset = st.selectbox(tr("筛选预设"), presets, key="blast_preset", format_func=translator())
    if presets[preset]:
        identity_value, evalue_value, length_value, coverage_value = presets[preset]
        st.caption(f"一致性 ≥ {identity_value:g}% · E-value ≤ {evalue_value} · 比对长度 ≥ {length_value} · 覆盖度 ≥ {coverage_value:g}%（选用覆盖度字段时）")
        if st.button(tr("应用筛选预设")):
            for key, value in zip(("identity", "evalue", "alignment_length", "coverage_cutoff"), presets[preset]):
                st.session_state[key] = value
    st.caption(tr("预设用于快速试筛，阈值可调整，应结合物种、基因家族和研究目标解释。"))
    left, mid, right = st.columns(3)
    identity = left.number_input(tr("序列一致性最低值（pident，%）"), 0.0, 100.0, 0.0, step=1.0,
                                 key="identity", help="较高阈值保留更相似的比对区段。短片段即使一致性高，也可能覆盖很小。")
    evalue = mid.text_input(tr("E-value 最大值"), "1e-5", key="evalue", help="期望随机命中数，通常越低证据越强，也受数据库大小影响。支持科学计数法；0 仅保留值为 0 的命中。")
    length = right.number_input(tr("比对长度最低值（length）"), min_value=1, value=1, step=1,
                                key="alignment_length", help="提高阈值可排除短片段。比对长度与查询序列覆盖百分比是不同指标。")
    fields = coverage_options(hits)
    if fields:
        left, right = st.columns(2)
        coverage_field = left.selectbox(
            tr("Query coverage 筛选字段"), [None, *fields],
            format_func=lambda value, translate=translator(): translate("不按覆盖度筛选") if value is None else value,
            key=f"coverage_{file_key}_{fields}",
        )
        cutoff = right.number_input(tr("查询序列覆盖度最低值（%）"), 0.0, 100.0, 0.0, step=1.0,
                                    disabled=coverage_field is None, key="coverage_cutoff")
        coverage = cutoff if coverage_field else None
        st.caption(tr("qcovs 为每个 Subject 的查询序列总体覆盖度，qcovhsp 为单个 HSP 的查询序列覆盖度。启用覆盖度筛选时，缺失值不满足阈值。"))
    else:
        coverage_field = coverage = None
        st.caption(tr("本表没有可用的 Query coverage 数值。"))

    thresholds = Thresholds(identity, evalue.strip(), length, coverage_field, coverage)
    try:
        filtered = filter_hits(hits, thresholds)
    except ValueError as exc:
        st.error(tr(str(exc)))
        return
    best = best_hits(filtered)
    counts = candidate_counts(filtered, hits["qseqid"])
    fingerprint = (name, origin, file_key, delimiter, header, mapping, thresholds)
    timestamp = previous["timestamp"] if previous and previous["key"] == fingerprint else run_time()
    st.session_state["blast_result"] = {
        "key": fingerprint, "timestamp": timestamp, "name": name, "origin": origin,
        "thresholds": thresholds, "mapping": mapping, "before": len(hits), "filtered": filtered,
        "best": best, "counts": counts, "coverage_fields": fields, "delimiter": delimiter,
        "header": header,
    }

    if previous and previous["key"] == fingerprint:
        figures.update(saved_figures)
    for column, label, value in zip(st.columns(5),
                                    ("原始命中数", "筛选后命中数", "有候选的 Query", "排除记录数", "保留比例"),
                                    (len(hits), len(filtered), len(best), len(hits)-len(filtered),
                                     f"{len(filtered)/len(hits):.1%}")):
        column.metric(tr(label), value)
    if filtered.empty:
        st.warning(tr("当前阈值下没有保留的命中。"))
    result_tab, best_tab, count_tab = st.tabs(list(map(tr, ["筛选结果", "最佳命中", "各 Query 候选数"])))
    result_tab.caption(tr("点击表头按任一指标排序。E-value 按原始文本保留；可用下拉列表按数值排序。"))
    sort_field = result_tab.selectbox(tr("候选比较排序"), [None, "bitscore", "pident", "length", "evalue", *fields],
                                      format_func=lambda field, translate=translator(): field or translate("输入顺序"))
    compared = filtered if sort_field is None else filtered.sort_values(
        sort_field, ascending=sort_field == "evalue",
        key=lambda values: values.map(parse_evalue) if sort_field == "evalue" else values,
        kind="stable",
    )
    result_tab.dataframe(display_frame(compared), width="stretch", hide_index=True)
    best_tab.caption(tr("同一 Query 按 Bit score 降序、E-value 升序、Identity 降序、比对长度降序、Subject ID 升序、原始行序排序，取首条。"))
    best_tab.dataframe(display_frame(best), width="stretch", hide_index=True)
    count_tab.caption(tr("对每个 Query 统计筛选后唯一的 Subject ID，保留候选数为 0 的 Query。"))
    count_tab.dataframe(display_frame(counts), width="stretch", hide_index=True)
    if len(filtered) < len(hits) and st.checkbox(tr("查看排除原因")):
        st.dataframe(rejection_reasons(hits, thresholds), width="stretch", hide_index=True)
    next_step("下一步：结果可视化 →", "结果可视化")


def plot_distribution(frame, key, field, title, id_field):
    mode = st.selectbox(f"{tr(title)} · {tr('图形')}", ["自动", "柱状图", "散点图", "直方图"], key=f"chart_mode_{key}", format_func=translator())
    histogram = mode == "直方图" or (mode == "自动" and len(frame) > 20)
    hover_fields = ("序列 ID", "序列类型", "序列长度", "qseqid", "sseqid", "bitscore", "evalue")
    hover = [name for name in hover_fields if name in frame and name != field]
    chart_panel(
        key, lambda grouped: charts.distribution(frame, field, title, id_field, mode, grouped, hover),
        frame, ChartStyle(title, title if histogram else id_field, "记录数" if histogram else title),
        groupable="qseqid" in frame,
    )


def visualization():
    st.title(tr("结果可视化"))
    result = st.session_state.get("blast_result")
    if result is None:
        st.info(tr("请先在 BLAST 候选筛选页载入表格并完成筛选。"))
        return
    hits = result["filtered"]
    st.caption(f'{result["name"]} · {tr(result["origin"])} · {tr("当前筛选结果")}')
    comparison = pd.DataFrame({"阶段": ["筛选前", "筛选后"], "命中数量": [result["before"], len(hits)]})
    chart_panel("blast_comparison", lambda _: charts.hit_comparison(result["before"], len(hits)), comparison,
                ChartStyle("筛选前后命中数量", "阶段", "命中数量", legend=False, legend_title="", category_colors=True))
    counts = result["counts"]
    chart_panel("blast_candidates", lambda grouped: charts.query_bars(counts, grouped), counts,
                ChartStyle("各 Query 候选数量", "Query", "候选数量"), groupable=True)
    if hits.empty:
        st.info(tr("当前没有保留的命中可用于分布图。"))
        next_step("下一步：导出分析报告 →", "分析记录与导出")
        return
    plots = st.tabs(list(map(tr, ["序列一致性", "比对长度", "覆盖度散点"])))
    with plots[0]:
        plot_distribution(hits, "blast_identity", "pident", "序列一致性（%）", "sseqid")
    with plots[1]:
        plot_distribution(hits, "blast_length", "length", "比对长度", "sseqid")
    with plots[2]:
        fields = coverage_options(hits)
        if fields:
            field = st.selectbox(tr("绘图覆盖度字段"), fields, key="chart_coverage")
            chart_panel(f"blast_scatter_{field}", lambda grouped: charts.coverage_scatter(hits, field, grouped),
                        hits.dropna(subset=[field]),
                        ChartStyle("一致性与覆盖度", "序列一致性（%）", f"查询覆盖度（{field}，%）", query_colors=True),
                        groupable=True)
        else:
            st.info(tr("当前命中没有可用于绘图的覆盖度。"))
    next_step("下一步：导出分析报告 →", "分析记录与导出")


def records():
    st.title(tr("分析记录与导出"))
    blast_result = st.session_state.get("blast_result")
    metadata = {}
    for label in (*METADATA, "数据库登录号"):
        if not blast_result and label in ("BLAST 程序及版本", "参考数据库及版本"):
            continue
        widget = st.text_area if label == "分析备注" else st.text_input
        metadata[label] = widget(tr("研究说明与备注（可选）" if label == "分析备注" else label), key=f"research_{label}")
        if label in ("BLAST 程序及版本", "参考数据库及版本") and not metadata[label].strip():
            metadata[label] = "未提供"
    fasta_result = st.session_state.get("fasta_result")
    blast_result = st.session_state.get("blast_result")
    pairwise_record = st.session_state.get("pairwise_record")
    record = build_record(metadata, fasta_result, blast_result, pairwise_record)
    save_button()
    st.subheader(tr("当前分析记录"))
    for module in ("FASTA", "BLAST", "成对序列比对"):
        if module in record:
            st.markdown(f"**{tr(module)}**")
            st.caption(" · ".join(f"{tr(key)}: {tr(value)}" for key, value in record[module].items()
                                  if key in ("上传文件名称", "序列数", "最短序列", "最长序列", "原始命中数",
                                             "筛选后命中数", "保留比例", "比对列数")))
    with st.expander(tr("原始 JSON")):
        st.json(record)
    st.download_button(tr("下载分析记录 JSON"), json_bytes(record), "analysis.json", "application/json")
    if blast_result:
        filtered = blast_result["filtered"]
        st.download_button(tr("下载 BLAST 筛选结果 CSV"), csv_bytes(filtered), "blast_filtered.csv", "text/csv")
        st.download_button(
            tr("下载候选基因 Excel"), excel_bytes(filtered, blast_result["best"], record),
            "candidates.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


    if fasta_result or blast_result or pairwise_record:
        report_section(record, blast_result)


def report_section(record, blast_result):
    st.subheader(tr("Word 分析报告"))
    left, right = st.columns(2)
    language = left.selectbox(tr("报告语言"), ("zh", "en"),
                              format_func={"zh": "中文报告", "en": "English Report"}.get,
                              key="report_setting_language")
    mode = right.selectbox(tr("报告模式"), ("full", "concise"),
                           format_func=lambda key, translate=translator(): translate("完整版" if key == "full" else "简洁版"),
                           key="report_setting_mode")
    title = st.text_input(tr("报告标题"), max_chars=200, key="report_setting_title")
    background = st.text_area(tr("研究背景"), max_chars=5000, key="report_setting_background")
    notes = record["科研信息"].get("分析备注", "")
    figures = st.session_state.get("report_figures", {})
    if static_images_enabled():
        selected_figures = st.multiselect(tr("插入图表"), list(figures), format_func=lambda key: tr(figures[key][0]))
    else:
        selected_figures = []
        st.caption(tr("轻量预览支持 Word 文字与表格。带图报告请使用本地或 Docker 版本。"))
    if static_images_enabled() and not figures:
        st.caption(tr("访问 FASTA 或结果可视化页面后，可在此选择已生成的图表。"))
    metrics = {}
    tables = {}
    if blast_result:
        hits = blast_result["filtered"]
        tables = {"候选基因列表": hits, "各 Query 候选数量": blast_result["counts"],
                  "最佳命中": blast_result["best"]}
        total = blast_result["before"]
        metrics = {"原始命中数": total, "筛选后命中数": len(hits), "保留比例": f"{len(hits)/total:.1%}"}
        if not hits.empty:
            coverage_fields = coverage_options(hits)
            if coverage_fields:
                coverage = coverage_fields[0]
                low_coverage = int(((hits["pident"] >= 90) & (hits[coverage] < 50)).sum())
                metrics[f'{tr("高一致性且低覆盖度命中", language)} (pident ≥ 90%, {coverage} < 50%)'] = low_coverage
            metrics.update({"一致性中位数（%）": f"{hits['pident'].median():.2f}",
                            "比对长度中位数": f"{hits['length'].median():g}",
                            "比特得分中位数": f"{hits['bitscore'].median():g}"})
    chosen = st.multiselect(tr("导出结果表"), list(tables), default=list(tables), format_func=translator())
    try:
        images = []
        for key in selected_figures:
            chart_title, original = figures[key]
            figure = type(original)(original)
            figure.update_layout(title_text=tr(chart_title, language))
            axes = (figure.layout.xaxis, figure.layout.yaxis)
            source_labels = (figure.layout.meta or {}).get("axis_source", [axis.title.text for axis in axes])
            for axis, label in zip(axes, source_labels):
                axis.title.text = tr(label, language)
            images.append((chart_title, image_bytes(figure, "png")))
        report_title = tr(title.strip() or "PlantLab-GeneMiner 分析报告", language)
        output = word_report(report_title, background, notes,
                             record, metrics, {key: tables[key] for key in chosen}, images, language, mode)
    except Exception:
        st.error(tr("Word 报告生成失败。若选了图表，请检查 Kaleido 与 Chromium，或取消插图后重试。"))
    else:
        st.session_state["last_report"] = output
        st.caption(f'{tr("当前报告已就绪")} · {report_title}')
        st.download_button(tr("下载 Word 报告"), output, "plantlab_geneminer_report.docx",
                           "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                           on_click="ignore", type="primary", key="current_word_report")

def about():
    brand_banner()
    st.subheader(tr("植物功能基因挖掘与多维证据分析平台"))
    st.write(tr("面向植物生物信息学，为教学和科研提供可复查的候选基因筛选、数据可视化与结果交流工作流。"))
    st.subheader(tr("当前功能"))
    cards = (
        ("FASTA 序列分析", "检查序列、统计长度和核酸 GC 含量。"),
        ("BLAST 结果筛选", "映射字段、设置阈值并比较候选命中。"),
        ("成对序列比对", "对两条核酸或蛋白质序列执行全局或局部比对。"),
        ("结果可视化", "比较分布、覆盖度与各 Query 的候选数量。"),
        ("图表编辑与导出", "编辑 Plotly 样式并下载图像、HTML、CSV 或 JSON 配置。"),
        ("分析记录与报告", "导出可复查的参数、候选表和带图的 Word 报告。"),
    )
    for index in range(0, len(cards), 3):
        for column, (title, description) in zip(st.columns(3), cards[index:index + 3]):
            with column.container(border=True):
                st.markdown(f"**{tr(title)}**")
                st.write(tr(description))
    st.subheader(tr("开始使用"))
    st.write(tr("适合植物科学专业本科生、研究生、生物信息学初学者及科研人员。"))
    st.write(tr("上传数据 → 检查数据 → 设置参数 → 执行分析 → 查看结果 → 导出文件"))
    st.subheader(tr("项目信息"))
    st.write(f"{tr('当前版本')} {VERSION}")
    st.caption(tr("开发者信息待补充。"))
    st.link_button(tr("GitHub 项目"), "https://github.com/xsun27674-commits/PlantLab-GeneMiner")
    st.link_button(tr("问题反馈"), "https://github.com/xsun27674-commits/PlantLab-GeneMiner/issues")
    st.subheader(tr("使用须知"))
    st.info(tr(NOTICE))
    st.write(tr("上传内容及分析结果仅在当前会话中处理。模拟教学数据不用于真实生物学推断。多维证据综合评分和 BLAST+ 数据库搜索列入后续开发。"))
