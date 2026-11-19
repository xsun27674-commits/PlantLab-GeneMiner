from io import BytesIO

import pandas as pd
import pytest

from src.batch_alignment import make_plan, matrix_data, run_batch
from src.blast_utils import REQUIRED, suggest_mapping
from src.export_utils import csv_bytes, excel_bytes
from src.project_data import classify_table, sequence_columns
from src.sequence_input import read_sequence_table
from src.workspace_state import restore, snapshot


def test_batch_self_and_distinct_sequences_and_scores():
    records = [("a", "ACGT"), ("b", "ACGA"), ("c", "TTTT")]
    clean, pairs, _ = make_plan(records, [0, 1, 2])
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
        make_plan([("a", "A" * 5100), ("b", "C" * 5100)], [0, 1])


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
