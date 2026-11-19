"""Streamlit entry point."""

import streamlit as st

from src import pages
from src.account_page import account_page, autosave, get_store, workspace_page
from src.workspace_state import clear
from src.brand import help_center, is_wide_logo, logo, logo_icon
from src.i18n import tr
from src.alignment_page import alignment_page

st.set_page_config(page_title="PlantLab-GeneMiner", page_icon=str(icon) if (icon := logo_icon() or logo()) else None, layout="wide")

_, language_ui, account_ui = st.columns([5, 1.4, 1])
language_ui.selectbox("中文 / English", ("zh", "en"), format_func={"zh": "中文", "en": "English"}.get,
                      key="language")
sidebar_logo = logo()
if sidebar_logo:
    st.sidebar.image(str(sidebar_logo), width="stretch" if is_wide_logo(sidebar_logo) else 66)
st.sidebar.title("PlantLab-GeneMiner")
st.sidebar.caption("V3.0")
st.sidebar.caption("Beta")

navigation = {
    "首页": pages.home,
    "FASTA 序列分析": pages.fasta,
    "成对序列比对": alignment_page,
    "BLAST 候选筛选": pages.blast,
    "结果可视化": pages.visualization,
    "分析记录与导出": pages.records,
    "关于平台": pages.about,
    "帮助中心": help_center,
    "账户": account_page,
    "我的项目": workspace_page,
}
pending = st.session_state.pop("workspace_pending", None)
if pending:
    row, state = pending
    clear(st.session_state)
    st.session_state.update(state)
    st.session_state.update(workspace_id=row["id"], project_name=row["name"],
                            project_species=row["species"], project_target=row["target"])
destination = st.session_state.pop("next_page", None)
if destination:
    st.session_state["page"] = destination
page = st.session_state.get("page", "首页")


st.html("""
<style>
.st-key-active_nav button {
    background:#edf7f1; color:#176b4d; border:0; border-left:3px solid #176b4d;
}
.st-key-home_intro { max-width: 960px; }
</style>
""")


def show_nav(container, key):
    slot = container.container(key="active_nav") if key == page else container
    slot.button(tr(key), key=f"nav_{key}", width="stretch",
                     type="secondary" if key == page else "tertiary",
                     on_click=st.session_state.__setitem__, args=("page", key))


show_nav(st.sidebar, "首页")
for group, keys in (
    ("序列分析", ("FASTA 序列分析", "成对序列比对")),
    ("候选基因分析", ("BLAST 候选筛选",)),
    ("结果管理", ("结果可视化", "分析记录与导出", "我的项目")),
):
    st.sidebar.caption(tr(group))
    for entry in keys:
        show_nav(st.sidebar, entry)
for entry in ("帮助中心", "关于平台"):
    show_nav(st.sidebar, entry)
with account_ui.popover(tr("账户") if st.session_state.get("auth_token") else tr("游客")):
    if not st.session_state.get("auth_token"):
        st.caption(tr("游客分析不会自动长期保存，请及时下载结果。"))
    show_nav(st, "账户")

# Keep scalar analysis controls across views. Upload bytes are retained by the uploader callback.
prefixes = ("delimiter_", "header_", "mapping_", "coverage_", "research_", "chart_mode_", "report_setting_", "alignment_setting_")
controls = {"fasta_example", "blast_example", "sequence_type", "identity", "evalue",
            "alignment_length", "coverage_cutoff", "project_name", "project_species", "project_target", "workspace_auto"}
for key in list(st.session_state):
    if key in controls or key.startswith(prefixes):
        st.session_state[key] = st.session_state[key]

navigation[page]()
if page not in ("账户", "我的项目") and st.session_state.get("workspace_auto") and st.session_state.get("auth_token"):
    if store := get_store():
        with st.sidebar:
            autosave(store, st.session_state["auth_token"])
