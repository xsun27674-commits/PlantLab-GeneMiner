"""Streamlit entry point."""


def main():
    from pathlib import Path

    import streamlit as st
    import streamlit.components.v1 as components

    from src import pages
    from src.account_page import account_page, autosave, get_store, toolbar_profile, workspace_page
    from src.workspace_state import clear
    from src.brand import NAME, brand_mark_uri, help_center, logo_icon
    from src.i18n import tr
    from src.alignment_page import alignment_page
    from src.batch_alignment_page import local_candidates_page

    st.set_page_config(page_title=NAME, page_icon=str(icon) if (icon := logo_icon()) else "🌱", layout="wide")
    st.html(Path(__file__).resolve().parent / "assets" / "shell.css")

    with st.container(key="plantlab_toolbar"):
        _, language_ui, account_ui = st.columns([6, 1, 1.25], vertical_alignment="center")
        language_ui.selectbox("中文 / English", ("zh", "en"), format_func={"zh": "中文", "en": "English"}.get,
                              key="language", label_visibility="collapsed")

    labels = {"FASTA 序列分析": "FASTA 序列统计", "结果可视化": "可视化与报告"}
    navigation = {
        "首页": pages.home,
        "数据导入与管理": pages.sequence_data_page,
        "FASTA 序列分析": pages.fasta,
        "成对序列比对": alignment_page,
        "BLAST 搜索": pages.blast_search,
        "BLAST 候选筛选": pages.blast,
        "本地比对候选筛选": local_candidates_page,
        "结果可视化": pages.visualization,
        "分析结果": pages.show_results,
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
    if page == "分析记录与导出":
        page = st.session_state["page"] = "结果可视化"
        st.session_state["result_section"] = "分析记录与导出"
    comparison = ("成对序列比对", "本地比对候选筛选")
    blast = ("BLAST 搜索", "BLAST 候选筛选")
    groups = (
        ("项目数据", ("数据导入与管理", "FASTA 序列分析")),
        ("序列比较与相似性筛选", comparison),
        ("BLAST 搜索与候选筛选", blast),
        ("结果管理", ("分析结果", "结果可视化")),
    )
    if page in ("FASTA 序列分析", *comparison):
        st.session_state["workflow_path"] = "local"
    elif page in blast:
        st.session_state["workflow_path"] = "blast"
    previous_page = st.session_state.get("_shown_page")
    st.session_state["_shown_page"] = page
    changed_page = previous_page is not None and previous_page != page


    def show_nav(container, key):
        slot = container.container(key="active_nav") if key == page else container
        slot.button(tr(labels.get(key, key)), key=f"nav_{key}", width="stretch",
                    on_click=st.session_state.__setitem__, args=("page", key))


    with st.sidebar.container(key="plantlab_sidebar"):
        st.html(f'<div class="plantlab-brand"><img src="{brand_mark_uri(compact=True)}" alt="">'
                f'<div><strong>{NAME}</strong><small>V3.0 · Beta</small></div></div>')
        show_nav(st, "首页")
        for group, keys in groups:
            with st.expander(tr(group), expanded=page in keys):
                for entry in keys:
                    show_nav(st, entry)
        for entry in ("帮助中心", "关于平台"):
            show_nav(st, entry)

    user = toolbar_profile()
    account_label, account_icon = user if user else (tr("游客"), None)
    with account_ui.popover(
        f"![ ]({account_icon}) {account_label}" if account_icon else account_label,
        icon=None if account_icon else ":material/account_circle:", width="stretch",
    ):
        if user is None:
            st.caption(tr("游客分析不会自动长期保存，请及时下载结果。"))
        show_nav(st, "账户")
        show_nav(st, "我的项目")

    # Keep scalar analysis controls across views. Upload bytes are retained by the uploader callback.
    prefixes = ("local_blast_", "delimiter_", "header_", "mapping_", "coverage_", "research_", "chart_mode_", "report_setting_", "alignment_setting_", "sequence_input_", "ncbi_transcripts_", "ncbi_accessions_")
    controls = {"blast_min_bitscore", "result_view", "result_section", "fasta_example", "blast_example", "sequence_type", "identity", "evalue",
                "alignment_length", "coverage_cutoff", "blast_detail_view", "project_name", "project_species", "project_target", "workspace_auto"}
    for key in list(st.session_state):
        if key in controls or (key != "local_blast_run" and key.startswith(prefixes)):
            st.session_state[key] = st.session_state[key]

    navigation[page]()
    if changed_page:
        components.html("""<script>
          const main = parent.document.querySelector('[data-testid="stMain"]');
          if (main) {
            const input = ["wheel", "touchstart", "pointerdown", "keydown"];
            const top = () => main.scrollTo({top: 0, behavior: "instant"});
            const observer = new parent.ResizeObserver(top);
            const stop = () => {
              observer.disconnect();
              for (const event of input) parent.document.removeEventListener(event, stop, true);
            };
            for (const event of input) parent.document.addEventListener(event, stop, true);
            top();
            parent.requestAnimationFrame(top);
            if (main.firstElementChild) observer.observe(main.firstElementChild);
            setTimeout(stop, 700);
          }
        </script>""", height=0)
    if page not in ("账户", "我的项目") and st.session_state.get("workspace_auto") and st.session_state.get("auth_token"):
        if store := get_store():
            with st.sidebar:
                autosave(store, st.session_state["auth_token"])


if __name__ == "__main__":
    main()
