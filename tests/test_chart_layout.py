from html import unescape

import pandas as pd

from src.chart_editor import ChartStyle, apply_style, fit_category_axis, fit_query_legend
from src.visualization import coverage_scatter, distribution


def test_sparse_ticks_keep_all_records_and_original_ids():
    source = [f"SIM_Q{i:03d}_extended_sequence_id" for i in range(63)]
    source.append(source[0])
    data = pd.DataFrame({"id": source, "length": range(64)})
    original = distribution(data, "length", "Length", "id", mode="柱状图")
    figure = apply_style(original, ChartStyle("Length", "Sequence ID", "Length"))
    fit_category_axis(figure)
    assert len(figure.data[0].x) == len(source)
    assert 0 < len(figure.layout.xaxis.tickvals) < len(source)
    assert all(unescape(label.replace("<br>", "")) in source for label in figure.layout.xaxis.ticktext)
    assert figure.layout.xaxis.title.text == "Sequence ID"
    assert figure.layout.margin.b > 55


def test_short_category_labels_all_displayed():
    identifiers = ["Q01", "Q02", "Q03", "Q04"]
    data = pd.DataFrame({"id": identifiers, "length": [1, 2, 3, 4]})
    figure = apply_style(distribution(data, "length", "Length", "id"),
                         ChartStyle("Length", "Sequence ID", "Length"))
    fit_category_axis(figure)
    assert list(figure.layout.xaxis.ticktext) == identifiers


def test_full_legend_gets_its_own_space():
    ids = [f"Query-{index:02d}-植株_extended_identifier" for index in range(24)]
    hits = pd.DataFrame({"qseqid": ids, "pident": 90, "qcovs": 80})
    figure = apply_style(coverage_scatter(hits, "qcovs", grouped=True),
                         ChartStyle("Coverage", "Identity", "Coverage", query_colors=True))
    original_height = figure.layout.height
    fit_query_legend(figure)
    assert [unescape(trace.name.replace("<br>", "")) for trace in figure.data] == ids
    assert figure.layout.legend.yref == "container"
    assert figure.layout.legend.orientation == "h"
    assert figure.layout.height > original_height
