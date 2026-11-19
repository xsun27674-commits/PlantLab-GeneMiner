from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / "app.py"


def test_example_workflow_and_navigation():
    app = AppTest.from_file(str(APP), default_timeout=25).run()
    assert not app.exception

    page = app.sidebar.radio(key="page")
    page.set_value("FASTA 序列分析").run()
    app.checkbox(key="fasta_example").check().run()
    app.radio(key="sequence_type").set_value("nucleotide").run()
    assert not app.exception
    assert len(app.dataframe[0].value) == 6

    page.set_value("BLAST 候选筛选").run()
    app.checkbox(key="blast_example").check().run()
    app.text_input(key="evalue").set_value("0").run()
    assert not app.exception
    assert [metric.value for metric in app.metric][:2] == ["60", "1"]

    page.set_value("结果可视化").run()
    assert not app.exception
    assert len(app.get("plotly_chart")) == 5
    page.set_value("分析记录与导出").run()
    app.text_input(key="research_项目名称").set_value("教学验证").run()
    assert not app.exception
    assert len(app.get("download_button")) == 3

    page.set_value("BLAST 候选筛选").run()
    assert not app.exception
    assert app.text_input(key="evalue").value == "0"
    assert app.metric[1].value == "1"

    page.set_value("分析记录与导出").run()
    assert app.text_input(key="research_项目名称").value == "教学验证"
