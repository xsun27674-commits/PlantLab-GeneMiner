"""Streamlit entry point."""

import streamlit as st

from src import pages

st.set_page_config(page_title="PlantLab-GeneMiner", page_icon="🌱", layout="wide")

st.sidebar.title("PlantLab-GeneMiner")
st.sidebar.caption("植物候选基因筛选平台 · V1.0")

navigation = {
    "首页": pages.home,
    "FASTA 序列分析": pages.fasta,
    "BLAST 候选筛选": pages.blast,
    "结果可视化": pages.visualization,
    "分析记录与导出": pages.records,
    "关于平台": pages.about,
}
page = st.sidebar.radio("页面导航", navigation, key="page")

# Keep scalar analysis controls across views. Upload bytes are retained by the uploader callback.
prefixes = ("delimiter_", "header_", "mapping_", "coverage_", "research_")
controls = {"fasta_example", "blast_example", "sequence_type", "identity", "evalue",
            "alignment_length", "coverage_cutoff"}
for key in list(st.session_state):
    if key in controls or key.startswith(prefixes):
        st.session_state[key] = st.session_state[key]

navigation[page]()
