import random
import shutil

import pytest

from src.blast_utils import OUTFMT6, Thresholds, filter_hits
from src.local_blast import run_local_blast, valid_records
from src.workspace_state import restore, snapshot


def test_local_blast_real_tools_and_empty_result(tmp_path, monkeypatch):
    if not all(shutil.which(name) for name in ("blastn", "makeblastdb")):
        pytest.skip("NCBI BLAST+ is required for the executable integration test")
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    rng = random.Random(7301)
    sequence = "".join(rng.choices("ACGT", k=180))
    unrelated = "".join(rng.choices("ACGT", k=180))
    project = {"key": ("fixture", "digest"), "type": "nucleotide",
               "records": [("same-id", sequence), ("same-id", sequence), ("other", unrelated)],
               "metadata": [{"gene": "SIM_A", "accession": "SIM.1"}, {"gene": "SIM_A", "accession": "SIM.2"}]}
    records = valid_records(project)
    result = run_local_blast(project, records, [0], [0, 1, 2])
    hits = result["hits"]
    assert tuple(hits.columns[:12]) == OUTFMT6
    assert result["version"].startswith("blastn:")
    assert hits["qseqid"].nunique() == 1 and hits["sseqid"].nunique() >= 2
    full = hits.loc[hits["length"].eq(180)]
    assert full["pident"].eq(100).all() and full["bitscore"].gt(0).all()
    assert set(full["Subject Accession"]) == {"SIM.1", "SIM.2"}
    assert full["Subject Internal ID"].nunique() == 2
    assert result["identical"].loc[full.index, "identical"].all()
    assert filter_hits(hits, Thresholds(min_bitscore=float(full["bitscore"].max()) + 1)).empty
    assert restore(snapshot({"local_blast_run": result}))["local_blast_run"]["key"] == result["key"]

    no_hits = run_local_blast(project, records, [0], [2])
    assert no_hits["hits"].empty
    assert filter_hits(no_hits["hits"], Thresholds()).empty
    assert list(tmp_path.iterdir()) == []


def test_local_blast_rejects_invalid_and_over_budget_inputs():
    project = {"key": ("fixture", "digest"), "type": "nucleotide",
               "records": [("bad", "AG!"), ("empty", ""), ("usable", "aUG"), ("large", "A" * 50_001)]}
    records = valid_records(project)
    assert list(records) == [2, 3] and records[2] == "ATG"
    with pytest.raises(ValueError, match="请选择有效"):
        run_local_blast(project, records, [0], [2])
    with pytest.raises(ValueError, match="资源上限"):
        run_local_blast(project, records, [2], [3])
