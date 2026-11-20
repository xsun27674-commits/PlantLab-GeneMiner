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


def test_horizontal_sequence_labels_remain_readable_and_keep_all_points():
    for count in (12, 32, 75):
        labels = [f"MLH1 · NM_{index:06}.1" for index in range(count)]
        data = pd.DataFrame({"Name": labels, "length": range(count)})
        figure = apply_style(distribution(data, "length", "Length", "Name",
                                          mode="柱状图", horizontal=True),
                             ChartStyle("Length", "Length", "Name"))
        fit_category_axis(figure)
        assert list(figure.data[0].y) == labels
        assert list(figure.layout.yaxis.tickvals) == labels
        assert [unescape(tick.replace("<br>", "")) for tick in figure.layout.yaxis.ticktext] == labels
        assert figure.layout.yaxis.range[0] == min(50, count) - .5


def test_fasta_scatter_keeps_numeric_order_and_full_hover():
    rows = pd.DataFrame({"Name": [f"CDS_{i}" for i in range(63)], "Sequence ID": "original",
                         "Gene": "SIM", "Accession": "SIM_1", "length": list(range(63))})
    figure = apply_style(distribution(rows, "length", "Length", "Name", "散点图",
                                      hover=("Sequence ID", "Gene", "Accession"), sequence_scatter=True),
                         ChartStyle("Length", "序列编号", "Length"))
    fit_category_axis(figure)
    assert list(figure.data[0].x) == list(range(1, 64))
    assert figure.layout.xaxis.showticklabels is False and figure.layout.xaxis.title.text == "序列编号"
    assert set(figure.data[0].customdata[0]) == {"original", "SIM", "SIM_1"}


def test_query_name_only_and_id_fallback():
    from src.visualization import query_bars

    counts = pd.DataFrame({"Query Name": ["MLH1", "HEI10"], "候选数量": [2, 3]})
    assert {trace.name for trace in query_bars(counts, grouped=True).data} == {"MLH1", "HEI10"}
    for mode in ("柱状图", "散点图", "直方图"):
        fig = distribution(counts, "候选数量", "Count", "Query Name", mode, query_colors=True)
        assert {trace.name for trace in fig.data} == {"MLH1", "HEI10"}
    counts["qseqid"] = ["query1", "query2"]
    counts["Query Name"] = ["MLH1", ""]
    assert {trace.name for trace in query_bars(counts, grouped=True).data} == {"MLH1", "query2"}


def test_chart_with_missing_query_columns_shows_warning():
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_string("""
import pandas as pd
from src.chart_editor import ChartStyle, chart_panel
from src.visualization import query_bars
data = pd.DataFrame({"候选数量": [4]})
chart_panel("missing_query", lambda _: query_bars(data), data, ChartStyle("Hits", "Count", "Query"))
""").run()
    assert not app.exception
    assert "qseqid / Query Name" in app.warning[0].value
