"""Streamlit entry point."""

import streamlit as st

from src import pages
from src.brand import help_center, logo
from src.i18n import tr
from src.alignment_page import alignment_page

st.set_page_config(page_title="PlantLab-GeneMiner", page_icon=str(logo()), layout="wide")

_, language_ui = st.columns([5, 1])
language_ui.selectbox("中文 / English", ("zh", "en"), format_func={"zh": "中文", "en": "English"}.get,
                      key="language")
st.sidebar.image(str(logo()), width=66)
st.sidebar.title("PlantLab-GeneMiner")
st.sidebar.caption("V3.0")
st.sidebar.caption(tr("游客分析不会自动长期保存，请及时下载结果。"))

navigation = {
    "首页": pages.home,
    "FASTA 序列分析": pages.fasta,
    "成对序列比对": alignment_page,
    "BLAST 候选筛选": pages.blast,
    "结果可视化": pages.visualization,
    "分析记录与导出": pages.records,
    "关于平台": pages.about,
    "帮助中心": help_center,
}
page = st.sidebar.radio(tr("页面导航"), navigation, key="page", format_func=tr)

# Keep scalar analysis controls across views. Upload bytes are retained by the uploader callback.
prefixes = ("delimiter_", "header_", "mapping_", "coverage_", "research_", "chart_mode_")
controls = {"fasta_example", "blast_example", "sequence_type", "identity", "evalue",
            "alignment_length", "coverage_cutoff"}
for key in list(st.session_state):
    if key in controls or key.startswith(prefixes):
        st.session_state[key] = st.session_state[key]

navigation[page]()
