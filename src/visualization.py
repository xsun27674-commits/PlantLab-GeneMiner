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


def coverage_scatter(hits, field):
    return px.scatter(
        hits.dropna(subset=[field]), x="pident", y=field,
        hover_data=["qseqid", "sseqid"], labels=LABELS, color_discrete_sequence=GREEN,
    )


def query_bars(counts):
    return px.bar(counts, x="qseqid", y="候选数量", labels=LABELS,
                  color_discrete_sequence=GREEN)


def hit_comparison(before, after):
    counts = pd.DataFrame({"阶段": ["筛选前", "筛选后"], "命中数量": [before, after]})
    return px.bar(counts, x="阶段", y="命中数量", color="阶段", text_auto=True,
                  color_discrete_sequence=GREEN).update_layout(showlegend=False)
