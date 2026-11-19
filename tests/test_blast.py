import json
from io import BytesIO

import pandas as pd
import pytest
from openpyxl import load_workbook

from src.blast_utils import (
    REQUIRED, Thresholds, best_hits, candidate_counts, filter_hits, normalize_hits,
    read_blast, suggest_mapping,
)
from src.export_utils import csv_bytes, excel_bytes, json_bytes


def hits_from(rows, columns=REQUIRED):
    return normalize_hits(pd.DataFrame(rows, columns=columns), {key: key for key in columns})


def test_standard_outfmt6_and_manual_mapping():
    raw = read_blast(b"Q\tS\t98.5\t100\t1\t0\t1\t100\t5\t104\t0\t200\n", "\t")
    assert normalize_hits(raw, suggest_mapping(raw)).iloc[0].tolist() == [
        "Q", "S", 98.5, 100, "0", 200.0,
    ]

    raw = read_blast(
        b'log,hit,query,id,score,span,cover\n2e-10,"S,2",Q,80,100,50,90\n',
        ",", "yes",
    )
    fields = dict(zip((*REQUIRED, "qcovhsp"), ("query", "hit", "id", "span", "log", "score", "cover")))
    assert normalize_hits(raw, fields).iloc[0].tolist() == ["Q", "S,2", 80.0, 50, "2e-10", 100.0, 90.0]


def test_evalue_exact_zero_and_extreme_exponents():
    hits = hits_from([
        ["Q", "zero", 98, 100, "0", 200],
        ["Q", "tiny", 98, 100, "1e-1000", 200],
        ["Q", "larger", 98, 100, "1e-999", 200],
    ])
    assert filter_hits(hits, Thresholds(evalue="0"))["sseqid"].tolist() == ["zero"]
    assert filter_hits(hits, Thresholds(evalue="1e-1000"))["sseqid"].tolist() == ["zero", "tiny"]
    with pytest.raises(ValueError, match="非负"):
        filter_hits(hits, Thresholds(evalue="NaN"))


def test_coverage_absent_or_blank():
    row = ["Q", "S", 95, 100, "0", 200]
    without = hits_from([row])
    assert len(filter_hits(without, Thresholds())) == 1
    assert "qcovs" not in without
    with pytest.raises(ValueError, match="不存在"):
        filter_hits(without, Thresholds(coverage_field="qcovs", coverage=0))
    with_coverage = hits_from([row + [""], row + [0], row + [95]], (*REQUIRED, "qcovs"))
    assert with_coverage["qcovs"].isna().tolist() == [True, False, False]
    assert filter_hits(with_coverage, Thresholds(coverage_field="qcovs", coverage=0)).index.tolist() == [1, 2]


def test_best_hits_tie_breaking_and_unique_candidates():
    hits = hits_from([
        ["A", "low_score", 100, 1000, "0", 99],
        ["A", "worse_evalue", 100, 1000, "1e-7", 100],
        ["A", "lower_identity", 90, 1000, "0", 100],
        ["A", "shorter", 95, 100, "0", 100],
        ["A", "zz", 95, 200, "0", 100],
        ["A", "aa", 95, 200, "0", 100],
        ["A", "aa", 95, 200, "0", 100],
        ["B", "only", 80, 50, "0", 30],
    ])
    assert best_hits(hits).index.tolist() == [5, 7]
    assert candidate_counts(hits, pd.Series(["A", "B", "C"]))["候选数量"].tolist() == [6, 1, 0]
    assert best_hits(hits.iloc[:0]).empty


def test_export_matches_filtered_results_and_parameters():
    hits = hits_from([["Q", "=1+1", 100, 100, "0", 200], ["Q", "excluded", 60, 100, "0", 100]])
    filtered = filter_hits(hits, Thresholds(identity=90))
    record = {"BLAST": {"筛选后命中数": 1}, "筛选阈值": {"identity": 90, "evalue": "0"}}
    csv = pd.read_csv(BytesIO(csv_bytes(filtered)), dtype={"evalue": str})
    assert csv["sseqid"].tolist() == ["=1+1"]
    assert csv["evalue"].tolist() == ["0"]
    book = load_workbook(BytesIO(excel_bytes(filtered, best_hits(filtered), record)))
    assert book.sheetnames == ["筛选结果", "最佳命中", "分析参数"]
    for sheet in ("筛选结果", "最佳命中"):
        assert book[sheet].max_row == 2
        assert book[sheet]["B2"].value == "=1+1"
        assert book[sheet]["B2"].data_type == "s"
    assert ("筛选阈值", "identity", 90) in list(book["分析参数"].values)
    assert json.loads(json_bytes(record)) == record
