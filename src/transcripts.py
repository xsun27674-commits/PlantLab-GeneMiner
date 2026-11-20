"""Conservative gene identity and opt-in transcript selection."""

from collections import defaultdict
import re
import unicodedata

import pandas as pd
import streamlit as st

from src.fasta_utils import ALPHABETS
from src.i18n import tr
from src.ncbi_dataset import SELECT_PRIORITY
from src.project_data import record_info, record_labels

EXCLUDE_ISOFORMS = "排除同一基因的不同转录本命中"
REPRESENTATIVES = "每个基因保留一条代表性转录本"
EVIDENCE_FIELDS = {
    "gene": "Gene", "gene_id": "Gene ID", "species": "Species",
    "accession": "Accession", "transcript": "Transcript",
}


def normalized(value):
    if not isinstance(value, str):
        return ""
    text = " ".join(unicodedata.normalize("NFKC", value).casefold().split())
    return "" if text in {"待核实", "unknown", "na", "n/a", "-", ".", "none", "null", "unverified"} else text


def gene_keys(records):
    """Use species and stable ID first; only bridge symbols with unambiguous evidence."""
    entries = [(normalized(item.get("species")), normalized(item.get("gene_id")),
                normalized(item.get("gene"))) for item in records]
    known = defaultdict(set)
    for species, gene_id, symbol in entries:
        if species and gene_id and symbol:
            known[species, symbol].add(gene_id)
    keys = []
    for species, gene_id, symbol in entries:
        ids = known[species, symbol]
        if not species or (not gene_id and (not symbol or len(ids) > 1)):
            keys.append(None)
        elif gene_id or ids:
            keys.append((species, "id", gene_id or next(iter(ids))))
        else:
            keys.append((species, "symbol", symbol))
    return keys


def isoform_hit_mask(hits, project=None):
    """Flag HSP rows only when both gene and distinct transcript are supported."""
    sides = []
    project_records = []
    by_internal = {}
    if project:
        project_records = [record_info(project, index) for index in range(len(project["records"]))]
        by_internal = {item["id"]: item for item in project_records}
    for side in ("Query", "Subject"):
        columns = {f"{side} {label}": key for key, label in {**EVIDENCE_FIELDS, "id": "Internal ID"}.items()}
        records = hits.reindex(columns=columns).rename(columns=columns).to_dict("records")
        sides.append([by_internal.get(item["id"], item) for item in records])
    n = len(hits)
    keys = gene_keys([*sides[0], *sides[1], *project_records])

    def different_transcript(left, right):
        for field in ("accession", "transcript"):
            a, b = normalized(left.get(field)), normalized(right.get(field))
            if a and b:
                return re.sub(r"\.\d+$", "", a) != re.sub(r"\.\d+$", "", b)
        return False

    return pd.Series([a is not None and a == b and different_transcript(left, right)
                      for a, b, left, right in zip(keys[:n], keys[n:2 * n], *sides)],
                     index=hits.index, dtype=bool)


def representative_selection(project, indices):
    info = [record_info(project, index) for index in indices]
    groups = defaultdict(list)
    decisions = {}
    for index, key, item in zip(indices, gene_keys(info), info):
        dna = "".join(project["records"][index][1].split()).upper()
        if key is None:
            decisions[index] = (True, "基因身份未核实，保留")
        elif not dna or set(dna) - ALPHABETS["nucleotide"]:
            decisions[index] = (False, "无有效核酸序列")
        else:
            category = item["select_category"]
            groups[key].append((index, len(dna), category))
    for options in groups.values():
        selected, _, category = max(
            options, key=lambda entry: (SELECT_PRIORITY.get(entry[2], 0), entry[1], -entry[0]))
        annotated = category in SELECT_PRIORITY
        reason = category if annotated else "最长有效 CDS（后备规则）"
        excluded = "同基因已保留 NCBI Select 标注序列" if annotated else "同基因已保留最长有效 CDS"
        for index, _, _ in options:
            decisions[index] = (index == selected, reason if index == selected else excluded)
    return decisions


def analysis_transcripts(project, indices, key):
    """Select an analysis view without modifying the imported records."""
    mode = st.radio(tr("分析转录本范围"), ("保留全部转录本", REPRESENTATIVES),
                    format_func=tr, horizontal=True, key=key)
    if mode != REPRESENTATIVES:
        return indices
    decisions = representative_selection(project, indices)
    labels = record_labels(project)
    st.caption(tr("优先采用 NCBI Select 标注。缺少标注时取最长有效 CDS，等长时按原始顺序。"))
    if any(reason == "基因身份未核实，保留" for _, reason in decisions.values()):
        st.info(tr("基因身份未核实的序列保持独立并保留。"))
    with st.expander(tr("查看转录本选择结果")):
        st.dataframe(pd.DataFrame({
            tr("显示名称"): [labels[index] for index in decisions],
            "Sequence ID": [record_info(project, index)["original"] for index in decisions],
            tr("保留"): [kept for kept, _ in decisions.values()],
            tr("原因"): [tr(reason) for _, reason in decisions.values()],
        }), hide_index=True)
    return [index for index in indices if decisions[index][0]]
