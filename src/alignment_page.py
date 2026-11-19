from dataclasses import asdict
from io import StringIO

import streamlit as st
from Bio import SeqIO

from src.alignment import align_sequences
from src.export_utils import json_bytes
from src.fasta_utils import analyze_fasta

MAX_FASTA_BYTES = 5 * 1024 * 1024


def alignment_page():
    st.title("成对序列比对")
    st.session_state.pop("pairwise_record", None)
    st.info("使用 Biopython 对两条序列进行全局或局部比对。数据库同源搜索需要独立的 BLAST 工作流。")
    types = {"nucleotide": "DNA / 核酸", "protein": "蛋白质"}
    sequence_type = st.radio("比对序列类型", types, index=None, format_func=types.get, horizontal=True)
    source = st.radio("输入方式", ["粘贴序列", "从 FASTA 选择"], horizontal=True)
    if sequence_type is None:
        return
    if source == "从 FASTA 选择":
        file = st.file_uploader("上传用于比对的 FASTA", type=["fasta", "fa", "fna", "faa", "fas", "txt"],
                                help="成对比对使用的 FASTA 上限为 5 MB。")
        if file is None:
            return
        if file.size > MAX_FASTA_BYTES:
            st.error("比对 FASTA 不能超过 5 MB。")
            return
        try:
            data = file.getvalue()
            analyze_fasta(data, sequence_type)
            records = list(SeqIO.parse(StringIO(data.decode("utf-8-sig").lstrip()), "fasta"))
        except ValueError as exc:
            st.error(str(exc))
            return
        if len(records) < 2:
            st.info("请上传至少包含两条序列的 FASTA。")
            return
        options = range(len(records))
        first, second = (column.selectbox(f"序列 {index + 1}", options, index=index,
                         format_func=lambda item: f"{item + 1} · {records[item].id}")
                         for index, column in enumerate(st.columns(2)))
        if first == second:
            st.warning("请选择两条不同的 FASTA 记录。")
            return
        sequences = [str(records[item].seq) for item in (first, second)]
    else:
        sequences = [column.text_area(f"序列 {index + 1}", max_chars=20000)
                     for index, column in enumerate(st.columns(2))]
    modes = {"global": "全局比对", "local": "局部比对"}
    mode = st.radio("比对模式", modes, format_func=modes.get, horizontal=True)
    scores = [column.number_input(label, -100.0, 100.0, default, step=0.5)
              for column, label, default in zip(st.columns(4),
                  ("匹配评分", "错配评分", "Gap 开启", "Gap 延伸"), (2.0, -1.0, -3.0, -1.0))]
    key = (tuple(sequences), sequence_type, mode, tuple(scores))
    if st.button("执行成对比对", type="primary"):
        try:
            result = align_sequences(*sequences, sequence_type, mode, *scores)
        except ValueError as exc:
            st.error(str(exc))
            return
        st.session_state["pairwise_result"] = (key, result)
    stored = st.session_state.get("pairwise_result")
    if stored is None or stored[0] != key:
        return
    result = stored[1]
    if result is None:
        st.info("没有找到正分的局部比对。")
        return
    for column, label, value in zip(st.columns(5), ("一致性", "比对列数", "匹配", "错配", "Gap"),
        (f"{result.identity:.2f}%", result.length, result.matches, result.mismatches, result.gaps)):
        column.metric(label, value)
    st.caption("一致性 = 匹配列数 / 全部比对列数，含 gap。| 表示匹配，. 表示错配，- 表示 gap。同分时展示 Biopython 返回的首个比对。")
    st.write(f"比对得分：{result.score:g}")
    st.code(result.text, language=None)
    payload = {**asdict(result), "mode": mode, "sequence_type": sequence_type,
               "scoring": dict(zip(("match", "mismatch", "gap_open", "gap_extend"), scores))}
    st.session_state["pairwise_record"] = {
        "输入来源": source, "序列类型": types[sequence_type], "比对模式": modes[mode],
        "得分": result.score, "比对列数": result.length, "一致性（%）": result.identity,
        "匹配列": result.matches, "错配列": result.mismatches, "gap 列": result.gaps,
        **payload["scoring"],
    }
    st.download_button("下载成对比对 JSON", json_bytes(payload), "pairwise_alignment.json", "application/json")
    st.download_button("下载比对文本", result.text, "pairwise_alignment.txt", "text/plain")
