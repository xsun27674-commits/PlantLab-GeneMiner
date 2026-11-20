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


def readable_query_legend(figure, data):
    if "Query Name" in data:
        names = dict(zip(data["qseqid"], data["Query Name"]))
        for trace in figure.data:
            if trace.name in names and pd.notna(names[trace.name]):
                trace.name = names[trace.name]
    return figure


def coverage_scatter(hits, field, grouped=False):
    figure = px.scatter(
        hits.dropna(subset=[field]), x="pident", y=field,
        color="qseqid" if grouped else None,
        hover_data=[name for name in ("Query Name", "Subject Name", "Query Gene", "Subject Gene",
                                    "Query Accession", "Subject Accession", "Query Sequence ID", "Subject Sequence ID",
                                    "qseqid", "sseqid", "pident", "qcovs", "qcovhsp", "bitscore", "evalue") if name in hits],
        labels=LABELS, color_discrete_sequence=GREEN,
    )
    return readable_query_legend(figure, hits)


def query_bars(counts, grouped=False):
    figure = px.bar(counts, x="候选数量", y="qseqid", orientation="h", labels=LABELS,
                    color="qseqid" if grouped else None,
                    hover_data=[field for field in ("Query Name", "Query Sequence ID", "Query Gene", "Query Accession") if field in counts],
                    color_discrete_sequence=GREEN)
    if "Query Name" in counts:
        figure.update_layout(meta={"category_labels": dict(zip(counts["qseqid"], counts["Query Name"]))})
    figure.update_yaxes(type="category", categoryorder="array", categoryarray=counts["qseqid"].tolist())
    return readable_query_legend(figure, counts)


def hit_comparison(before, after):
    counts = pd.DataFrame({"阶段": ["筛选前", "筛选后"], "命中数量": [before, after]})
    return px.bar(counts, x="阶段", y="命中数量", color="阶段", text_auto=True,
                  color_discrete_sequence=GREEN).update_layout(showlegend=False)


def distribution(frame, field, label, id_field, mode="自动", query_colors=False, hover=(), *, horizontal=False):
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
        return readable_query_legend(figure, points)
    ids = points[id_field].astype(str)
    points["_record"] = ids
    repeated = ids.duplicated(keep=False)
    points.loc[repeated, "_record"] = ids[repeated] + " · " + (points.groupby(id_field).cumcount()[repeated] + 1).astype(str)
    chart = px.bar if mode == "柱状图" else px.scatter
    x, y = (field, "_record") if horizontal else ("_record", field)
    figure = chart(points, x=x, y=y, color=group, labels=labels,
                   hover_data=list(hover), category_orders={"_record": points["_record"].tolist()})
    figure.update_layout(meta={"category_labels": dict(zip(points["_record"], ids))})
    if horizontal:
        figure.update_yaxes(type="category", categoryorder="array", categoryarray=points["_record"].tolist())
        figure.update_xaxes(rangemode="tozero")
    else:
        figure.update_xaxes(type="category")
        figure.update_yaxes(rangemode="tozero")
    return readable_query_legend(figure, points)
