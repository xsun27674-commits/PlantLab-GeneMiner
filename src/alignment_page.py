from dataclasses import asdict
from io import StringIO

import streamlit as st

from src.i18n import tr, translator
from Bio import SeqIO

from src.alignment import align_sequences
from src.account_page import navigate
from src.batch_alignment_page import batch_page
from src.project_data import project_status
from src.export_utils import json_bytes
from src.fasta_utils import analyze_fasta

MAX_FASTA_BYTES = 5 * 1024 * 1024


def alignment_page():
    st.title(tr("成对序列比对"))
    project_status()
    project = st.session_state.get("project_sequences")
    if project and project["type"] == "nucleotide":
        view = st.radio(tr("本地比对来源"), ["当前项目", "手动成对比对"], horizontal=True,
                        format_func=translator(), key="alignment_setting_view")
        if view == "当前项目":
            st.info(tr("本地 PairwiseAligner 得分不等于 BLAST bitscore，也不产生 E-value。"))
            batch_page(project)
            return
    if not project or project["type"] != "nucleotide":
        st.info(tr("项目批量比对需要核酸序列，可先导入项目数据。"))
        if st.button(tr("前往数据导入 →")):
            st.session_state["workflow_path"] = "local"
            navigate("数据导入与管理")
    st.session_state.pop("pairwise_record", None)
    st.info(tr("使用 Biopython 对两条序列进行全局或局部比对。数据库同源搜索需要独立的 BLAST 工作流。"))
    types = {"nucleotide": "DNA / 核酸", "protein": "蛋白质"}
    sequence_type = st.radio(tr("比对序列类型"), types, index=None, format_func=lambda key, translate=translator(): translate(types[key]), horizontal=True, key="alignment_setting_type")
    source = st.radio(tr("输入方式"), ["粘贴序列", "从 FASTA 选择"], horizontal=True, format_func=translator(), key="alignment_setting_source")
    if sequence_type is None:
        return
    if source == "从 FASTA 选择":
        def remember_alignment_file():
            upload = st.session_state.get("alignment_upload")
            st.session_state["alignment_fasta"] = (upload.name, upload.getvalue()) if upload else None

        file = st.file_uploader(tr("上传用于比对的 FASTA"), type=["fasta", "fa", "fna", "faa", "fas", "txt"],
                                help="FASTA ≤ 5 MB", key="alignment_upload", on_change=remember_alignment_file)
        cached = st.session_state.get("alignment_fasta")
        if cached is None:
            return
        if file is None:
            st.caption(cached[0])
        filename, data = cached
        if len(data) > MAX_FASTA_BYTES:
            st.error(tr("比对 FASTA 不能超过 5 MB。"))
            return
        try:
            analyze_fasta(data, sequence_type)
            records = list(SeqIO.parse(StringIO(data.decode("utf-8-sig").lstrip()), "fasta"))
        except ValueError as exc:
            st.error(tr(str(exc)))
            return
        if len(records) < 2:
            st.info(tr("请上传至少包含两条序列的 FASTA。"))
            return
        options = range(len(records))
        first, second = (column.selectbox(f"序列 {index + 1}", options, index=index,
                         format_func=lambda item: f"{item + 1} · {records[item].id}")
                         for index, column in enumerate(st.columns(2)))
        if first == second:
            st.warning(tr("请选择两条不同的 FASTA 记录。"))
            return
        sequences = [str(records[item].seq) for item in (first, second)]
    else:
        sequences = [column.text_area(f"{tr('序列')} {index + 1}", max_chars=20000, key=f"alignment_setting_sequence_{index}")
                     for index, column in enumerate(st.columns(2))]
    modes = {"global": "全局比对", "local": "局部比对"}
    mode = st.radio(tr("比对模式"), modes, format_func=lambda key, translate=translator(): translate(modes[key]), horizontal=True, key="alignment_setting_mode")
    scores = [column.number_input(tr(label), -100.0, 100.0, default, step=0.5, key=f"alignment_setting_score_{index}")
              for index, (column, label, default) in enumerate(zip(st.columns(4),
                  ("匹配评分", "错配评分", "Gap 开启", "Gap 延伸"), (2.0, -1.0, -3.0, -1.0)))]
    key = (tuple(sequences), sequence_type, mode, tuple(scores))
    if st.button(tr("执行成对比对"), type="primary"):
        try:
            result = align_sequences(*sequences, sequence_type, mode, *scores)
        except ValueError as exc:
            st.error(tr(str(exc)))
            return
        st.session_state["pairwise_result"] = (key, result)
    stored = st.session_state.get("pairwise_result")
    if stored is None or stored[0] != key:
        return
    result = stored[1]
    if result is None:
        st.info(tr("没有找到正分的局部比对。"))
        return
    for column, label, value in zip(st.columns(5), ("一致性", "比对列数", "匹配", "错配", "Gap"),
        (f"{result.identity:.2f}%", result.length, result.matches, result.mismatches, result.gaps)):
        column.metric(tr(label), value)
    st.caption(tr("一致性 = 匹配列数 / 全部比对列数，含 gap。| 表示匹配，. 表示错配，- 表示 gap。同分时展示 Biopython 返回的首个比对。"))
    st.write(f"比对得分：{result.score:g}")
    st.code(result.text, language=None)
    payload = {**asdict(result), "mode": mode, "sequence_type": sequence_type,
               "scoring": dict(zip(("match", "mismatch", "gap_open", "gap_extend"), scores))}
    st.session_state["pairwise_record"] = {
        "输入来源": source, "序列类型": types[sequence_type], "比对模式": modes[mode],
        "得分": result.score, "比对列数": result.length, "一致性（%）": result.identity,
        "匹配列": result.matches, "错配列": result.mismatches, "gap 列": result.gaps,
        **payload["scoring"],
        **({"上传文件名称": filename} if source == "从 FASTA 选择" else {}),
    }
    st.download_button(tr("下载成对比对 JSON"), json_bytes(payload), "pairwise_alignment.json", "application/json")
    st.download_button(tr("下载比对文本"), result.text, "pairwise_alignment.txt", "text/plain")
