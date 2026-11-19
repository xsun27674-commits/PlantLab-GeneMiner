"""Shared, serializable project data and conservative table classification."""

import re
from io import StringIO

import streamlit as st
from Bio import SeqIO

from src.blast_utils import ALIASES, REQUIRED
from src.i18n import tr
from src.timing import session_result


def column_key(value):
    return re.sub(r"[\W_]", "", str(value).casefold())


def sequence_columns(columns):
    ids = [name for name in columns if column_key(name) in {"sequenceid", "seqid", "recordid", "序列编号", "序列id"}]
    sequences = [name for name in columns if column_key(name) in {
        "sequence", "seq", "cds", "cdssequence", "nucleotidesequence", "dnasequence", "序列内容",
    }]
    return ids or [name for name in columns if column_key(name) in {"id", "accession"}], sequences


def classify_table(columns):
    keys = {column_key(name) for name in columns}
    ids, sequences = sequence_columns(columns)
    if sequences:
        return "sequence" if ids else "incomplete_sequence", []
    missing = [field for field in REQUIRED if not keys.intersection(ALIASES[field])]
    if not missing:
        return "blast", []
    if "alignmentscore" in keys or ("algorithm" in keys and "alignmentlength" in keys):
        return "pairwise", missing
    if len(missing) < len(REQUIRED):
        return "incomplete_blast", missing
    return "unknown", missing


def register_sequences(fingerprint, name, origin, sequence_type, data):
    current = st.session_state.get("project_sequences")
    if current and current["key"] == fingerprint:
        return
    records = session_result("project_sequences", fingerprint,
        lambda: [(record.id, str(record.seq))
                 for record in SeqIO.parse(StringIO(data.decode("utf-8-sig").lstrip()), "fasta")])
    st.session_state["project_sequences"] = {
        "key": fingerprint, "name": name, "origin": origin, "type": sequence_type, "records": records,
    }
    for key in ("batch_alignment", "pairwise_record", "alignment_setting_batch_indices",
                "alignment_setting_batch_query"):
        st.session_state.pop(key, None)


def project_status():
    project = st.session_state.get("project_sequences")
    blast = st.session_state.get("blast_result")
    batch = st.session_state.get("batch_alignment")
    if not any((project, blast, batch)):
        return
    with st.expander(tr("当前项目数据"), expanded=True):
        if project:
            label = "核酸" if project["type"] == "nucleotide" else "蛋白质"
            st.write(f'{project["name"]} · {tr(project["origin"])} · {tr(label)} · '
                     f'{len(project["records"])} {tr("条序列")} · {tr("序列统计已完成")}')
        if batch:
            st.write(f'{tr("本地比对已完成")} · {len(batch["results"])} {tr("对")}')
        if blast:
            st.write(f'BLAST · {blast["name"]} · {tr(blast["origin"])} · '
                     f'{len(blast["filtered"])}/{blast["before"]} {tr("条命中")}')


def clear_sequence_project():
    for key in ("project_sequences", "fasta_result", "fasta_source", "sequence_grid_source",
                "sequence_grid_base", "sequence_ncbi_applied", "sequence_ncbi_table",
                "sequence_ncbi_selection", "batch_alignment", "pairwise_record"):
        st.session_state.pop(key, None)
    for key in list(st.session_state):
        if key.startswith(("_timed_fasta_", "_timed_ncbi_", "_timed_sequence_",
                           "_timed_project_sequences", "_timed_batch_detail")):
            st.session_state.pop(key, None)
    st.session_state.pop("last_report", None)
    st.session_state.pop("_prepared_word", None)
    st.session_state["fasta_example"] = False
    st.session_state["fasta_upload_revision"] = st.session_state.get("fasta_upload_revision", 0) + 1
    st.session_state["sequence_grid_revision"] = st.session_state.get("sequence_grid_revision", 0) + 1
    figures = st.session_state.get("report_figures", {})
    for key in ("fasta_length", "fasta_gc"):
        figures.pop(key, None)
