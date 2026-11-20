"""Shared, serializable project data and conservative table classification."""

import re
from collections import Counter
from io import StringIO

import streamlit as st
from Bio import SeqIO

from src.blast_utils import ALIASES, REQUIRED
from src.i18n import tr
from src.ncbi_dataset import match_record, UNKNOWN
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


def table_metadata(frame, *, include_source=False):
    names = {column_key(name): name for name in frame.columns}
    columns = [next((names[key] for key in choices if key in names), None) for choices in
               (("gene", "genesymbol", "基因"), ("accession", "accessionversion", "登录号"),
                ("transcript", "transcriptid", "transcriptaccession", "转录本"),
                ("originalsequenceid",))]
    if include_source:
        columns += [names.get("geneid"), names.get("species")]
    return [tuple(str(row[column]).strip() if column is not None else "" for column in columns)
            for _, row in frame.fillna("").iterrows()]


def clean_metadata(value):
    return "" if value in ("", UNKNOWN, "NA", "N/A", "-") else value


def register_sequences(fingerprint, name, origin, sequence_type, data, metadata=()):
    current = st.session_state.get("project_sequences")
    if current and current["key"] == fingerprint and "metadata" in current:
        return

    def parse():
        records, identities = [], []
        for index, record in enumerate(SeqIO.parse(StringIO(data.decode("utf-8-sig").lstrip()), "fasta")):
            records.append((record.id, str(record.seq)))
            gene_id, symbol, species, accession = match_record(record, ({}, {}, {}))
            if index < len(metadata):
                supplied_symbol, supplied_accession, transcript, original, *source = map(clean_metadata, metadata[index])
                if source:
                    gene_id, species = source[0] or gene_id, source[1] or species
            else:
                supplied_symbol = supplied_accession = transcript = original = ""
            identities.append({"gene": supplied_symbol or clean_metadata(symbol),
                               "accession": supplied_accession or accession, "transcript": transcript,
                               "original": original or record.id, "gene_id": gene_id, "species": species,
                               "id": f"seq-{fingerprint[1][:12]}-{index + 1}"})
        return records, identities

    records, identities = session_result("project_sequences", fingerprint, parse)
    invalidate_sequence_results()
    st.session_state["project_sequences"] = {
        "key": fingerprint, "name": name, "origin": origin, "type": sequence_type,
        "records": records, "metadata": identities,
    }


def invalidate_sequence_results():
    stop_batch()
    if (st.session_state.get("blast_result") or {}).get("local_search"):
        st.session_state.pop("blast_result", None)
        figures = st.session_state.get("report_figures", {})
        for chart in list(figures):
            if chart.startswith("blast_"):
                figures.pop(chart)
    for key in ("local_blast_run", "local_blast_queries", "local_blast_targets", "local_blast_source_mode"):
        st.session_state.pop(key, None)
    for key in ("fasta_length", "fasta_gc", "local_alignment_matrix", "local_candidate_comparison", "local_candidate_identity"):
        st.session_state.get("report_figures", {}).pop(key, None)
    for key in ("project_sequences", "fasta_result", "batch_alignment", "_batch_history", "_batch_outcome",
                "_batch_checkpoint", "local_candidates_record", "last_report", "_prepared_word", "_prepared_word_local", "_prepared_word_blast",
                "pairwise_record", "alignment_setting_candidates_reference", "alignment_setting_batch_indices",
                "alignment_setting_batch_query", "alignment_setting_batch_pair", "alignment_setting_candidate_pair"):
        st.session_state.pop(key, None)


def stop_batch():
    job = st.session_state.pop("_batch_job", None)
    if job:
        job.cancel.set()


def record_info(project, index):
    record = project["records"][index][0]
    metadata = project.get("metadata", [])
    info = metadata[index] if index < len(metadata) else {}
    return {"original": info.get("original", record), "gene": info.get("gene", ""), "accession": info.get("accession", ""),
            "transcript": info.get("transcript", ""), "gene_id": info.get("gene_id", ""),
            "species": info.get("species", ""),
            "id": info.get("id", f"seq-{project['key'][1][:12]}-{index + 1}")}


def record_labels(project):
    return display_labels([record_info(project, i) for i in range(len(project["records"]))])


def display_labels(info):
    labels = [" · ".join(filter(None, (item["gene"], item["accession"] or item["original"])))
              for item in info]
    counts = Counter(labels)
    return [f"{label} · [{index + 1}]" if counts[label] > 1 else label
            for index, label in enumerate(labels)]

def project_gene_count(project):
    groups = set()
    known = {}
    for item in project.get("metadata", ()):
        symbol = (item.get("species", ""), item.get("gene", ""))
        if item.get("gene_id") and symbol[1]:
            known.setdefault(symbol, set()).add(item["gene_id"])
    for item in project.get("metadata", ()):
        symbol = (item.get("species", ""), item.get("gene", ""))
        identifiers = known.get(symbol, set())
        if item.get("gene_id"):
            groups.add(item["gene_id"])
        elif symbol[1] and not identifiers:
            groups.add(symbol)
    return len(groups)


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
        local = current_candidates()
        if local:
            st.write(f'{tr("本地候选对数")} · {local["count"]}')
        if blast:
            st.write(f'BLAST · {blast["name"]} · {tr(blast["origin"])} · '
                     f'{len(blast["filtered"])}/{blast["before"]} {tr("条命中")}')


def current_candidates():
    project = st.session_state.get("project_sequences")
    batch = st.session_state.get("batch_alignment")
    selected = st.session_state.get("local_candidates_record")
    if (project and batch and selected and batch["key"][0] == project["key"]
            and selected["key"] == batch["key"] and "results" in selected):
        return selected
    return None


def clear_sequence_project():
    invalidate_sequence_results()
    for key in ("fasta_source", "blast_source", "blast_result", "blast_upload", "blast_example",
                "pairwise_result", "alignment_fasta", "alignment_upload", "sequence_input_paste",
                "sequence_grid_source", "sequence_grid_base", "sequence_ncbi_applied",
                "sequence_ncbi_table", "sequence_ncbi_selection", "report_figures"):
        st.session_state.pop(key, None)
    for key in list(st.session_state):
        if key.startswith(("_timed_", "_prepared_", "_matrix_click_", "matrix_", "ncbi_",
                           "alignment_setting_sequence_", "chart_genes_")):
            st.session_state.pop(key, None)
    st.session_state["fasta_example"] = False
    st.session_state["fasta_upload_revision"] = st.session_state.get("fasta_upload_revision", 0) + 1
    st.session_state["sequence_grid_revision"] = st.session_state.get("sequence_grid_revision", 0) + 1
