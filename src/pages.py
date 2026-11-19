"""Chinese Streamlit views for the analysis workflow."""

from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import streamlit as st

from src import visualization as charts
from src.blast_utils import (
    COVERAGE, REQUIRED, Thresholds, best_hits, candidate_counts, filter_hits,
    normalize_hits, read_blast, suggest_mapping,
)
from src.export_utils import csv_bytes, excel_bytes, json_bytes
from src.fasta_utils import analyze_fasta

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
    use_example = st.checkbox("载入模拟教学数据", key=f"{kind}_example")
    if use_example:
        return name, path.read_bytes(), "模拟教学数据"
    widget_key = f"{kind}_upload"
    cache_key = f"{kind}_source"

    def remember_upload():
        upload = st.session_state[widget_key]
        st.session_state[cache_key] = (
            (upload.name, upload.getvalue(), "用户上传") if upload is not None else None
        )

    upload = st.file_uploader(f"上传{label}", type=extensions, key=widget_key,
                              on_change=remember_upload)
    cached = st.session_state.get(cache_key)
    if upload is None and cached is not None:
        st.caption(f"当前文件 · {cached[0]}")
        if st.button("清除当前文件", key=f"clear_{kind}"):
            st.session_state.pop(cache_key)
            return None
    return cached


def home():
    st.title("PlantLab-GeneMiner")
    st.subheader("面向植物功能基因挖掘的候选基因筛选与分析平台")
    st.write("管理植物序列、审查 BLAST 命中并记录可复查的筛选参数。")
    steps = st.columns(5)
    for column, (title, description) in zip(steps, (
        ("FASTA 序列", "检查 ID、长度和字符"),
        ("BLAST 导入", "确认字段映射"),
        ("候选筛选", "设置阈值并查看最佳命中"),
        ("数据可视化", "检查分布和候选数量"),
        ("结果导出", "下载结果与分析记录"),
    )):
        with column.container(border=True):
            st.markdown(f"**{title}**")
            st.caption(description)
    st.subheader("模拟教学数据")
    st.write("示例序列为人工生成，命中表包含 60 条模拟记录。可下载文件，或在对应页面直接载入。")
    for column, (name, label) in zip(st.columns(2), EXAMPLES.values()):
        column.download_button(f"下载{label}", (DATA / name).read_bytes(), name, "text/plain")
    st.info(NOTICE)


def run_time():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fasta():
    st.title("FASTA 序列分析")
    previous = st.session_state.pop("fasta_result", None)
    selected = source("fasta", ["fasta", "fa", "fna", "faa", "fas", "txt"])
    labels = {"nucleotide": "核酸", "protein": "蛋白质"}
    sequence_type = st.radio("序列类型", labels, index=None, format_func=labels.get,
                             horizontal=True, key="sequence_type")
    if selected is None or sequence_type is None:
        st.info("请载入 FASTA 文件并明确选择序列类型。")
        return
    name, data, origin = selected
    fingerprint = (name, sha256(data).hexdigest(), origin, sequence_type)
    try:
        frame = analyze_fasta(data, sequence_type)
    except ValueError as exc:
        st.error(str(exc))
        return
    timestamp = previous["分析时间（UTC）"] if previous and previous["key"] == fingerprint else run_time()
    st.session_state["fasta_result"] = {
        "key": fingerprint, "上传文件名称": name, "文件来源": origin, "序列类型": labels[sequence_type],
        "分析时间（UTC）": timestamp, "序列数": len(frame),
    }
    if origin == "模拟教学数据":
        st.caption(origin)
    duplicate_count = int(frame["重复 ID"].sum())
    invalid_count = int(frame["非法字符"].ne("").sum())
    empty_count = int(frame["空序列"].sum())
    for column, label, value in zip(st.columns(4), ("序列数", "重复 ID 记录", "非法字符记录", "空序列"),
                                    (len(frame), duplicate_count, invalid_count, empty_count)):
        column.metric(label, value)
    if duplicate_count or invalid_count or empty_count:
        st.warning("请检查表中标记的重复 ID、非法字符和空序列。")
    if sequence_type == "nucleotide":
        st.caption("GC 使用 Biopython 的模糊碱基排除规则，S 与 W 按已知 GC 类别计入。无法计算时留空。")
    st.dataframe(frame, width="stretch", hide_index=True)
    st.plotly_chart(charts.histogram(frame, "序列长度"), width="stretch")
    st.download_button("下载 FASTA 序列统计 CSV", csv_bytes(frame), "fasta_statistics.csv", "text/csv")


def coverage_options(hits):
    return [field for field in COVERAGE if field in hits and hits[field].notna().any()]


def blast():
    st.title("BLAST 候选筛选")
    st.info(NOTICE)
    previous = st.session_state.pop("blast_result", None)
    selected = source("blast", ["csv", "tsv", "txt", "tab", "out"])
    if selected is None:
        st.info("请上传 BLAST 表格或载入模拟教学数据。")
        return
    name, data, origin = selected
    if origin == "模拟教学数据":
        st.caption(origin)
    file_key = sha256(data).hexdigest()
    with st.expander("表格格式与字段映射", expanded=True):
        left, right = st.columns(2)
        delimiter = left.selectbox("分隔符", ["\t", ","], index=int(name.lower().endswith(".csv")),
                                   format_func={"\t": "制表符（TSV）", ",": "逗号（CSV）"}.get,
                                   key=f"delimiter_{file_key}")
        header = right.selectbox("表头", ["auto", "yes", "no"],
                                 format_func={"auto": "自动识别", "yes": "有表头", "no": "无表头"}.get,
                                 key=f"header_{file_key}")
        try:
            raw = read_blast(data, delimiter, header)
        except ValueError as exc:
            st.error(str(exc))
            return
        st.dataframe(raw.head(5), width="stretch", hide_index=True)
        suggested = suggest_mapping(raw.columns)
        options = [None, *raw.columns]
        mapping = {}
        columns = st.columns(4)
        for index, field in enumerate((*REQUIRED, *COVERAGE)):
            selected_col = columns[index % 4].selectbox(
                field, options, index=options.index(suggested.get(field)),
                format_func=lambda value: "未映射" if value is None else value,
                key=f"mapping_{file_key}_{ord(delimiter)}_{header}_{field}",
            )
            if selected_col is not None:
                mapping[field] = selected_col
        try:
            hits = normalize_hits(raw, mapping)
        except ValueError as exc:
            st.error(str(exc))
            return

    st.subheader("筛选阈值")
    left, mid, right = st.columns(3)
    identity = left.number_input("Identity 最低值 (%)", 0.0, 100.0, 0.0, step=1.0, key="identity")
    evalue = mid.text_input("E-value 最大值", "1e-5", key="evalue", help="支持科学计数法，0 仅保留 E-value 为 0 的命中。")
    length = right.number_input("Alignment length 最低值", min_value=1, value=1, step=1, key="alignment_length")
    fields = coverage_options(hits)
    if fields:
        left, right = st.columns(2)
        coverage_field = left.selectbox(
            "Query coverage 筛选字段", [None, *fields],
            format_func=lambda value: "不按覆盖度筛选" if value is None else value,
            key=f"coverage_{file_key}_{fields}",
        )
        cutoff = right.number_input("Query coverage 最低值 (%)", 0.0, 100.0, 0.0, step=1.0,
                                    disabled=coverage_field is None, key="coverage_cutoff")
        coverage = cutoff if coverage_field else None
        st.caption("qcovs 为相同 Subject 的查询覆盖度，qcovhsp 为单条比对覆盖度。启用覆盖度筛选时，缺失值不满足阈值。")
    else:
        coverage_field = coverage = None
        st.caption("本表没有可用的 Query coverage 数值。")

    thresholds = Thresholds(identity, evalue.strip(), length, coverage_field, coverage)
    try:
        filtered = filter_hits(hits, thresholds)
    except ValueError as exc:
        st.error(str(exc))
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

    for column, label, value in zip(st.columns(3), ("原始命中数", "筛选后命中数", "有候选的 Query"),
                                    (len(hits), len(filtered), len(best))):
        column.metric(label, value)
    if filtered.empty:
        st.warning("当前阈值下没有保留的命中。")
    result_tab, best_tab, count_tab = st.tabs(["筛选结果", "最佳命中", "各 Query 候选数"])
    result_tab.dataframe(filtered, width="stretch", hide_index=True)
    best_tab.caption("同一 Query 按 Bit score 降序、E-value 升序、Identity 降序、比对长度降序、Subject ID 升序、原始行序排序，取首条。")
    best_tab.dataframe(best, width="stretch", hide_index=True)
    count_tab.caption("对每个 Query 统计筛选后唯一的 Subject ID，保留候选数为 0 的 Query。")
    count_tab.dataframe(counts, width="stretch", hide_index=True)


def visualization():
    st.title("结果可视化")
    result = st.session_state.get("blast_result")
    if result is None:
        st.info("请先在 BLAST 候选筛选页载入表格并完成筛选。")
        return
    hits = result["filtered"]
    st.caption(f'{result["name"]} · {result["origin"]} · 当前筛选结果')
    left, right = st.columns(2)
    with left:
        st.subheader("筛选前后命中数量")
        st.plotly_chart(charts.hit_comparison(result["before"], len(hits)), width="stretch")
    with right:
        st.subheader("各 Query 候选数量")
        st.plotly_chart(charts.query_bars(result["counts"]), width="stretch")
    if hits.empty:
        st.info("当前没有保留的命中可用于分布图。")
        return
    for column, label, field in zip(st.columns(2), ("Identity 分布", "Alignment length 分布"),
                                    ("pident", "length")):
        with column:
            st.subheader(label)
            st.plotly_chart(charts.histogram(hits, field), width="stretch")
    fields = coverage_options(hits)
    if fields:
        st.subheader("Identity 与 Query coverage")
        field = st.selectbox("绘图覆盖度字段", fields)
        st.plotly_chart(charts.coverage_scatter(hits, field), width="stretch")
    elif result["coverage_fields"]:
        st.caption("筛选后命中均缺少覆盖度数值。")


def records():
    st.title("分析记录与导出")
    metadata = {}
    for label in METADATA:
        widget = st.text_area if label == "分析备注" else st.text_input
        metadata[label] = widget(label, key=f"research_{label}")
    record = {"科研信息": metadata}
    fasta_result = st.session_state.get("fasta_result")
    blast_result = st.session_state.get("blast_result")
    if fasta_result:
        record["FASTA"] = {key: value for key, value in fasta_result.items() if key != "key"}
    if blast_result:
        record["BLAST"] = {
            "上传文件名称": blast_result["name"], "文件来源": blast_result["origin"],
            "分析时间（UTC）": blast_result["timestamp"], "原始命中数": blast_result["before"],
            "筛选后命中数": len(blast_result["filtered"]), "分隔符": blast_result["delimiter"],
            "表头模式": blast_result["header"],
        }
        record["字段映射"] = blast_result["mapping"]
        record["筛选阈值"] = asdict(blast_result["thresholds"])
    st.subheader("当前分析记录")
    st.json(record, expanded=1)
    st.download_button("下载分析记录 JSON", json_bytes(record), "analysis.json", "application/json")
    if blast_result:
        filtered = blast_result["filtered"]
        st.download_button("下载 BLAST 筛选结果 CSV", csv_bytes(filtered), "blast_filtered.csv", "text/csv")
        st.download_button(
            "下载候选基因 Excel", excel_bytes(filtered, blast_result["best"], record),
            "candidates.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


def about():
    st.title("关于平台")
    st.write("PlantLab-GeneMiner V1.0 · 面向植物科学研究的候选基因筛选工具。")
    st.info(NOTICE)
    st.write("平台读取已有 BLAST 表格。上传数据与分析记录保存在当前 Streamlit 会话，需下载以长期保存。")
    st.write("模拟教学数据用于演示软件操作，不能用于生物学推断。")
