from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / "app.py"


def test_example_workflow_and_navigation():
    app = AppTest.from_file(str(APP), default_timeout=25).run()
    assert not app.exception

    app.sidebar.button(key="nav_FASTA 序列分析").click().run()
    assert not app.exception
    app.checkbox(key="fasta_example").check().run()
    app.radio(key="sequence_type").set_value("nucleotide").run()
    assert not app.exception
    assert len(app.dataframe[0].value) == 6

    app.sidebar.button(key="nav_BLAST 候选筛选").click().run()
    assert not app.exception
    app.checkbox(key="blast_example").check().run()
    app.text_input(key="evalue").set_value("0").run()
    assert not app.exception
    assert [metric.value for metric in app.metric][:2] == ["60", "1"]

    app.sidebar.button(key="nav_结果可视化").click().run()
    assert not app.exception
    assert len(app.get("plotly_chart")) == 5
    app.sidebar.button(key="nav_分析记录与导出").click().run()
    app.text_input(key="research_项目名称").set_value("教学验证").run()
    assert not app.exception
    assert len(app.get("download_button")) == 4

    app.sidebar.button(key="nav_BLAST 候选筛选").click().run()
    assert not app.exception
    assert app.text_input(key="evalue").value == "0"
    assert app.metric[1].value == "1"

    app.sidebar.button(key="nav_分析记录与导出").click().run()
    assert app.text_input(key="research_项目名称").value == "教学验证"


def test_lightweight_preview_keeps_interactive_export(monkeypatch):
    monkeypatch.setenv("GENEMINER_LIGHTWEIGHT_PREVIEW", "1")
    app = AppTest.from_file(str(APP), default_timeout=25).run()
    app.sidebar.button(key="nav_FASTA 序列分析").click().run()
    app.checkbox(key="fasta_example").check().run()
    app.radio(key="sequence_type").set_value("nucleotide").run()
    assert not app.exception
    assert len(app.get("plotly_chart")) == 2
    assert not any(button.label == "生成静态图" for button in app.button)
    assert len(app.get("download_button")) == 7

    app.sidebar.button(key="nav_分析记录与导出").click().run()
    assert not app.exception
    assert not any(widget.label == "插入图表" for widget in app.multiselect)
    assert not app.exception
    assert len(app.get("download_button")) == 2


def test_language_switch_keeps_fasta_analysis():
    app = AppTest.from_file(str(APP), default_timeout=25).run()
    app.sidebar.button(key="nav_FASTA 序列分析").click().run()
    app.checkbox(key="fasta_example").check().run()
    app.radio(key="sequence_type").set_value("nucleotide").run()
    app.selectbox(key="language").set_value("en").run()
    assert not app.exception
    assert app.metric[0].label == "Sequences"
    assert "Sequence ID" in app.dataframe[0].value
    assert '"title":{"text":"Sequence length"}' in app.get("plotly_chart")[0].proto.spec
    app.selectbox(key="language").set_value("zh").run()
    assert not app.exception
    assert app.metric[0].value == "6"
    assert "序列 ID" in app.dataframe[0].value
