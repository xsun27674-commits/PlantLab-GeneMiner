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
    assert not any("Word" in button.label for button in app.button)
    assert not any("Word" in item.proto.label for item in app.get("download_button"))

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
    assert not any("Word" in button.label for button in app.button)
    assert not any("Word" in item.proto.label for item in app.get("download_button"))


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
    assert app.button(key="home_local").label == "开始序列比较 →"
    assert app.button(key="home_blast").label == "开始 BLAST 分析 →"
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


def test_local_isoform_filter_is_opt_in_and_uses_filtered_plot_data():
    from src.batch_alignment import make_plan, run_batch

    genes = ("RCK", "RCK", "MLH3", "MLH3", "MLH1")
    records = [(f"SIM_{i}", "ACGT" * 20 + "A" * i) for i in range(len(genes))]
    project = {"key": ("fixture", "abcd"), "type": "nucleotide", "name": "fixture", "origin": "test",
               "records": records, "metadata": [
                   {"gene": gene, "gene_id": gene, "species": "Arabidopsis thaliana", "accession": f"SIM_{i}.1"}
                   for i, gene in enumerate(genes)]}
    scores = (2, -1, -3, -1)
    indices = tuple(range(len(records)))
    clean, pairs, _ = make_plan(records, indices)
    raw = run_batch(records, clean, pairs, "global", scores)
    batch = {"key": (project["key"], indices, None, "global", scores, False),
             "results": raw, "pairs": pairs, "time": "test"}
    app = AppTest.from_file(str(APP), default_timeout=25)
    app.session_state["project_sequences"] = project
    app.session_state["batch_alignment"] = batch
    app.session_state["page"] = "本地比对候选筛选"
    app.run()
    checkbox = "alignment_setting_candidates_exclude_isoforms"
    assert not app.checkbox(key=checkbox).value
    assert len(app.session_state["local_candidates_record"]["results"]) == 10
    app.checkbox(key=checkbox).check().run()
    filtered = app.session_state["local_candidates_record"]["results"]
    assert len(filtered) == 8
    assert not (filtered["Query Gene"] == filtered["Subject Gene"]).any()
    assert ((filtered["Query Gene"] == "MLH3") & (filtered["Subject Gene"] == "MLH1")).any()
    next(button for button in app.button if button.label == "下一步：可视化与导出 →").click().run()
    assert not app.exception
    fig = app.session_state["report_figures"]["local_candidate_identity"][1]
    assert len(fig.data[0].x) == 8
    app.sidebar.button(key="nav_本地比对候选筛选").click().run()
    app.checkbox(key=checkbox).uncheck().run()
    assert len(app.session_state["local_candidates_record"]["results"]) == 10
    assert app.session_state["batch_alignment"]["results"].equals(raw)


def test_blast_mode_switch_prunes_stale_selections_before_rendering():
    genes = [f"SIM_GENE_{i:02d}" for i in range(11)]
    accessions = [f"SIM_{i:03d}.1" for i in range(33)]
    project = {
        "key": ("fixture", "33-cds"), "name": "11 genes", "origin": "test", "type": "nucleotide",
        "records": [(name, "ATG" * (10 + i % 3)) for i, name in enumerate(accessions)],
        "metadata": [{"gene": genes[i // 3], "gene_id": str(i // 3 + 1),
                      "species": "Arabidopsis thaliana", "accession": name}
                     for i, name in enumerate(accessions)],
    }
    app = AppTest.from_file(str(APP), default_timeout=25)
    app.session_state["page"] = "BLAST 搜索"
    app.session_state["project_sequences"] = project
    # Mimic a snapshot saved before selectors switched to string IDs.
    app.session_state["local_blast_queries"] = [0, 2]
    app.session_state["local_blast_targets"] = [1, 5]
    app.run()
    queries, targets, scope = "local_blast_queries", "local_blast_targets", "local_blast_transcript_scope"
    assert len(app.multiselect(key=queries).options) == 33
    assert app.multiselect(key=queries).value == ["0", "2"]
    assert app.multiselect(key=targets).value == ["1", "5"]
    app.radio(key=scope).set_value("每个基因保留一条代表性转录本").run()
    assert not app.exception
    assert len(app.multiselect(key=queries).options) == len(app.multiselect(key=targets).options) == 11
    assert app.multiselect(key=queries).value == ["2"]
    assert app.multiselect(key=targets).value == ["5"]
    assert app.multiselect(key=queries).options[0] == "SIM_GENE_00 · SIM_002.1"
    app.radio(key=scope).set_value("保留全部转录本").run()
    assert not app.exception
    assert len(app.multiselect(key=queries).options) == 33
    assert app.multiselect(key=queries).value == ["2"]
    assert app.multiselect(key=targets).value == ["5"]
    assert len(app.session_state["project_sequences"]["records"]) == 33
