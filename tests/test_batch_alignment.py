import json
from io import BytesIO
from zipfile import ZipFile
from threading import Event

import pandas as pd
import pytest

from src.batch_alignment import BatchCancelled, make_plan, matrix_data, run_batch, similarity_order
from src.blast_utils import REQUIRED, suggest_mapping
from src.export_utils import csv_bytes, excel_bytes
from src.project_data import classify_table, record_labels, sequence_columns, table_metadata
from src.sequence_input import read_sequence_table
from src.workspace_state import restore, snapshot


def test_batch_self_and_distinct_sequences_and_scores():
    records = [("a", "ACGT"), ("b", "ACGA"), ("c", "TTTT")]
    clean, pairs, _ = make_plan(records, [0, 1, 2], include_self=True)
    results = run_batch(records, clean, pairs, "global", (2, -1, -3, -1))
    assert len(results) == 6
    assert results.iloc[0][["Alignment Length", "Identity (%)", "Matches", "Gaps", "Alignment Score"]].tolist() == [4, 100, 4, 0, 8]
    assert results.iloc[1][["Alignment Length", "Identity (%)", "Matches", "Gaps", "Alignment Score"]].tolist() == [4, 75, 3, 0, 5]
    assert results.iloc[2]["Identity (%)"] == 25
    _, matrix = matrix_data(results, pairs, [0, 1, 2], "Identity (%)", True)
    assert matrix == [[100, 75, 25], [75, 100, 0], [25, 0, 100]]
    assert classify_table(results.columns)[0] == "pairwise"
    assert not {"bitscore", "evalue"} & set(results.columns)


def test_query_mode_local_no_alignment_and_budget():
    records = [("a", "AAAA"), ("b", "CCCC"), ("c", "TAAAA")]
    clean, pairs, cells = make_plan(records, [0, 1, 2], query=0)
    assert pairs == [(0, 1), (0, 2)] and cells == 36
    filtered = run_batch(records, clean, pairs, "local", (2, -2, -3, -1))
    assert filtered["Identity (%)"].isna().tolist() == [True, False]
    assert filtered["Alignment Length"].tolist() == [0, 4]
    with pytest.raises(ValueError, match="计算量超限"):
        make_plan([("a", "A" * 8100), ("b", "C" * 8100)], [0, 1])


def test_all_63_records_and_symmetric_matrix_and_cancellation():
    from src.ncbi_dataset import parse_ncbi_zip

    archive = BytesIO()
    reports, fasta = [], []
    for gene in range(20):
        transcripts = []
        for isoform in range(4 if gene < 3 else 3):
            accession = f"XM_{900000000 + gene * 10 + isoform}.1"
            sequence = "ACGT" * (isoform + 1)
            fasta.append(f">{accession}:1-{len(sequence)}\n{sequence}\n")
            transcripts.append({"accessionVersion": accession})
        reports.append({"gene": {"geneId": str(90000 + gene), "symbol": f"SIM_{gene}",
                                 "taxname": "Arabidopsis thaliana", "transcripts": transcripts}})
    with ZipFile(archive, "w") as package:
        package.writestr("ncbi_dataset/data/cds.fna", "".join(fasta))
        package.writestr("ncbi_dataset/data/data_report.jsonl", "\n".join(map(json.dumps, reports)))
    table = parse_ncbi_zip(archive.getvalue())
    assert len(table) == 63 and table["Gene"].nunique() == 20 and table["Accession"].nunique() == 63
    records = list(table[["Sequence ID", "Sequence"]].itertuples(index=False, name=None))
    indices = list(range(len(records)))
    clean, pairs, cells = make_plan(records, indices)
    assert len(pairs) == len(set(pairs)) == 1953
    assert cells > 0 and all(first < second for first, second in pairs)
    cancel = Event()
    progress = []

    def stop_at_eight(count):
        progress.append(count)
        if count == 8:
            cancel.set()

    scores = (2, -1, -3, -1)
    with pytest.raises(BatchCancelled):
        run_batch(records, clean, pairs, "global", scores, stop_at_eight, cancel)
    assert progress == list(range(1, 9))
    results = run_batch(records, clean, pairs, "global", scores)
    order = similarity_order(results, pairs, indices)
    assert sorted(order) == indices
    _, matrix = matrix_data(results, pairs, order, "Identity (%)", True)
    frame = pd.DataFrame(matrix, index=order, columns=order)
    assert all(pd.isna(frame.iloc[i, i]) for i in indices)
    assert len(results) == len(pairs)
    for (first, second), identity in zip(pairs, results["Identity (%)"]):
        assert frame.loc[first, second] == frame.loc[second, first] == identity


def test_record_labels_use_verified_metadata_and_distinguish_duplicate_accessions():
    metadata = table_metadata(pd.DataFrame({
        "Gene Symbol": ["MLH1", "MLH1", "MLH1"],
        "Accession": ["NM_123.1", "NM_123.1", "NM_456.1"],
        "Transcript": ["", "", "T-A"],
        "Original Sequence ID": ["NM_123.1:1-50", "NM_123.1:4-60", "NM_456.1:1-40"],
    }))
    assert metadata[2] == ("MLH1", "NM_456.1", "T-A", "NM_456.1:1-40")
    project = {"key": ("f", "digest"), "records": [("edited", "ACC")] * 3,
               "metadata": [dict(zip(("gene", "accession", "transcript", "original"), row)) for row in metadata]}
    assert record_labels(project) == ["MLH1 · NM_123.1 · [1]", "MLH1 · NM_123.1 · [2]",
                                      "MLH1 · NM_456.1"]


def test_data_classification_export_and_project_roundtrip():
    cds = pd.DataFrame({"Sequence ID": ["x"], "Accession": ["XM_1.1"], "Length (bp)": [4], "Sequence": ["ACGT"]})
    assert classify_table(cds.columns) == ("sequence", [])
    assert sequence_columns(cds.columns) == (["Sequence ID"], ["Sequence"])
    columns = ["Query ID", "Subject ID", "Percent identity", "Alignment length", "Expect value", "Bit score"]
    assert classify_table(columns) == ("blast", [])
    assert set(suggest_mapping(columns)) == set(REQUIRED)
    assert classify_table(columns[:-1]) == ("incomplete_blast", ["bitscore"])
    hits = pd.DataFrame([["q", "s", "95", "100", "0", "200"]], columns=REQUIRED)
    for name, data in [("table.csv", csv_bytes(hits)), ("table.xlsx", excel_bytes(hits, hits, {}))]:
        reopened = read_sequence_table(name, data, True)
        assert classify_table(reopened.columns)[0] == "blast"
        pd.testing.assert_frame_equal(reopened, hits)
    project = {"key": ("test",), "records": [("q", "ACGT")], "type": "nucleotide"}
    assert restore(snapshot({"project_sequences": project}))["project_sequences"] == project


def test_grouping_and_resume_preserve_exact_coverage_and_rows():
    records = [("iso1", "GGGAAAA"), ("iso2", "AAAA"), ("unverified", "AAAA"), ("other", "AAAA")]
    groups = {0: "gene_A", 1: "gene_A", 3: "gene_B"}
    clean, pairs, _ = make_plan(records, range(4), groups=groups)
    assert pairs == [(0, 1)]
    scores = (2, -1, -3, -1)
    result = run_batch(records, clean, pairs, "local", scores)
    assert result.loc[0, "Query Coverage (%)"] == pytest.approx(4 / 7 * 100)
    assert result.loc[0, "Subject Coverage (%)"] == 100
    all_clean, all_pairs, _ = make_plan(records, range(4))
    rows = []
    run_batch(records, all_clean, all_pairs[:2], "local", scores, rows=rows)
    replay_done = []
    resumed = run_batch(records, all_clean, all_pairs, "local", scores, replay_done.append, rows=rows)
    assert replay_done == [3, 4, 5, 6]
    pd.testing.assert_frame_equal(resumed, run_batch(records, all_clean, all_pairs, "local", scores))


def test_candidate_filters_remain_project_scoped_and_blind_to_blast(monkeypatch):
    from src.batch_alignment_page import filter_candidates
    from src.project_data import current_candidates, invalidate_sequence_results
    import streamlit as st

    matches = pd.DataFrame({"Query Internal ID": ["a", "a", "b"], "Subject Internal ID": ["a", "b", "c"],
                            "Identity (%)": [100, 95, 80], "Gaps": [0, 2, 1]})
    filtered = filter_candidates(matches, "b", {"Identity (%)": 90, "Gaps": 2}, True, "Gaps")
    assert filtered.index.tolist() == [1]
    key = (("file", "digest"), "batch")
    state = {"project_sequences": {"key": key[0]}, "batch_alignment": {"key": key},
             "local_candidates_record": {"key": key, "results": filtered}, "blast_result": {"independent": True}}
    monkeypatch.setattr(st, "session_state", state)
    assert current_candidates()["results"].equals(filtered)
    state["project_sequences"] = {"key": ("different", "data")}
    assert current_candidates() is None
    invalidate_sequence_results()
    assert "local_candidates_record" not in state and "batch_alignment" not in state
    assert state["blast_result"] == {"independent": True}
