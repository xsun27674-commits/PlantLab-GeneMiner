"""Plotly figures derived from current session data."""

import pandas as pd
import plotly.express as px

GREEN = ["#147756", "#79B898"]
LABELS = {
    "pident": "Identity (%)",
    "length": "Alignment length",
    "qseqid": "Query",
    "sseqid": "Subject",
    "qcovs": "Query coverage · qcovs (%)",
    "qcovhsp": "Query coverage · qcovhsp (%)",
    "count": "命中数量",
}


def histogram(frame, field):
    figure = px.histogram(frame, x=field, labels=LABELS, color_discrete_sequence=GREEN)
    figure.update_yaxes(title="记录数")
    return figure


def coverage_scatter(hits, field, grouped=False):
    return px.scatter(
        hits.dropna(subset=[field]), x="pident", y=field,
        color="qseqid" if grouped else None,
        hover_data=[name for name in ("qseqid", "sseqid", "pident", "qcovs",
                                    "qcovhsp", "bitscore", "evalue") if name in hits],
        labels=LABELS, color_discrete_sequence=GREEN,
    )


def query_bars(counts, grouped=False):
    return px.bar(counts, x="qseqid", y="候选数量", labels=LABELS, color="qseqid" if grouped else None,
                  color_discrete_sequence=GREEN)


def hit_comparison(before, after):
    counts = pd.DataFrame({"阶段": ["筛选前", "筛选后"], "命中数量": [before, after]})
    return px.bar(counts, x="阶段", y="命中数量", color="阶段", text_auto=True,
                  color_discrete_sequence=GREEN).update_layout(showlegend=False)


def distribution(frame, field, label, id_field, mode="自动", query_colors=False, hover=()):
    """Use categorical per-record bars for small samples and bounded bins for larger ones."""
    mode = ("柱状图" if len(frame) <= 20 else "直方图") if mode == "自动" else mode
    points = frame.copy()
    group = "qseqid" if query_colors and "qseqid" in points else None
    labels = {**LABELS, field: label, "_record": id_field}
    if mode == "直方图":
        figure = px.histogram(points, x=field, color=group, labels=labels, barmode="overlay")
        count = max(1, min(40, round(len(points) ** 0.5)))
        if not points.empty:
            low, high = points[field].min(), points[field].max()
            span = float(high - low)
            size = span / count if span else 1.0
            figure.update_traces(xbins=dict(start=float(low) - size / 2, end=float(high) + size, size=size))
        figure.update_yaxes(title="记录数", rangemode="tozero")
        return figure
    ids = points[id_field].astype(str)
    points["_record"] = ids
    repeated = ids.duplicated(keep=False)
    points.loc[repeated, "_record"] = ids[repeated] + " · " + (points.groupby(id_field).cumcount()[repeated] + 1).astype(str)
    chart = px.bar if mode == "柱状图" else px.scatter
    figure = chart(points, x="_record", y=field, color=group, labels=labels,
                   hover_data=list(hover), category_orders={"_record": points["_record"].tolist()})
    figure.update_layout(meta={"category_labels": dict(zip(points["_record"], ids))})
    figure.update_xaxes(type="category")
    figure.update_yaxes(rangemode="tozero")
    return figure
