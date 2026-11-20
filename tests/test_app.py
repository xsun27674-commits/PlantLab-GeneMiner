from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / "app.py"


def test_example_workflow_and_navigation():
    app = AppTest.from_file(str(APP), default_timeout=25).run()
    assert not app.exception

    app.sidebar.button(key="nav_数据导入与管理").click().run()
    assert not app.exception
    app.checkbox(key="fasta_example").check().run()
    app.radio(key="sequence_type").set_value("nucleotide").run()
    app.button(key="workflow_next_FASTA 序列分析").click().run()
    assert not app.exception
    assert len(app.dataframe[0].value) == 6

    app.sidebar.button(key="nav_BLAST 候选筛选").click().run()
    assert not app.exception
    app.radio(key="local_blast_source_mode").set_value("外部 BLAST 命中表").run()
    app.checkbox(key="blast_example").check().run()
    app.text_input(key="evalue").set_value("0").run()
    assert not app.exception
    assert [metric.value for metric in app.metric][:2] == ["60", "1"]

    app.sidebar.button(key="nav_结果可视化").click().run()
    assert not app.exception
    assert len([frame for frame in app.get("iframe") if "Plotly.newPlot" in frame.proto.srcdoc]) == 3
    app.sidebar.button(key="nav_结果可视化").click().run()
    app.radio(key="result_section").set_value("分析记录与导出").run()
    app.text_input(key="research_项目名称").set_value("教学验证").run()
    assert not app.exception
    assert len(app.get("download_button")) == 3
    next(button for button in app.button if button.label == "准备 Word 报告").click().run()
    assert len(app.get("download_button")) == 4

    app.sidebar.button(key="nav_BLAST 候选筛选").click().run()
    assert not app.exception
    assert app.text_input(key="evalue").value == "0"
    assert app.metric[1].value == "1"

    app.sidebar.button(key="nav_结果可视化").click().run()
    app.radio(key="result_section").set_value("分析记录与导出").run()
    assert app.text_input(key="research_项目名称").value == "教学验证"


def test_lightweight_preview_keeps_interactive_export(monkeypatch):
    monkeypatch.setenv("GENEMINER_LIGHTWEIGHT_PREVIEW", "1")
    app = AppTest.from_file(str(APP), default_timeout=25).run()
    app.sidebar.button(key="nav_数据导入与管理").click().run()
    app.checkbox(key="fasta_example").check().run()
    app.radio(key="sequence_type").set_value("nucleotide").run()
    app.button(key="workflow_next_FASTA 序列分析").click().run()
    assert not app.exception
    assert len([frame for frame in app.get("iframe") if "Plotly.newPlot" in frame.proto.srcdoc]) == 2
    assert not any(button.label == "生成静态图" for button in app.button)
    assert len(app.get("download_button")) == 5

    app.sidebar.button(key="nav_结果可视化").click().run()
    app.radio(key="result_section").set_value("分析记录与导出").run()
    assert not app.exception
    assert not any(widget.label == "插入图表" for widget in app.multiselect)
    assert not app.exception
    assert len(app.get("download_button")) == 1
    next(button for button in app.button if button.label == "准备 Word 报告").click().run()
    assert len(app.get("download_button")) == 2


def test_language_switch_keeps_fasta_analysis():
    app = AppTest.from_file(str(APP), default_timeout=25).run()
    app.sidebar.button(key="nav_数据导入与管理").click().run()
    app.checkbox(key="fasta_example").check().run()
    app.radio(key="sequence_type").set_value("nucleotide").run()
    app.button(key="workflow_next_FASTA 序列分析").click().run()
    app.selectbox(key="language").set_value("en").run()
    assert not app.exception
    assert app.metric[0].label == "Sequences"
    assert "Sequence ID" in app.dataframe[0].value
    assert '"title":{"text":"Sequence length"}' in app.get("iframe")[0].proto.srcdoc
    app.selectbox(key="language").set_value("zh").run()
    assert not app.exception
    assert app.metric[0].value == "6"
    assert "序列 ID" in app.dataframe[0].value


def test_home_import_routes_share_sequences_and_show_missing_blast_tools(monkeypatch):
    import src.pages as pages

    def unavailable():
        raise ValueError("BLAST+ unavailable")

    monkeypatch.setattr(pages, "executable_paths", unavailable)
    app = AppTest.from_file(str(APP), default_timeout=25).run()
    assert app.button(key="home_local").label == "开始本地分析"
    assert app.button(key="home_blast").label == "开始 BLAST 分析"
    assert not any(button.label in ("开始分析", "开始使用 →") for button in app.button)
    app.button(key="home_blast").click().run()
    assert app.title[0].value == "数据导入与管理"
    app.checkbox(key="fasta_example").check().run()
    app.radio(key="sequence_type").set_value("nucleotide").run()
    app.button(key="workflow_next_BLAST 搜索").click().run()
    assert app.title[0].value == "BLAST 搜索"
    assert any(warning.value == "BLAST+ unavailable" for warning in app.warning)
    assert next(button for button in app.button if button.label == "使用当前序列运行 BLAST").disabled
    assert "batch_alignment" not in app.session_state
    project_key = app.session_state["project_sequences"]["key"]

    app.sidebar.button(key="nav_首页").click().run()
    app.button(key="home_local").click().run()
    assert app.title[0].value == "FASTA 序列统计"
    assert app.metric[0].value == "6"
    assert app.session_state["project_sequences"]["key"] == project_key
    assert not any(".zip" in uploader.proto.type for uploader in app.get("file_uploader"))


def test_clear_project_data_removes_current_results_and_keeps_project_identity(monkeypatch):
    import streamlit as st
    from src.project_data import clear_sequence_project

    state = {"workspace_id": "current", "project_name": "saved project",
             "project_sequences": {"name": "test"}, "blast_result": {"origin": "external"},
             "blast_source": ("hits.tsv", b"result", "external"), "pairwise_result": ("key", "value"),
             "_timed_batch_plan": "cached", "report_figures": {"chart": "figure"},
             "fasta_source": ("sample.fasta", b"sequence", "source")}
    monkeypatch.setattr(st, "session_state", state)
    clear_sequence_project()
    assert state["workspace_id"] == "current"
    assert state["project_name"] == "saved project"
    assert not {"project_sequences", "blast_result", "pairwise_result", "blast_source",
                "fasta_source", "_timed_batch_plan", "report_figures"} & state.keys()
