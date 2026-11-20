"""Background batch controls, similarity matrices and independent candidate screening."""

from datetime import datetime, timezone
from hashlib import sha256
from html import escape
from math import ceil
from pathlib import Path
from textwrap import wrap

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st
import streamlit.components.v1 as components

from src.batch_alignment import AlignmentJob, make_plan, matrix_data, local_aligner, similarity_order
from src.chart_editor import PLOTLY_SCRIPT, browser_chart
from src.export_utils import csv_bytes, excel_bytes
from src.i18n import tr
from src.project_data import current_candidates, record_info, record_labels, project_status
from src.timing import session_result


matrix_component = components.declare_component("plantlab_matrix", path=str(Path(__file__).parent / "matrix_component"))


def go_to(page):
    st.session_state["next_page"] = page
    st.rerun()


def flow_actions(next_page=None):
    left, right = st.columns(2)
    if left.button(tr("← 返回 FASTA 序列分析")):
        go_to("FASTA 序列分析")
    if next_page and right.button(tr("下一步：本地比对候选筛选 →"), type="primary"):
        go_to(next_page)


def collect_job():
    job = st.session_state.get("_batch_job")
    if not job:
        return
    state, completed, elapsed, results = job.status()
    if state not in ("done", "cancelled", "failed"):
        return
    st.session_state.pop("_batch_job")
    st.session_state["_batch_outcome"] = (state, completed, job.total, elapsed)
    project = st.session_state.get("project_sequences")
    if not project or project["key"] != job.key[0]:
        return
    if state == "cancelled":
        st.session_state["_batch_checkpoint"] = (job.key, job.rows)
    if state == "done":
        st.session_state.pop("_batch_checkpoint", None)
        stored = {"key": job.key, "results": results, "pairs": job.pairs, "elapsed": elapsed,
                  "time": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        history = st.session_state.get("_batch_history", [])
        st.session_state.get("report_figures", {}).pop("local_alignment_matrix", None)
        st.session_state["_batch_history"] = [stored, *[item for item in history if item["key"] != job.key]][:3]
        st.session_state["batch_alignment"] = stored


@st.fragment(run_every=1)
def running_job():
    job = st.session_state.get("_batch_job")
    if not job:
        st.rerun()
    state, completed, elapsed, _ = job.status()
    if state in ("done", "cancelled", "failed"):
        collect_job()
        st.rerun()
    st.progress(completed / job.total,
                text=f"{tr('已完成')} {completed:,}/{job.total:,} · {elapsed:.1f} s · {tr('排队中' if state == 'queued' else '计算中')}")
    if st.button(tr("取消任务"), disabled=job.cancel.is_set()):
        job.cancel.set()
        st.caption(tr("取消将在当前序列对计算结束后生效。"))


def batch_page(project):
    collect_job()
    records = project["records"]
    labels = record_labels(project)
    if len(records) < 2:
        st.info(tr("当前项目至少需要两条核酸序列才能进行批量比对。"))
        flow_actions()
        return
    if st.session_state.get("_batch_job"):
        running_job()
        flow_actions()
        return
    outcome = st.session_state.get("_batch_outcome")
    if outcome and outcome[0] != "done":
        label = "任务已取消。使用相同参数可从当前会话的检查点继续。" if outcome[0] == "cancelled" else "任务失败，请减少输入或使用更短序列。"
        st.warning(f"{tr(label)} {outcome[1]}/{outcome[2]} · {outcome[3]:.1f} s")

    select = st.radio(tr("记录范围"), ["全部序列", "指定序列"], horizontal=True,
                      key="alignment_setting_batch_range", format_func=tr)
    indices = list(range(len(records)))
    if select == "指定序列":
        indices = st.multiselect(tr("选定记录"), indices, format_func=labels.__getitem__,
                                 key="alignment_setting_batch_indices")
    method = st.radio(tr("比较方式"), ["两两比较", "单查询对其余序列", "按基因分组"], horizontal=True, format_func=tr,
                      key="alignment_setting_batch_method")
    st.caption(tr({"两两比较": "比较选定范围中的每个唯一序列对。",
                   "单查询对其余序列": "仅比较查询序列与选定范围中的其它序列。",
                   "按基因分组": "仅比较同一已知基因的不同记录。缺少基因信息的记录不参与。"}[method]))
    query = None
    if method == "单查询对其余序列" and indices:
        query = st.selectbox(tr("查询记录"), indices, format_func=labels.__getitem__, key="alignment_setting_batch_query")
    include_self = method == "两两比较" and st.checkbox(tr("包含自比对"), key="alignment_setting_include_self")
    mode = st.radio(tr("比对模式"), ("global", "local"), horizontal=True,
                    format_func=lambda name: tr("全局比对" if name == "global" else "局部比对"),
                    key="alignment_setting_batch_mode")
    scores = tuple(col.number_input(tr(label), -100.0, 100.0, value, step=.5,
                                    key=f"alignment_setting_batch_score{i}")
                   for i, (col, label, value) in enumerate(zip(
                   st.columns(4), ("匹配评分", "错配评分", "Gap 开启", "Gap 延伸"), (2.0, -1.0, -3.0, -1.0))))
    fingerprint = (project["key"], tuple(indices), query, mode, scores, include_self)
    groups = None
    if method == "按基因分组":
        fingerprint += ("grouped",)
        groups = {}
        for index in indices:
            item = record_info(project, index)
            groups[index] = (("id", item["gene_id"]) if item["gene_id"] else
                             (item["species"], item["gene"]) if item["species"] and item["gene"] else None)
    history = st.session_state.get("_batch_history", [])
    active = st.session_state.get("batch_alignment")
    if active and active["key"] != fingerprint:
        st.session_state["_batch_history"] = history = [active, *[item for item in history if item["key"] != active["key"]]][:3]
        st.session_state.pop("batch_alignment")
        st.session_state.get("report_figures", {}).pop("local_alignment_matrix", None)
        for key in ("local_candidate_comparison", "local_candidate_identity"):
            st.session_state.get("report_figures", {}).pop(key, None)

    try:
        clean, pairs, cells = session_result("batch_plan", fingerprint, lambda: make_plan(
            records, indices, query, include_self=include_self, groups=groups))
    except ValueError as exc:
        st.info(tr(str(exc)))
        flow_actions()
        return

    st.caption(f'{tr("按估算的动态规划单元数控制计算量")} · {len(pairs):,} {tr("对")} · {cells:,} cells')
    st.caption(tr("一致性以全部比对列为分母，包含缺口列。无正分局部比对时一致性留空。"))
    stored = next((item for item in [active, *history] if item and item["key"] == fingerprint), None)
    checkpoint = st.session_state.get("_batch_checkpoint")
    prior_rows = checkpoint[1] if checkpoint and checkpoint[0] == fingerprint else ()
    if prior_rows:
        st.caption(f'{tr("检查点")} · {len(prior_rows):,}/{len(pairs):,}')
    if st.button(tr("继续批量比对" if prior_rows else "运行批量比对"), type="primary") and not stored:
        try:
            st.session_state["_batch_job"] = AlignmentJob(fingerprint, records, clean, pairs, mode, scores, checkpoint=prior_rows)
        except ValueError as exc:
            st.error(tr(str(exc)))
        else:
            st.rerun()
    if not stored:
        flow_actions()
        return
    st.session_state["batch_alignment"] = stored

    results = stored["results"]
    st.progress(1.0, text=f"{tr('已完成')} {len(results):,}/{len(pairs):,} · {stored.get('elapsed', 0):.1f} s")
    metadata = export_metadata(project, stored)
    dataset = session_result("batch_annotations", fingerprint, annotate_results, project, stored)
    st.dataframe(dataset, hide_index=True)
    downloads(dataset, metadata, "local_alignment", "alignment")
    picked = matrix_panel(project, stored, indices, query, labels)
    render_pair_picker(project, stored, list(results.index), "batch", picked)
    flow_actions("本地比对候选筛选")


def render_pair_picker(project, stored, options, view, picked=None, *, show_sequences=False):
    if not options:
        return
    pairs = stored["pairs"]
    labels = record_labels(project)
    selection_key = f"alignment_setting_{view}_pair"
    click_key = f"_matrix_click_{view}"
    if picked and picked.get("row") in options and picked["id"] != st.session_state.get(click_key):
        st.session_state[click_key] = picked["id"]
        st.session_state[selection_key] = picked["row"]
    minimum = next((i for i in options if pairs[i][0] != pairs[i][1]), options[0])
    if st.session_state.get(selection_key) not in options:
        st.session_state[selection_key] = minimum
    with st.expander(tr("碱基级比对详情"), expanded=picked is not None):
        pair_index = st.selectbox(tr("查看指定序列对"), options,
                                  format_func=lambda i: f"{labels[pairs[i][0]]} ↔ {labels[pairs[i][1]]}",
                                  key=selection_key)
        if st.checkbox(tr("展开碱基比对"), key=f"alignment_setting_{view}_show") or picked:
            render_pair(project, stored, pair_index, labels, view)
        if show_sequences and st.checkbox(tr("显示原始序列"), key=f"alignment_setting_{view}_originals"):
            for index in pairs[pair_index]:
                st.write(labels[index])
                st.code(project["records"][index][1], language=None)


def render_pair(project, stored, index, labels, view):
    first, second = stored["pairs"][index]
    key = stored["key"]
    stats = stored["results"].loc[index]
    metadata = export_metadata(project, stored)
    records = [record_info(project, pos) for pos in (first, second)]
    for role, pos, item in zip(("Query", "Subject"), (first, second), records):
        st.write(f'{role} · {labels[pos]} · {item["original"]}')
    fields = ("Identity (%)", "Alignment Length", "Matches", "Mismatches", "Gaps", "Alignment Score")
    st.caption(" · ".join(f'{name}: {stats[name]:.4g}' for name in fields))

    def detail():
        sequences = ["".join(project["records"][i][1].split()).upper() for i in (first, second)]
        alignment = next(iter(local_aligner(key[3], key[4]).align(*sequences)), None)
        if alignment is None:
            return tr("没有找到正分的局部比对。"), ""
        left, right = alignment[0], alignment[1]
        offsets = [int(alignment.coordinates[i, 0]) for i in range(2)]
        lines = []
        colors = {"gap": "#875300", "match": "#176b4d", "mismatch": "#a42632"}
        for start in range(0, len(left), 60):
            chunk = [strand[start:start + 60] for strand in (left, right)]
            marks = ["gap" if "-" in (a, b) else "match" if a == b else "mismatch"
                     for a, b in zip(*chunk)]
            for i, strand in enumerate(chunk):
                begin = offsets[i] + 1
                offsets[i] += len(strand.replace("-", ""))
                spans = "".join(f'<span style="color:{colors[mark]}">{escape(base)}</span>'
                                for base, mark in zip(strand, marks))
                lines.append(f'{"Query  " if i == 0 else "Subject"} {begin:>6}  {spans}  {offsets[i]:>6}')
            lines.append("")
        return str(alignment), '<pre style="overflow:auto;max-height:24rem">' + "\n".join(lines) + "</pre>"

    body, colored = session_result("batch_detail", (key, index, st.session_state.get("language")), detail)
    st.caption(tr("颜色：绿为匹配，红为错配，棕为缺口。两侧为 1 起始的碱基位置。"))
    if colored:
        st.html(colored)
    else:
        st.info(body)
    header = [f'{role}: {labels[pos]} | {item["original"]} | {item["accession"]} | {item["id"]}'
              for role, pos, item in zip(("Query", "Subject"), (first, second), records)]
    header += [f"{name}: {value}" for name, value in metadata.items()]
    header += [f"{name}: {stats[name]}" for name in (*fields, "Algorithm")]
    st.download_button(tr("下载比对文本"), "\n".join(header) + "\n\n" + body,
                       "local_alignment_detail.txt", "text/plain", on_click="ignore", key=f"txt_{view}")


def export_metadata(project, stored):
    key = stored["key"]
    return {"Source file": project["name"], "Origin": project["origin"], "Mode": key[3],
            "Calculated (UTC)": stored["time"], "Comparisons": len(stored["results"]),
            **dict(zip(("Match", "Mismatch", "Gap open", "Gap extend"), key[4]))}


def annotate_results(project, stored):
    result = stored["results"].copy()
    labels = record_labels(project)
    for pos, side in enumerate(("Query", "Subject")):
        records = [record_info(project, pair[pos]) for pair in stored["pairs"]]
        result.insert(pos, f"{side} Name", [labels[pair[pos]] for pair in stored["pairs"]])
        for key, column in (("original", "Original Sequence ID"), ("gene", "Gene"), ("accession", "Accession"),
                            ("transcript", "Transcript"), ("species", "Species"), ("gene_id", "Gene ID"), ("id", "Internal ID")):
            result[f"{side} {column}"] = [item[key] or ("待核实" if key == "gene" else "") for item in records]
    return result


def downloads(frame, metadata, filename, key):
    left, right = st.columns(2)
    exported = frame if key == "matrix" else frame.assign(**metadata)
    left.download_button("CSV", csv_bytes(exported), f"{filename}.csv", "text/csv", on_click="ignore", key=f"csv_{key}")
    # Cache only the last workbook for each export so toggling a detail or metric does not rebuild it.
    fingerprint = (tuple(frame.columns), tuple(metadata.items()), pd.util.hash_pandas_object(frame).to_numpy().tobytes())
    workbook = session_result(f"alignment_excel_{key}", fingerprint, excel_bytes,
                              frame, frame.iloc[:0], {"Local alignment": metadata})
    right.download_button("Excel", workbook, f"{filename}.xlsx",
                          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                          on_click="ignore", key=f"xlsx_{key}")


def filter_candidates(results, reference, thresholds, exclude_self, sort_by):
    keep = pd.Series(True, index=results.index)
    if reference:
        keep &= results["Query Internal ID"].eq(reference) | results["Subject Internal ID"].eq(reference)
    if exclude_self:
        keep &= results["Query Internal ID"].ne(results["Subject Internal ID"])
    for field, limit in thresholds.items():
        if limit is not None:
            keep &= results[field].le(limit) if field == "Gaps" else results[field].ge(limit)
    return results.loc[keep].sort_values(sort_by, ascending=sort_by == "Gaps", kind="stable")


def local_candidates_page():
    st.title(tr("本地比对候选筛选"))
    collect_job()
    project_status()
    project = st.session_state.get("project_sequences")
    stored = st.session_state.get("batch_alignment")
    st.info(tr("本地相似序列初筛使用 PairwiseAligner 实测指标。基因功能和直系同源关系需独立验证。"))
    if not project or not stored or stored["key"][0] != project["key"]:
        st.info(tr("当前项目尚无已完成的本地批量比对。"))
    else:
        a, b, c = st.columns(3)
        minimum = a.slider(tr("最低一致性 (%)"), 0, 100, 0, key="alignment_setting_candidates_identity")
        length = b.number_input(tr("最短比对长度"), min_value=0, value=0, key="alignment_setting_candidates_length")
        score = c.number_input(tr("最低比对得分"), value=None, key="alignment_setting_candidates_score")
        a, b, c = st.columns(3)
        gaps = c.number_input(tr("最大缺口碱基数"), min_value=0, value=None, key="alignment_setting_candidates_gaps")
        thresholds = {"Identity (%)": minimum, "Alignment Length": length, "Alignment Score": score, "Gaps": gaps}
        results = session_result("batch_annotations", stored["key"], annotate_results, project, stored)
        if "Query Coverage (%)" in results:
            thresholds["Query Coverage (%)"] = a.slider(tr("最低 Query 覆盖度 (%)"), 0, 100, 0, key="alignment_setting_candidates_qcov")
            thresholds["Subject Coverage (%)"] = b.slider(tr("最低 Subject 覆盖度 (%)"), 0, 100, 0, key="alignment_setting_candidates_scov")
            st.caption(tr("覆盖度按比对区域内消耗的碱基数除以对应原序列全长计算，方向以表格的 Query 和 Subject 为准。"))
        labels = dict(zip((record_info(project, i)["id"] for i in range(len(project["records"]))),
                          record_labels(project)))
        reference = st.selectbox(tr("参考序列"), [None, *labels], key="alignment_setting_candidates_reference",
                                 format_func=lambda value: labels[value] if value is not None else tr("全部"))
        exclude = st.checkbox(tr("排除自比对"), value=True, key="alignment_setting_candidates_exclude")
        order = st.selectbox(tr("排序指标"), list(thresholds), key="alignment_setting_candidates_sort")
        selected = filter_candidates(results, reference, thresholds, exclude, order)
        settings = {"key": stored["key"], "minimum_identity": minimum, "minimum_length": length,
                    "minimum_score": score, "count": len(selected), "thresholds": thresholds,
                    "reference": reference, "exclude_self": exclude, "sort": order, "before": len(results)}
        previous = current_candidates()
        if previous is None or any(previous.get(name) != value for name, value in settings.items()):
            figures = st.session_state.get("report_figures", {})
            for key in ("local_candidate_comparison", "local_candidate_identity"):
                figures.pop(key, None)
        st.session_state["local_candidates_record"] = {**settings, "results": selected}
        st.caption(f"{len(selected):,} / {len(results):,} {tr('对')}")
        st.dataframe(selected, hide_index=True)
        downloads(selected, {**export_metadata(project, stored), **{f"Filter {key}": val for key, val in thresholds.items()},
                             "Reference Internal ID": reference, "Exclude self": exclude, "Sort": order},
                  "local_candidates", "candidates")
        render_pair_picker(project, stored, list(selected.index), "candidate", show_sequences=True)
        if st.button(tr("下一步：结果可视化 →"), type="primary"):
            st.session_state["result_view"] = "local"
            go_to("结果可视化")
    if st.button(tr("← 返回成对序列比对")):
        go_to("成对序列比对")


def matrix_panel(project, stored, indices, query, labels):
    metric = st.radio(tr("相似性热图"), ("Identity (%)", "Alignment Score"), horizontal=True,
                      key="alignment_setting_matrix_metric")
    ordering = ["按基因排序", "输入顺序"]
    if query is None and len(stored["key"]) == 6:
        ordering.append("按相似性聚类")
    order = st.selectbox(tr("序列排序"), ordering, format_func=tr, key="alignment_setting_matrix_order")
    indices = list(indices)
    if order == "按基因排序":
        indices.sort(key=lambda idx: (not record_info(project, idx)["gene"], labels[idx].casefold(), idx))
    elif order == "按相似性聚类":
        st.caption(tr("使用一致性距离进行平均连接排序，仅用于探索相似性，不是系统发育分析。"))
        try:
            indices = session_result("alignment_order", stored["key"], similarity_order,
                                     stored["results"], stored["pairs"], indices)
        except ValueError as exc:
            st.warning(tr(str(exc)))
    small = len(indices) <= 12
    numbers = small and st.checkbox(tr("在单元格显示数值"), key="alignment_setting_matrix_numbers")
    color_range = (0, 100)
    if metric == "Identity (%)":
        color_range = st.slider(tr("一致性色标 (%)"), 0, 100, (0, 100), key="alignment_setting_matrix_scale")
    row_ids, values = matrix_data(stored["results"], stored["pairs"], indices, metric, query is None, query)
    xlabels, ylabels = [labels[idx] for idx in indices], [labels[idx] for idx in row_ids]
    row_label = next(name for name in ("Query", *(f"Query [{i}]" for i in range(len(xlabels) + 1)))
                     if name not in xlabels)
    matrix = pd.DataFrame(values, index=ylabels, columns=xlabels).reset_index(names=row_label)
    if query is None and not stored["key"][5]:
        st.caption(tr("默认不计算自比对，矩阵对角线留空。"))
    if not small:
        st.caption(tr("大矩阵按需显示坐标标签。悬停可查看完整信息，下载表格可取得完整矩阵。"))
    stem = "local_identity_matrix" if metric == "Identity (%)" else "local_score_matrix"
    downloads(matrix, export_metadata(project, stored), stem, "matrix")
    figure = session_result("alignment_figure", (stored["key"], order, metric, numbers, color_range),
                            build_matrix_figure, project, values, indices, row_ids, xlabels, ylabels, metric, numbers,
                            stored, color_range)
    st.session_state.setdefault("report_figures", {})["local_alignment_matrix"] = (metric, figure)
    click_script = """
    document.getElementById("chart").on("plotly_click", event => {
        const data = event.points[0]?.customdata;
        if (data && Number.isInteger(data[3])) {
            parent.postMessage({type: "plantlab_pair", row: data[3]}, "*");
        }
    });"""
    html = pio.to_html(figure, full_html=False, include_plotlyjs=PLOTLY_SCRIPT, div_id="chart", post_script=click_script,
                       config={"displaylogo": False, "modeBarButtonsToRemove": ["toImage"], "scrollZoom": True})
    rendered = browser_chart(html, stem, figure.layout).replace("overflow:hidden", "overflow:auto")
    component_key = sha256(repr(stored["key"]).encode()).hexdigest()
    return matrix_component(html=rendered, height=min(1150, figure.layout.height + 84),
                            key=f"matrix_{component_key}", default=None)


def build_matrix_figure(project, values, indices, row_ids, xlabels, ylabels, metric, numbers,
                        stored, color_range):
    records = {index: record_info(project, index) for index in indices}
    hover = {index: "<br>".join(escape(item[field] or "—") for field in ("original", "gene", "accession"))
             for index, item in records.items()}
    row_lookup = {pair: i for i, pair in enumerate(stored["pairs"])}
    lengths = stored["results"]["Alignment Length"].tolist()
    metadata = []
    for first in row_ids:
        row = []
        for second in indices:
            key = row_lookup.get((first, second))
            if key is None and len(row_ids) > 1:
                key = row_lookup.get((second, first))
            length = None if key is None else int(lengths[key])
            row.append((hover[first], hover[second], length, key))
        metadata.append(row)
    z = go.Heatmap(z=values, x=list(range(len(indices))), y=list(range(len(row_ids))),
                   colorscale="Viridis", customdata=metadata, hoverongaps=False,
                   hovertemplate="Query ID / Gene / Accession:<br>%{customdata[0]}<br><br>"
                                 "Subject ID / Gene / Accession:<br>%{customdata[1]}<br><br>"
                                 + metric + ": %{z:.3f}<br>Alignment length: %{customdata[2]}<extra></extra>")
    if metric == "Identity (%)":
        low, high = color_range
        z.update(zmin=low, zmax=high if high > low else low + .001)
    if numbers:
        z.texttemplate = "%{z:.1f}"
    margin = max(130, min(280, max(map(len, xlabels)) * 5))
    width = max(800, margin + 140 + min(1850, 23 * len(indices)))
    height = max(430, 250 + min(1850, 19 * len(row_ids)))
    figure = go.Figure(z)
    figure.update_layout(title_text=metric, width=width, height=height,
                         margin=dict(l=margin, r=90, b=155, t=65),
                         font=dict(size=11), xaxis=dict(title="Subject", tickangle=-35),
                         yaxis=dict(title="Query", autorange="reversed"))
    for axis, labels in ((figure.update_xaxes, xlabels), (figure.update_yaxes, ylabels)):
        stride = max(1, ceil(len(labels) / 24))
        ticks = list(range(0, len(labels), stride))
        axis(tickmode="array", tickvals=ticks, automargin=True,
             ticktext=["<br>".join(escape(line) for line in wrap(labels[index], width=30)) for index in ticks])
    return figure
