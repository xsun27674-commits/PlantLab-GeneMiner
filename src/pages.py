"""Chinese Streamlit views for the analysis workflow."""

from html import escape
import csv
from io import BytesIO
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
from src.batch_alignment_page import export_metadata
from src.local_blast import FIELDS as LOCAL_BLAST_FIELDS, SEARCH_EVALUE, executable_paths, run_local_blast, valid_records
from src.fasta_utils import analyze_fasta
from src.sequence_input import read_sequence_table, table_to_fasta
from src.ncbi_page import ncbi_link, ncbi_source
from src.project_data import classify_table, clear_sequence_project, current_candidates, invalidate_sequence_results, project_status, record_info, record_labels, project_gene_count, register_sequences, sequence_columns, table_metadata
from src.timing import elapsed, session_result

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
    widget_key = f"{kind}_upload_{st.session_state.get('fasta_upload_revision', 0)}" if kind == "fasta" else f"{kind}_upload"
    cache_key = f"{kind}_source"

    def invalidate_source():
        if kind == "fasta":
            invalidate_sequence_results()
            st.session_state.pop("sequence_ncbi_applied", None)
        else:
            st.session_state.pop("blast_result", None)
            st.session_state.pop("last_report", None)
            for key in list(st.session_state.get("report_figures", {})):
                if key.startswith("blast_"):
                    st.session_state["report_figures"].pop(key)

    def remember_upload():
        upload = st.session_state[widget_key]
        selected = None
        if upload is not None:
            content = upload.getvalue()
            origin = "模拟教学数据" if content == path.read_bytes() else "用户上传"
            selected = (upload.name, content, origin)
        if selected != st.session_state.get(cache_key):
            invalidate_source()
        st.session_state[cache_key] = selected

    upload = st.file_uploader(f"{tr('上传')} {tr(label)}", type=extensions, key=widget_key,
                              on_change=remember_upload)
    cached = st.session_state.get(cache_key)
    if upload is None and cached is not None:
        st.caption(f'{tr("当前文件")} · {cached[0]}')
        if st.button(tr("清除当前文件"), key=f"clear_{kind}"):
            st.session_state.pop(cache_key)
            invalidate_source()
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
        with illustration:
            st.html(f'<img class="plantlab-hero-art" src="{brand_mark_uri()}" alt="">')

    project = st.session_state.get("project_sequences")
    if project:
        name = st.session_state.get("project_name") or project["name"]
        st.caption(f'{tr("当前项目")} · {name} · {tr("基因数")} {project_gene_count(project)} · '
                   f'{tr("序列数")} {len(project["records"])}')
    else:
        st.caption(tr("当前项目尚未导入序列。"))
    cards = (
        ("local", "序列比较与相似性筛选", "比较已上传 DNA 序列的相同与差异，分析序列一致性，并筛选相似序列。",
         "开始本地分析", "FASTA 序列分析"),
        ("blast", "BLAST 搜索与候选筛选", "选择参考序列和目标序列集合，通过 BLAST 搜索相似序列并筛选候选结果。",
         "开始 BLAST 分析", "BLAST 搜索"),
    )
    for column, (path, title, description, action, destination) in zip(st.columns(2), cards):
        with column.container(key=f"home_path_{path}", border=True):
            st.subheader(tr(title))
            st.write(tr(description))
            if st.button(tr(action), key=f"home_{path}", type="primary"):
                st.session_state["workflow_path"] = path
                st.session_state["result_view"] = path
                ready = project if path == "local" else project_nucleotide_records(project)
                navigate(destination if ready else "数据导入与管理")


def run_time():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sequence_source():
    st.session_state.pop("_sequence_table_is_cds", None)
    st.session_state.pop("_sequence_input_metadata", None)
    ncbi_link()
    mode = st.radio(tr("序列输入方式"), ("upload", "grid"), key="sequence_input_mode",
                    format_func={"upload": tr("上传文件"), "grid": tr("在线表格")}.get,
                    horizontal=True)
    if mode == "upload":
        upload = source("fasta", ["fasta", "fa", "fna", "faa", "fas", "txt", "csv", "xlsx", "zip"])
        if upload and Path(upload[0]).suffix.lower() == ".zip":
            return ncbi_source(upload[0], upload[1])
        if not upload or Path(upload[0]).suffix.lower() not in (".csv", ".xlsx"):
            return upload
        name, data, origin = upload
        rows = session_result("sequence_table", (name, sha256(data).digest()), read_sequence_table, name, data)
        options = list(rows.columns)
        kind, _ = classify_table(options)
        st.session_state["_sequence_input_metadata"] = table_metadata(rows, include_source=True)
        if kind in ("blast", "incomplete_blast", "pairwise"):
            raise ValueError("该表不是序列数据。请上传包含 Sequence ID 和 Sequence 的表格。")
        ids, sequences = sequence_columns(options)
        if not ids or not sequences:
            raise ValueError("序列表缺少 Sequence ID 或 Sequence 列。")
        if len(ids) == len(sequences) == 1:
            evidence = any(str(column).strip().casefold().replace(" ", "") == "length(bp)" for column in options)
            st.session_state["_sequence_table_is_cds"] = evidence or str(sequences[0]).casefold() in {"cds", "cds sequence"}
            st.caption(tr("已识别序列表。"))
            canonical = session_result("sequence_canonical", (name, sha256(data).digest(), ids[0], sequences[0]),
                                       table_to_fasta, rows, ids[0], sequences[0])
            return name, canonical, origin
        suffix = sha256(data).hexdigest()
        left, right = st.columns(2)
        identifier = left.selectbox(tr("序列编号列"), options, key=f"mapping_seqid_{suffix}",
                                    index=options.index(ids[0]))
        sequence = right.selectbox(tr("序列内容列"), options, key=f"mapping_sequence_{suffix}",
                                   index=options.index(sequences[0]))
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


def next_step(label, destination, *, status=None, summary=None, result_view=None):
    with st.container(key="workflow_step"):
        message, action = st.columns([3, 2], vertical_alignment="center")
        with message:
            if status:
                st.markdown(f"**{tr(status)}**")
            if summary:
                st.caption(tr(summary))
        with action:
            if st.button(tr(label), key=f"workflow_next_{destination}", type="primary"):
                if result_view:
                    st.session_state["result_view"] = result_view
                if destination == "结果可视化":
                    st.session_state["result_section"] = "结果可视化"
                if destination == "成对序列比对":
                    st.session_state["alignment_setting_view"] = "当前项目"
                navigate(destination)


def sequence_data_page():
    st.title(tr("数据导入与管理"))
    project_status()
    if st.session_state.get("project_sequences"):
        st.button(tr("清空当前序列数据"), on_click=clear_sequence_project)
    previous = st.session_state.get("fasta_result")
    try:
        selected = sequence_source()
    except ValueError as exc:
        st.error(tr(str(exc)))
        return
    labels = {"nucleotide": "核酸", "protein": "蛋白质"}
    cached_upload = st.session_state.get("fasta_source")
    pending_ncbi = (
        st.session_state.get("sequence_input_mode") == "upload" and
        not st.session_state.get("fasta_example") and cached_upload and
        Path(cached_upload[0]).suffix.lower() == ".zip"
    )
    if pending_ncbi and selected is None:
        return
    if selected is None:
        if st.session_state.get("project_sequences"):
            data_next_step()
        else:
            st.info(tr("请载入 FASTA 文件并明确选择序列类型。"))
        return
    if selected[2] == "NCBI Datasets" or st.session_state.get("_sequence_table_is_cds"):
        sequence_type = "nucleotide"
        st.caption(tr("已识别为核酸序列数据。"))
    else:
        sequence_type = st.radio(tr("序列类型"), labels, index=None,
                                 format_func=lambda key, translate=translator(): translate(labels[key]),
                                 horizontal=True, key="sequence_type", on_change=invalidate_sequence_results)
    if sequence_type is None:
        st.info(tr("请载入 FASTA 文件并明确选择序列类型。"))
        return
    name, data, origin = selected
    metadata = st.session_state.get("_sequence_input_metadata", ())
    fingerprint = (name, sha256(data).hexdigest(), origin, sequence_type,
                   sha256(repr(metadata).encode()).hexdigest())
    try:
        frame = session_result("fasta_parse", fingerprint, analyze_fasta, data, sequence_type)
    except ValueError as exc:
        st.error(tr(str(exc)))
        return
    register_sequences(fingerprint, name, origin, sequence_type, data, metadata)
    timestamp = previous["分析时间（UTC）"] if previous and previous["key"] == fingerprint else run_time()
    st.session_state["fasta_result"] = {
        "key": fingerprint, "上传文件名称": name, "文件来源": origin, "序列类型": labels[sequence_type],
        "分析时间（UTC）": timestamp, "序列数": len(frame),
        "最短序列": int(frame["序列长度"].min()), "最长序列": int(frame["序列长度"].max()),
        "统计数据": frame,
        "重复 ID 记录数": int(frame["重复 ID"].sum()),
        "非法字符记录数": int(frame["非法字符"].ne("").sum()),
    }
    st.success(f'{tr("序列已保存到当前项目")} · {len(frame)} {tr("条序列")}')
    data_next_step()


def data_next_step():
    if st.session_state.get("workflow_path") == "blast":
        if project_nucleotide_records(st.session_state.get("project_sequences")):
            next_step("下一步：BLAST 搜索 →", "BLAST 搜索")
        else:
            st.info(tr("BLAST 搜索需要当前项目中的有效核酸序列。"))
    else:
        next_step("下一步：FASTA 序列统计 →", "FASTA 序列分析")


def fasta():
    st.title(tr("FASTA 序列统计"))
    project_status()
    result = st.session_state.get("fasta_result")
    project = st.session_state.get("project_sequences")
    if not project:
        st.info(tr("请先导入序列，再查看 FASTA 统计。"))
        next_step("前往数据导入 →", "数据导入与管理")
        return
    name, origin, sequence_type = (project[key] for key in ("name", "origin", "type"))
    labels = {"nucleotide": "核酸", "protein": "蛋白质"}
    if result and result["key"] == project["key"] and "统计数据" in result:
        frame = result["统计数据"]
    else:
        canonical = "".join(f">{identifier}\n{sequence}\n" for identifier, sequence in project["records"])
        frame = session_result("fasta_parse", project["key"], analyze_fasta, canonical.encode(), sequence_type)
    if st.button(tr("← 返回数据导入与管理")):
        navigate("数据导入与管理")
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
    project = st.session_state["project_sequences"]
    named = frame.assign(**{tr("行号"): range(1, len(frame) + 1)})
    named.insert(1, "显示名称", record_labels(project))
    identifiers = [record_info(project, idx) for idx in range(len(frame))]
    for key, label in (("original", "Original Sequence ID"), ("gene", "Gene"), ("accession", "Accession"), ("id", "Internal ID")):
        named[label] = [item[key] or tr("待核实") for item in identifiers]
    st.dataframe(display_frame(named), width="stretch", hide_index=True)
    frame = frame.assign(序列类型=labels[sequence_type])
    plot_distribution(frame, "fasta_length", "序列长度", "序列长度", "序列 ID")
    if sequence_type == "nucleotide" and frame["GC (%)"].notna().any():
        plot_distribution(frame.dropna(subset=["GC (%)"]), "fasta_gc", "GC (%)", "GC 含量", "序列 ID")
    st.download_button(tr("下载 FASTA 序列统计 CSV"), csv_bytes(named.assign(**{"Source file": name, "Origin": origin})), "fasta_statistics.csv", "text/csv")
    if sequence_type == "nucleotide" and len(frame) >= 2:
        next_step("下一步：成对序列比对 →", "成对序列比对",
                  status="序列分析已完成 ✓",
                  summary="当前序列已保存到项目，可直接进行本地比对。")
    else:
        st.caption(tr("当前序列已保存。批量比对需要至少两条核酸记录。"))


def coverage_options(hits):
    return [field for field in COVERAGE if field in hits and hits[field].notna().any()]


def reject_blast_table(kind, missing):
    if kind in ("sequence", "incomplete_sequence"):
        raise ValueError("已识别为核酸序列数据。请在 FASTA 序列分析或本地序列比对中使用。")
    if kind == "pairwise":
        raise ValueError("本地比对结果缺少 BLAST bitscore 和 E-value，请在成对序列比对中查看。")
    raise ValueError("BLAST 表格缺少必需字段：" + "、".join(missing))


LOCAL_BLAST = "项目内本地 BLAST"
EXTERNAL_BLAST = "外部 BLAST 命中表"


def project_blast(project, records):
    st.info(tr("当前运行的是项目内本地 BLAST，仅搜索用户上传的序列，不代表搜索整个 NCBI 数据库。"))
    labels = record_labels(project)
    available = list(records)
    try:
        executable_paths()
        unavailable = None
    except ValueError as exc:
        unavailable = str(exc)
        st.warning(tr(unavailable))
    with st.form("project_blast_search"):
        st.caption(tr("查询或目标留空时使用全部有效序列。"))
        if len(records) != len(project["records"]):
            st.warning(tr("空序列或含非法字符的记录已排除。"))
        cols = st.columns(2)
        queries = cols[0].multiselect(tr("查询序列（默认全部）"), available, format_func=labels.__getitem__,
                                      key="local_blast_queries")
        targets = cols[1].multiselect(tr("目标序列（默认全部）"), available, format_func=labels.__getitem__,
                                      key="local_blast_targets")
        run = st.form_submit_button(tr("使用当前序列运行 BLAST"), type="primary", disabled=unavailable is not None)
    queries, targets = tuple(queries or available), tuple(targets or available)
    previous = st.session_state.get("local_blast_run")
    if previous and previous["key"][0] != project["key"]:
        previous = None
    if run and (not previous or previous["key"] != (project["key"], queries, targets)):
        try:
            with st.spinner(tr("正在建立项目数据库并运行 blastn…"), show_time=True):
                result = run_local_blast(project, records, queries, targets)
        except ValueError as exc:
            st.error(tr(str(exc)))
            if previous:
                st.caption(tr("以下显示上次成功的搜索结果。"))
        else:
            previous = {**result, "timestamp": run_time()}
            st.session_state["local_blast_run"] = previous
            st.session_state.pop("blast_result", None)
            st.session_state.pop("_prepared_word_blast", None)
            for key in list(st.session_state.get("report_figures", {})):
                if key.startswith("blast_"):
                    st.session_state["report_figures"].pop(key)
    if previous is None:
        return None

    hits = previous["hits"]
    st.success(f'{tr("本地 BLAST 已完成")} · {previous["version"]} · {len(hits)} {tr("条命中")}')
    st.caption(f'{tr("查询序列数")} {previous["query_count"]} · {tr("目标序列数")} {previous["target_count"]} · '
               f'BLAST E-value ≤ {SEARCH_EVALUE} · max_hsps=5')
    st.download_button(tr("下载本地 BLAST 原始命中表（TSV）"),
                       hits.to_csv(index=False, sep="\t").encode(), "local_blast_hits.tsv",
                       "text/tab-separated-values", on_click="ignore")
    return previous


def external_blast(selected):
    name, data, origin = selected
    if origin == "模拟教学数据":
        st.caption(tr(origin))
    file_key = sha256(data).hexdigest()
    with st.expander(tr("表格格式与字段映射"), expanded=True):
        sheet = name.lower().endswith(".xlsx")
        left, right = st.columns(2)
        delimiter = left.selectbox(tr("分隔符"), ["\t", ","], index=int(name.lower().endswith(".csv")),
                                   format_func=lambda value, translate=translator(): translate({"\t": "制表符（TSV）", ",": "逗号（CSV）"}[value]),
                                   key=f"delimiter_{file_key}", disabled=sheet)
        header = right.selectbox(tr("表头"), ["auto", "yes", "no"],
                                 format_func=lambda value, translate=translator(): translate({"auto": "自动识别", "yes": "有表头", "no": "无表头"}[value]),
                                 key=f"header_{file_key}", disabled=sheet)
        try:
            if sheet:
                raw = session_result("blast_excel", file_key, read_sequence_table, name, data, True)
            else:
                lines = (line.decode("utf-8-sig") for line in BytesIO(data)
                         if line.strip() and not line.lstrip().startswith(b"#"))
                first_row = next(csv.reader(lines, delimiter=delimiter), [])
                kind, missing = classify_table(first_row)
                if kind in ("sequence", "incomplete_sequence", "pairwise", "incomplete_blast"):
                    reject_blast_table(kind, missing)
                raw = session_result("blast_parse", (file_key, delimiter, header), read_blast, data, delimiter, header)
            kind, missing = classify_table(raw.columns)
            if kind != "blast":
                reject_blast_table(kind, missing)
        except (ValueError, csv.Error) as exc:
            st.error(tr(str(exc)))
            return None
        st.dataframe(raw.head(5), width="stretch", hide_index=True)
        suggested = suggest_mapping(raw.columns)
        if all(field in suggested for field in REQUIRED):
            mapping = suggested
            st.caption(tr("已自动映射 BLAST 必需字段。"))
        else:
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
            hits = session_result("blast_mapping", (file_key, delimiter, header, mapping), normalize_hits, raw, mapping)
        except ValueError as exc:
            st.error(tr(str(exc)))
            return None

    return (name, origin, file_key, delimiter, header, mapping, hits)


def current_project_blast(project):
    result = st.session_state.get("local_blast_run")
    return result if project and result and result["key"][0] == project["key"] else None


def project_nucleotide_records(project):
    return session_result("local_blast_records", project["key"], valid_records, project) if project else {}


def blast_search():
    st.title(tr("BLAST 搜索"))
    project_status()
    project = st.session_state.get("project_sequences")
    available = project_nucleotide_records(project)
    if available:
        result = project_blast(project, available)
        if result:
            if st.button(tr("下一步：BLAST 候选筛选 →"), type="primary"):
                st.session_state["local_blast_source_mode"] = LOCAL_BLAST
                navigate("BLAST 候选筛选")
    else:
        st.info(tr("BLAST 搜索需要当前项目中的有效核酸序列。"))
        next_step("前往数据导入 →", "数据导入与管理")
    if st.button(tr("导入外部 BLAST 命中表")):
        st.session_state["local_blast_source_mode"] = EXTERNAL_BLAST
        navigate("BLAST 候选筛选")


def blast():
    st.title(tr("BLAST 候选筛选"))
    st.info(tr(NOTICE))
    project_status()
    project = st.session_state.get("project_sequences")
    stored_run = current_project_blast(project)
    previous = st.session_state.get("blast_result")
    figures = st.session_state.setdefault("report_figures", {})
    saved_figures = [key for key in figures if key.startswith("blast_")]
    sources = [LOCAL_BLAST, EXTERNAL_BLAST] if project and project["type"] == "nucleotide" else [EXTERNAL_BLAST]
    if st.session_state.get("local_blast_source_mode") not in sources:
        st.session_state["local_blast_source_mode"] = EXTERNAL_BLAST if st.session_state.get("blast_source") else sources[0]
    mode = st.radio(tr("BLAST 数据来源"), sources, horizontal=True, format_func=translator(), key="local_blast_source_mode")
    local = None
    exclude_identical = False
    if mode == LOCAL_BLAST:
        local = stored_run
        if local is None:
            st.info(tr("请先完成当前项目的 BLAST 搜索，或选择导入外部命中表。"))
            next_step("前往 BLAST 搜索 →", "BLAST 搜索")
            return
        if st.button(tr("← 返回 BLAST 搜索")):
            navigate("BLAST 搜索")
        st.caption(tr("当前运行的是项目内本地 BLAST，仅搜索用户上传的序列，不代表搜索整个 NCBI 数据库。"))
        name, origin = project["name"], LOCAL_BLAST
        file_key = sha256(repr(local["key"]).encode()).hexdigest()
        delimiter, header = "\t", "yes"
        mapping = {column: column for column in LOCAL_BLAST_FIELDS}
        hits = local["hits"]
        exclude_identical = st.checkbox(tr("隐藏自命中及完全相同的序列命中"), value=True, key="local_blast_exclude_identical")
        if hits.empty:
            st.info(tr("BLAST 已正常完成，所选查询和目标范围内没有命中。"))
    else:
        st.link_button(tr("前往 NCBI BLAST 官方页面 ↗"), "https://blast.ncbi.nlm.nih.gov/Blast.cgi")
        selected = source("blast", ["csv", "tsv", "txt", "tab", "out", "xlsx"])
        if selected is None:
            if previous and not previous.get("local_search"):
                st.dataframe(previous["filtered"], hide_index=True)
                next_step("下一步：可视化与报告 →", "结果可视化", result_view="blast")
            else:
                st.info(tr("可选：上传已生成的外部 BLAST 命中表。"))
                next_step("前往 BLAST 搜索 →", "BLAST 搜索")
            return
        imported = external_blast(selected)
        if imported is None:
            return
        name, origin, file_key, delimiter, header, mapping, hits = imported

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

    min_bitscore = st.number_input(tr("比特得分最低值（bitscore）"), min_value=0.0, value=0.0,
                                  key="blast_min_bitscore")
    thresholds = Thresholds(identity, evalue.strip(), length, coverage_field, coverage, min_bitscore)
    eligible = hits.loc[~local["identical"]["identical"]] if exclude_identical else hits
    if exclude_identical and not eligible.empty and len(eligible) < len(hits):
        st.caption(f'{tr("已隐藏的相同序列命中")} · {len(hits) - len(eligible)}')
    elif exclude_identical and eligible.empty and not hits.empty:
        st.info(tr("当前只有自命中或完全相同序列的命中，可开启显示。"))
    try:
        filtered = session_result("blast_filter", (file_key, delimiter, header, mapping, thresholds, exclude_identical), filter_hits, eligible, thresholds)
    except ValueError as exc:
        st.error(tr(str(exc)))
        return
    fingerprint = (name, origin, file_key, delimiter, header, mapping, thresholds, exclude_identical)
    queries = pd.Series(local["queries"]) if local else hits["qseqid"]
    best, counts = session_result("blast_count", fingerprint,
                                  lambda: (best_hits(filtered), candidate_counts(filtered, queries)))
    if local:
        counts = counts.assign(**{"Query Name": counts["qseqid"].map(local["query_names"])})
    timestamp = previous["timestamp"] if previous and previous["key"] == fingerprint else run_time()
    st.session_state["blast_result"] = {
        "key": fingerprint, "timestamp": timestamp, "name": name, "origin": origin,
        "thresholds": thresholds, "mapping": mapping, "before": len(hits), "filtered": filtered,
        "best": best, "counts": counts, "coverage_fields": fields, "delimiter": delimiter,
        "header": header,
    }
    if local:
        st.session_state["blast_result"]["local_search"] = {
            "version": local["version"], "timestamp": local["timestamp"], "query_count": local["query_count"],
            "target_count": local["target_count"], "exclude_identical": exclude_identical,
            "evalue": SEARCH_EVALUE,
        }

    if not previous or previous["key"] != fingerprint:
        for key in saved_figures:
            figures.pop(key, None)
    for column, label, value in zip(st.columns(5),
                                    ("原始命中数", "筛选后命中数", "有候选的 Query", "排除记录数", "保留比例"),
                                    (len(hits), len(filtered), len(best), len(hits)-len(filtered),
                                     f"{len(filtered)/len(hits):.1%}" if len(hits) else "0.0%")):
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
        st.dataframe(rejection_reasons(eligible, thresholds), width="stretch", hide_index=True)
    next_step("下一步：可视化与报告 →", "结果可视化", result_view="blast")


@st.fragment
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


RESULT_ORIGINS = {"local": "本地比对候选筛选", "blast": "BLAST 候选筛选"}


def result_path():
    default = st.session_state.get("workflow_path", "local")
    if not st.session_state.get("workflow_path") and st.session_state.get("blast_result") and not current_candidates():
        default = "blast"
    if "result_view" not in st.session_state:
        st.session_state["result_view"] = default
    return st.radio(tr("结果来源"), list(RESULT_ORIGINS), horizontal=True, key="result_view",
                    format_func=lambda path: tr(RESULT_ORIGINS[path]))


def show_results():
    st.title(tr("分析结果"))
    project_status()
    path = result_path()
    result = current_candidates() if path == "local" else st.session_state.get("blast_result")
    if result is None:
        st.info(tr("请先完成所选路径的候选筛选。"))
    else:
        frame = result["results" if path == "local" else "filtered"]
        st.dataframe(display_frame(frame), width="stretch", hide_index=True)
        filename = "local_candidates.csv" if path == "local" else "blast_filtered.csv"
        st.download_button(tr("下载当前结果 CSV"), csv_bytes(frame), filename, "text/csv", on_click="ignore")
        next_step("下一步：可视化与报告 →", "结果可视化")
    if st.button(tr("← 返回候选筛选")):
        navigate(RESULT_ORIGINS[path])


def visualization():
    st.title(tr("可视化与报告"))
    project_status()
    path = result_path()
    if st.button(tr("← 返回分析结果")):
        navigate("分析结果")
    section = st.radio(tr("查看内容"), ["结果可视化", "分析记录与导出"], horizontal=True,
                       key="result_section", format_func=translator())
    if section == "分析记录与导出":
        records(path)
        return
    if path == "local":
        local = current_candidates()
        if local:
            local_visualization(local)
        else:
            st.info(tr("请先完成所选路径的候选筛选。"))
        return
    result = st.session_state.get("blast_result")
    if result is None:
        st.info(tr("请先完成所选路径的候选筛选。"))
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
        return
    detail_plot(hits)


def local_visualization(local):
    hits = local["results"]
    st.caption(f'{tr("本地候选对数")} · {len(hits):,} / {local["before"]:,}')
    comparison = pd.DataFrame({"阶段": ["筛选前", "筛选后"], "命中数量": [local["before"], len(hits)]})
    chart_panel("local_candidate_comparison", lambda _: charts.hit_comparison(local["before"], len(hits)), comparison,
                ChartStyle("本地比对筛选前后对数", "阶段", "记录数", legend=False, legend_title="", category_colors=True))
    if hits.empty:
        st.info(tr("当前筛选没有保留本地候选对。"))
    else:
        plot_distribution(hits, "local_candidate_identity", "Identity (%)", "本地候选序列一致性", "Subject Name")



@st.fragment
def detail_plot(hits):
    selected = st.radio(tr("图表类型"), ("序列一致性", "比对长度", "覆盖度散点"),
                        horizontal=True, format_func=translator(), key="blast_detail_view")
    if selected == "序列一致性":
        plot_distribution(hits, "blast_identity", "pident", "序列一致性（%）", "sseqid")
    elif selected == "比对长度":
        plot_distribution(hits, "blast_length", "length", "比对长度", "sseqid")
    else:
        fields = coverage_options(hits)
        if fields:
            field = st.selectbox(tr("绘图覆盖度字段"), fields, key="chart_coverage")
            chart_panel(f"blast_scatter_{field}", lambda grouped: charts.coverage_scatter(hits, field, grouped),
                        hits.dropna(subset=[field]),
                        ChartStyle("一致性与覆盖度", "序列一致性（%）", f"查询覆盖度（{field}，%）", query_colors=True),
                        groupable=True)
        else:
            st.info(tr("当前命中没有可用于绘图的覆盖度。"))



def records(path):
    blast_result = st.session_state.get("blast_result") if path == "blast" else None
    local_search = blast_result.get("local_search") if blast_result else None
    metadata = {}
    for label in (*METADATA, "数据库登录号"):
        if label in ("BLAST 程序及版本", "参考数据库及版本"):
            if local_search:
                metadata[label] = local_search["version"] if label == "BLAST 程序及版本" else "当前项目序列（临时核酸库）"
                continue
            if not blast_result:
                continue
        widget = st.text_area if label == "分析备注" else st.text_input
        metadata[label] = widget(tr("研究说明与备注（可选）" if label == "分析备注" else label), key=f"research_{label}")
        if label in ("BLAST 程序及版本", "参考数据库及版本") and not metadata[label].strip():
            metadata[label] = "未提供"
    fasta_result = st.session_state.get("fasta_result")
    pairwise_record = st.session_state.get("pairwise_record") if path == "local" else None
    batch = st.session_state.get("batch_alignment") if path == "local" else None
    project = st.session_state.get("project_sequences")
    if batch and project and batch["key"][0] == project["key"]:
        pairwise_record = {**export_metadata(project, batch), "Algorithm": "Biopython PairwiseAligner"}
        candidates = current_candidates()
        if candidates:
            pairwise_record.update({
                "最低一致性 (%)": candidates["minimum_identity"], "最短比对长度": candidates["minimum_length"],
                "最低比对得分": candidates["minimum_score"], "本地候选对数": candidates["count"],
                "Reference Internal ID": candidates["reference"], "Exclude self": candidates["exclude_self"],
                "Sort": candidates["sort"], **{f"Filter {key}": val for key, val in candidates["thresholds"].items()},
            })
    record = build_record(metadata, fasta_result, blast_result, pairwise_record)
    save_button()
    st.subheader(tr("当前分析记录"))
    for module in ("FASTA", "BLAST", "成对序列比对"):
        if module in record:
            st.markdown(f"**{tr(module)}**")
            st.caption(" · ".join(f"{tr(key)}: {tr(value)}" for key, value in record[module].items()
                                  if key in ("上传文件名称", "序列数", "最短序列", "最长序列", "原始命中数",
                                             "筛选后命中数", "保留比例", "比对列数", "Comparisons", "本地候选对数")))
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
        report_section(record, blast_result, path)


def report_section(record, blast_result, path):
    st.subheader(tr("Word 分析报告"))
    with st.form("word_report_settings", enter_to_submit=False):
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
        prefixes = ("fasta_", "blast_") if path == "blast" else ("fasta_", "local_")
        figures = {key: value for key, value in st.session_state.get("report_figures", {}).items()
                   if key.startswith(prefixes)}
        if static_images_enabled():
            selected_figures = st.multiselect(tr("插入图表"), list(figures), format_func=lambda key: tr(figures[key][0]))
        else:
            selected_figures = []
            st.caption(tr("轻量预览支持 Word 文字与表格。带图报告请使用本地或 Docker 版本。"))
        if static_images_enabled() and not figures:
            st.caption(tr("访问 FASTA 或结果可视化页面后，可在此选择已生成的图表。"))
        metrics = {}
        tables = {}
        candidate_result = current_candidates() if path == "local" else None
        if candidate_result:
            hits = candidate_result["results"]
            columns = ("Query", "Subject")
            table = pd.DataFrame({
                side: hits[f"{side} Name"] + "\n" + hits[f"{side} Original Sequence ID"] + "\n" + hits[f"{side} Internal ID"]
                for side in columns
            }).assign(**{column: hits[column] for column in ("Identity (%)", "Alignment Length", "Alignment Score", "Gaps")})
            tables["本地比对候选筛选"] = table
            metrics["本地候选对数"] = candidate_result["count"]
        if blast_result:
            hits = blast_result["filtered"]
            tables.update({"候选基因列表": hits, "各 Query 候选数量": blast_result["counts"],
                           "最佳命中": blast_result["best"]})
            total = blast_result["before"]
            metrics.update({"原始命中数": total, "筛选后命中数": len(hits),
                            "保留比例": f"{len(hits)/total:.1%}" if total else "0.0%"})
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
        submitted = st.form_submit_button(tr("准备 Word 报告"), type="primary")
    signature = sha256(repr((record, title, background, notes, language, mode,
                             [(key, tables[key].to_json()) for key in chosen],
                             [(key, figures[key][1].to_json()) for key in selected_figures])).encode()).digest()
    prepared_key = f"_prepared_word_{path}"
    if submitted:
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
                with elapsed("word_images"):
                    images.append((chart_title, image_bytes(figure, "png")))
            report_title = tr(title.strip() or "PlantLab-GeneMiner 分析报告", language)
            with elapsed("word_docx"):
                output = word_report(report_title, background, notes,
                                     record, metrics, {key: tables[key] for key in chosen}, images, language, mode)
        except Exception:
            st.error(tr("Word 报告生成失败。若选了图表，请检查 Kaleido 与 Chromium，或取消插图后重试。"))
        else:
            st.session_state["last_report"] = output
            st.session_state[prepared_key] = (signature, report_title, output)
    prepared = st.session_state.get(prepared_key)
    if prepared and prepared[0] == signature:
        st.caption(f'{tr("当前报告已就绪")} · {prepared[1]}')
        st.download_button(tr("下载 Word 报告"), prepared[2], "plantlab_geneminer_report.docx",
                           "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                           on_click="ignore", key="current_word_report")


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
