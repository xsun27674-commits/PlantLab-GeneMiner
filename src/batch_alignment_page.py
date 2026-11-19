"""Local project batch UI and independent, evidence-based result filtering."""

from datetime import datetime, timezone
from textwrap import wrap

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st
import streamlit.components.v1 as components

from src.batch_alignment import make_plan, matrix_data, run_batch, local_aligner
from src.chart_editor import PLOTLY_SCRIPT, browser_chart
from src.export_utils import csv_bytes, excel_bytes
from src.i18n import tr
from src.timing import session_result


def batch_page(project):
    records = project["records"]
    if len(records) < 2:
        st.info(tr("当前项目至少需要两条核酸序列才能进行批量比对。"))
        return
    display = lambda index: f"{records[index][0]} · #{index + 1}"
    select = st.radio(tr("记录范围"), ["全部序列", "指定序列"], horizontal=True,
                      key="alignment_setting_batch_range", format_func=tr)
    indices = list(range(len(records)))
    if select == "指定序列":
        indices = st.multiselect(tr("选定记录"), indices, format_func=display,
                                 key="alignment_setting_batch_indices", max_selections=32)
    method = st.radio(tr("比较方式"), ["两两比较", "单查询对其余序列"], horizontal=True, format_func=tr,
                      key="alignment_setting_batch_method")
    query = None
    if method == "单查询对其余序列" and indices:
        query = st.selectbox(tr("查询记录"), indices, format_func=display, key="alignment_setting_batch_query")
    mode = st.radio(tr("比对模式"), ("global", "local"), horizontal=True,
                    format_func=lambda name: tr("全局比对" if name == "global" else "局部比对"),
                    key="alignment_setting_batch_mode")
    scores = tuple(col.number_input(tr(label), -100.0, 100.0, value, step=.5,
                                    key=f"alignment_setting_batch_score{i}")
                   for i, (col, label, value) in enumerate(zip(
                   st.columns(4), ("匹配评分", "错配评分", "Gap 开启", "Gap 延伸"), (2.0, -1.0, -3.0, -1.0))))
    try:
        clean, pairs, cells = make_plan(records, indices, query)
    except ValueError as exc:
        st.info(tr(str(exc)))
        return
    fingerprint = (project["key"], tuple(indices), query, mode, scores)
    stored = st.session_state.get("batch_alignment")
    st.caption(f'{tr("按估算的动态规划单元数控制计算量")} · {len(pairs)} {tr("对")} · {cells:,} cells')
    st.caption(tr("一致性以全部比对列为分母，包含缺口列。无正分局部比对时一致性留空。"))
    if st.button(tr("运行批量比对"), type="primary") and (not stored or stored["key"] != fingerprint):
        bar = st.progress(0)
        try:
            results = run_batch(records, clean, pairs, mode, scores, bar.progress)
        except ValueError as exc:
            st.error(tr(str(exc)))
            return
        finally:
            bar.empty()
        stored = {"key": fingerprint, "results": results, "pairs": pairs, "time": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        st.session_state["batch_alignment"] = stored
    if not stored or stored["key"] != fingerprint:
        return

    results = stored["results"]
    st.session_state["pairwise_record"] = {
        "上传文件名称": project["name"], "输入来源": project["origin"],
        "分析时间（UTC）": stored["time"], "比对模式": mode, "本地比对数": len(results),
        **dict(zip(("Match", "Mismatch", "Gap open", "Gap extend"), scores)),
    }
    metadata = {"Source file": project["name"], "Origin": project["origin"], "Mode": mode,
                "Calculated (UTC)": stored["time"],
                **dict(zip(("Match", "Mismatch", "Gap open", "Gap extend"), scores))}
    st.caption(f'{project["name"]} · {tr(project["origin"])} · {stored["time"]}')
    with st.expander(tr("本地比对结果筛选")):
        minimum = st.slider(tr("最低一致性 (%)"), 0, 100, 0)
        aligned = st.number_input(tr("最短比对长度"), min_value=0, value=0)
    keep = (results["Alignment Length"] >= aligned) & (results["Identity (%)"].fillna(-1) >= minimum)
    if minimum == aligned == 0:
        keep[:] = True
    screened = results.loc[keep]
    st.dataframe(screened, hide_index=True)
    exported = screened.assign(**metadata)
    left, right = st.columns(2)
    left.download_button("CSV", csv_bytes(exported), "local_alignment.csv", "text/csv", on_click="ignore")
    right.download_button("Excel", excel_bytes(exported, exported.iloc[:0], {"Local alignment": metadata}),
                          "local_alignment.xlsx",
                          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", on_click="ignore")
    metric = st.radio(tr("相似性热图"), ("Identity (%)", "Alignment Score"), horizontal=True)
    render_matrix(results, pairs, indices, query, display, metric)

    pair_index = st.selectbox(tr("查看指定序列对"), list(screened.index),
                              format_func=lambda row: f"{display(pairs[row][0])} ↔ {display(pairs[row][1])}")
    if pair_index is not None:
        first, second = pairs[pair_index]
        first_id, second_id = records[first][0], records[second][0]
        aligner = local_aligner(mode, scores)
        # Only materialize display text for the selected pair, never the entire batch.
        def detail():
            alignment = next(iter(aligner.align(clean[first], clean[second])), None)
            return str(alignment) if alignment is not None else tr("没有找到正分的局部比对。")
        body = session_result("batch_detail", (fingerprint, pair_index), detail)
        st.caption(tr("符号：| 匹配，. 错配，- 缺口。位置由 Biopython 输出。"))
        st.code(body, language=None)
        text = f"Query: {first_id}\nSubject: {second_id}\n" + "\n".join(
            f"{key}: {value}" for key, value in metadata.items()) + "\n\n" + body
        st.download_button(tr("下载比对文本"), text, "local_alignment_detail.txt", "text/plain", on_click="ignore")


def render_matrix(results, pairs, indices, query, display, metric):
    rows, values = matrix_data(results, pairs, indices, metric, query is None, query)
    labels = [display(index) for index in indices]
    row_labels = [display(index) for index in rows]
    longest = max(len(label) for label in labels)
    margin = min(440, max(135, int(longest * 6.5)))
    width = max(880, 230 + margin + 34 * len(labels))
    height = max(390, 140 + margin + 22 * len(rows))
    figure = go.Figure(go.Heatmap(z=values, x=labels, y=row_labels, colorscale="Viridis",
                                 hovertemplate="%{y} → %{x}: %{z:.3f}<extra></extra>"))
    figure.update_layout(title_text=metric, width=width, height=height,
                         margin=dict(l=margin, r=105, b=margin, t=65),
                         font=dict(size=11), xaxis=dict(title="Subject", tickangle=-70),
                         yaxis=dict(title="Query", autorange="reversed"))
    for axis, raw in ((figure.update_xaxes, labels), (figure.update_yaxes, row_labels)):
        axis(tickmode="array", tickvals=raw,
             ticktext=["<br>".join(wrap(label, width=38)) for label in raw], automargin=True)
    name = "local_identity_matrix" if metric == "Identity (%)" else "local_score_matrix"
    html = pio.to_html(figure, full_html=False, include_plotlyjs=PLOTLY_SCRIPT, div_id="chart",
                       config={"displaylogo": False, "modeBarButtonsToRemove": ["toImage"]})
    rendered = browser_chart(html, name, figure.layout).replace("overflow:hidden", "overflow:auto")
    components.html(rendered, height=height + 85, scrolling=True)
