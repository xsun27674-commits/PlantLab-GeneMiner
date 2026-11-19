import pytest

from src.fasta_utils import analyze_fasta


def test_nucleotide_statistics():
    rows = analyze_fasta(b">a first\nACGUNSW\n>b\nNNN\n", "nucleotide")
    assert list(rows["序列 ID"]) == ["a", "b"]
    assert list(rows["序列长度"]) == [7, 3]
    assert rows.loc[0, "GC (%)"] == pytest.approx(50)
    assert rows["GC (%)"].isna().tolist() == [False, True]


def test_protein_has_no_gc_and_reports_invalid_characters():
    rows = analyze_fasta(b">p\nabjuoxz*?-\n>empty\n", "protein")
    assert "GC (%)" not in rows
    assert rows["非法字符"].tolist() == ["-?", ""]
    assert rows["空序列"].tolist() == [False, True]


def test_duplicate_marks_all_instances():
    rows = analyze_fasta(b">a first\nA\n>b\nA\n>a second\nA", "nucleotide")
    assert rows["重复 ID"].tolist() == [True, False, True]


@pytest.mark.parametrize(("data", "message"), [
    (b"", "为空"),
    (b"\n  ", "为空"),
    (b"ACTG", "FASTA 标题"),
    (b">\nACGT", "缺少序列 ID"),
    (b"\xff", "UTF-8"),
])
def test_bad_fasta(data, message):
    with pytest.raises(ValueError, match=message):
        analyze_fasta(data, "nucleotide")
