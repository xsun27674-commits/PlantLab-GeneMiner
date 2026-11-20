"""NCBI package controls for the existing sequence input workflow."""

from hashlib import sha256

import streamlit as st
from openpyxl.utils.exceptions import IllegalCharacterError

from src.export_utils import csv_bytes
from src.i18n import tr
from src.ncbi_dataset import COLUMNS, INTERNAL, UNKNOWN, parse_ncbi_zip, sequence_quality
from src.sequence_input import MAX_BYTES, MAX_ROWS, table_to_fasta, write_sequence_xlsx
from src.timing import session_result
from src.project_data import clean_metadata, display_labels, invalidate_sequence_results, table_metadata

NCBI_DATASETS_URL = "https://www.ncbi.nlm.nih.gov/datasets/gene/"


def ncbi_link():
    st.link_button(tr("从 NCBI 获取序列 ↗"), NCBI_DATASETS_URL)
    st.caption(tr("搜索多个基因 → 选择物种 → Download Package → 勾选 CDS (FASTA) → 下载 ZIP → 上传 PlantLab。"))


def ncbi_source(name, data):
    digest = sha256(data).hexdigest()
    original = session_result("ncbi_zip", digest, parse_ncbi_zip, data)
    saved = st.session_state.get("sequence_ncbi_table")
    if saved and saved[0] == digest:
        original = saved[1].copy()
        if "_original_sequence_id" not in original:
            original["_original_sequence_id"] = original["Sequence ID"]
    def invalidate_applied():
        if st.session_state.pop("sequence_ncbi_applied", None):
            invalidate_sequence_results()

    mode = st.radio(tr("转录本范围"), ("all", "selected"), horizontal=True, key=f"ncbi_transcripts_{digest}",
                    format_func={"all": tr("保留全部转录本"), "selected": tr("选择转录本")}.get, on_change=invalidate_applied)
    selection = []
    if mode == "selected":
        options = sorted(set(original["_transcript"]) - {""})
        selection = st.multiselect(tr("选择已核实的转录本编号"), options, key=f"ncbi_accessions_{digest}", on_change=invalidate_applied)
        if not selection:
            st.info(tr("请选择转录本，或切换为保留全部。"))
            return None
        originals = original.loc[original["_transcript"].isin(selection)]
    else:
        originals = original

    draft = st.session_state.get("sequence_ncbi_selection")
    if mode == "selected" and draft and draft[:2] == (digest, tuple(selection)):
        originals = draft[2].copy()
        if "_original_sequence_id" not in originals:
            originals["_original_sequence_id"] = originals["Sequence ID"]
    revision = st.session_state.get("sequence_ncbi_revision", 0)
    editor_id = sha256(repr((digest, mode, selection, revision)).encode()).hexdigest()
    st.caption(tr("可批量编辑序列编号和序列，或删除行。基因、物种与转录本编号取自原始记录。"))
    preview = originals.copy()
    label = "Display Name"
    preview.insert(0, label, display_labels([
        {"gene": clean_metadata(str(gene)), "accession": clean_metadata(str(accession)),
         "original": original or identifier}
        for gene, accession, original, identifier in originals[
            ["Gene", "Accession", "_original_sequence_id", "Sequence ID"]
        ].itertuples(index=False, name=None)
    ]))
    edited = st.data_editor(
        preview, key=f"ncbi_grid_{editor_id}", hide_index=True, num_rows="dynamic",
        disabled=[label, "Gene", "Species", "Accession", "Length (bp)", *INTERNAL],
        column_config={**{key: None for key in INTERNAL}, label: tr("显示名称")}, width="stretch",
    ).drop(columns=label)
    edited[INTERNAL] = edited[INTERNAL].fillna("")
    for field in ("Gene", "Species", "Accession"):
        edited[field] = edited[field].fillna(UNKNOWN)
    edited["Sequence"] = edited["Sequence"].fillna("").astype(str).map(lambda cell: "".join(cell.split()))
    edited["Length (bp)"] = edited["Sequence"].str.len()
    if len(edited) > MAX_ROWS or sum(len(sequence.encode()) for sequence in edited["Sequence"]) > MAX_BYTES:
        raise ValueError("序列表超出 5,000 行或 10 MB。")
    # The editor retains deltas against its base. Commit edits into a new
    # widget revision so calculated lengths and deleted rows remain current.
    if list(edited.fillna("").itertuples(index=False, name=None)) != list(
        originals.fillna("").itertuples(index=False, name=None)
    ):
        invalidate_applied()
        if mode == "all":
            st.session_state["sequence_ncbi_table"] = (digest, edited)
        else:
            st.session_state["sequence_ncbi_selection"] = (digest, tuple(selection), edited)
        st.session_state["sequence_ncbi_revision"] = revision + 1
        st.rerun()
    quality = sequence_quality(edited)
    for column, label, count in zip(st.columns(3),
        ("导入序列数", "已核实基因数", "已核实转录本数"),
        (len(edited), edited.loc[edited["_gene_id"].ne(""), "_gene_id"].nunique(),
         edited.loc[edited["_transcript"].ne(""), "_transcript"].nunique())):
        column.metric(tr(label), count)
    st.caption(f'{tr("基因待核实行数")} {int(edited["_gene_id"].eq("").sum())} · '
               f'{tr("转录本待核实行数")} {int(edited["_transcript"].eq("").sum())}')
    flagged = quality["Empty"] | quality["Duplicate ID"] | quality["Invalid characters"].ne("") | quality["Sequence ID"].eq("")
    if flagged.any():
        st.warning(tr("请检查下列空值、重复编号或非法字符。"))
        st.dataframe(quality.loc[flagged], hide_index=True)

    public = edited[COLUMNS].copy()
    public["Original Sequence ID"] = edited["_original_sequence_id"]
    export_signature = sha256(repr(tuple(public.itertuples(index=False, name=None))).encode()).digest()
    excel, csv, analyze = st.columns(3)
    if not public.empty:
        with excel:
            if public["Length (bp)"].gt(32767).any():
                st.caption(tr("超过 Excel 单元格上限的序列会完整保存到分片工作表。CSV 仍为单格完整序列。"))
            try:
                workbook = session_result("ncbi_excel", export_signature, write_sequence_xlsx, public)
            except IllegalCharacterError:
                st.warning(tr("表格含 Excel 不支持的控制字符，修正后可下载 Excel。"))
            else:
                excel.download_button(tr("下载 Excel"), workbook, "ncbi_sequences.xlsx",
                                      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                      on_click="ignore")
        csv.download_button(tr("下载 CSV"), csv_bytes(public), "ncbi_sequences.csv", "text/csv", on_click="ignore")
    clicked = analyze.button(tr("应用序列到项目"), type="primary", disabled=public.empty)
    applied = st.session_state.get("sequence_ncbi_applied")
    if clicked:
        st.session_state["_sequence_input_metadata"] = table_metadata(public.assign(GeneID=edited["_gene_id"]), include_source=True)
        canonical = table_to_fasta(public, "Sequence ID", "Sequence")
        st.session_state["sequence_ncbi_applied"] = (digest, export_signature, canonical)
        return name, canonical, "NCBI Datasets"
    if applied and applied[:2] == (digest, export_signature):
        st.session_state["_sequence_input_metadata"] = table_metadata(public.assign(GeneID=edited["_gene_id"]), include_source=True)
        return name, applied[2], "NCBI Datasets"
    return None
