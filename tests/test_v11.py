import json
import os
from dataclasses import asdict, replace
from io import BytesIO
from xml.etree import ElementTree

import pandas as pd
import plotly.io as pio
import pytest
from PIL import Image

from src.alignment import align_sequences
from src.analysis_record import build_record
from src.blast_utils import REQUIRED, Thresholds, filter_hits, normalize_hits, rejection_reasons
from src.chart_editor import ChartStyle, apply_style, image_bytes, load_style
from src.visualization import distribution


def test_small_samples_have_independent_bars():
    frame = pd.DataFrame({"id": ["a", "a", "b", "c", "d", "e"], "length": [1, 2, 3, 4, 5, 6]})
    figure = distribution(frame, "length", "Length", "id")
    assert figure.data[0].type == "bar"
    assert len(set(figure.data[0].x)) == 6
    assert list(figure.data[0].y) == [1, 2, 3, 4, 5, 6]
    assert distribution(frame.iloc[:1], "length", "Length", "id").data[0].type == "bar"
    histogram = distribution(frame, "length", "Length", "id", "直方图")
    assert histogram.data[0].xbins.size > 0


def test_empty_result_and_rejection_explanation():
    data = pd.DataFrame([["Q", "S", 90, 20, "0", 10, ""]], columns=[*REQUIRED, "qcovs"])
    hits = normalize_hits(data, {name: name for name in data.columns})
    threshold = Thresholds(identity=95, coverage_field="qcovs", coverage=0)
    assert filter_hits(hits, threshold).empty
    assert rejection_reasons(hits, threshold)["排除原因"].tolist() == ["pident 低于阈值；覆盖度缺失"]


def test_align_global_local_protein_and_gap():
    global_hit = align_sequences("ACGT", "AGT", "nucleotide", "global", 2, -1, -2, -1)
    assert (global_hit.matches, global_hit.gaps, global_hit.length, global_hit.identity) == (3, 1, 4, 75)
    assert "-" in global_hit.text
    local_hit = align_sequences("ACDE", "GCDF", "protein", "local", 2, -2, -3, -1)
    assert local_hit.length == 2 and local_hit.identity == 100
    assert align_sequences("AAA", "TTT", "nucleotide", "local", 2, -2, -3, -1) is None
    with pytest.raises(ValueError, match="非法字符"):
        align_sequences("ABC?", "AGT", "nucleotide", "global", 2, -1, -2, -1)
    with pytest.raises(ValueError, match="超过"):
        align_sequences("A" * 3000, "T" * 3000, "nucleotide", "global", 2, -1, -2, -1)


def styled_plot():
    frame = pd.DataFrame({"id": ["植物"], "length": [22]})
    figure = distribution(frame, "length", "长度", "id")
    style = ChartStyle("中文绘图标题", "序列", "长度", color="#94001A", y_range="0, 50")
    return figure, style


def test_styles_round_trip_and_html():
    figure, style = styled_plot()
    restored = load_style(json.dumps(asdict(style), ensure_ascii=False).encode())
    assert restored == style
    plot = apply_style(figure, restored)
    assert plot.data[0].marker.color == "#94001A"
    assert plot.layout.yaxis.range == (0, 50)
    assert "中文绘图标题" in pio.to_html(plot, include_plotlyjs=True)
    with pytest.raises(ValueError):
        apply_style(figure, replace(style, x_range="20,10"))


@pytest.mark.skipif(not os.environ.get("GENEMINER_TEST_IMAGES"), reason="needs working Chrome/Kaleido")
def test_static_images():
    figure, style = styled_plot()
    plot = apply_style(figure, style)
    png = image_bytes(plot, "png")
    with Image.open(BytesIO(png)) as decoded:
        assert decoded.size == (style.width * 2, style.height * 2)
        decoded.verify()
    svg = ElementTree.fromstring(image_bytes(plot, "svg"))
    assert svg.tag.endswith("svg")
    assert any("中文绘图标题" in content for content in svg.itertext())
    assert image_bytes(plot, "pdf").startswith(b"%PDF")


def test_existing_analysis_record():
    record = build_record({"项目名称": "植物分析"}, {"序列数": 6, "key": "session-only"}, {
        "name": "example_blast.tsv", "origin": "模拟教学数据", "timestamp": "2026-11-19T00:00:00+00:00",
        "before": 60, "filtered": pd.DataFrame({"qseqid": ["Q01"]}), "delimiter": "\t",
        "header": "auto", "mapping": {"qseqid": "query"}, "thresholds": Thresholds(evalue="0"),
    })
    assert "key" not in record["FASTA"]
    assert record["筛选阈值"]["evalue"] == "0"
    assert record["BLAST"]["筛选后命中数"] == 1


def test_query_palette_override():
    frame = pd.DataFrame({"qseqid": ["Q1", "Q2"], "sseqid": ["S1", "S2"], "pident": [60, 70]})
    figure = distribution(frame, "pident", "一致性", "sseqid", query_colors=True)
    style = ChartStyle("候选对比", "Subject", "一致性", query_colors=True,
                       query_palette='{"Q2": "#992233"}')
    plot = apply_style(figure, style)
    assert plot.data[0].marker.color == style.color
    assert plot.data[1].name == "Q2"
    assert plot.data[1].marker.color == "#992233"


def test_comparison_class_colors_are_independent():
    from src.visualization import hit_comparison

    figure = hit_comparison(60, 2)
    style = ChartStyle("Comparison", "Stage", "Hits", category_colors=True, legend=False)
    colored = apply_style(figure, style)
    assert [trace.marker.color for trace in colored.data] == ["#9BC9B1", "#176B4D"]
    assert not colored.layout.showlegend
    unified = apply_style(figure, replace(style, category_colors=False))
    assert [trace.marker.color for trace in unified.data] == [style.color, style.color]
