import pandas as pd

from src.blast_utils import candidate_counts
from src.transcripts import isoform_hit_mask, representative_selection


def identity(gene, gene_id, species, accession):
    return dict(zip(("Gene", "Gene ID", "Species", "Accession"), (gene, gene_id, species, accession)))


def test_isoform_filter_is_per_gene_and_species_and_reversible():
    a = identity(" MLH1", "001", "Arabidopsis  thaliana", "NM_001.1")
    b = identity("mlh1", "", "arabidopsis thaliana", "NM_002.1")
    c = identity("MLH3", "003", "Arabidopsis thaliana", "NM_003.1")
    d = identity("MLH3", "003", "Arabidopsis thaliana", "NM_004.1")
    pms1 = identity("PMS1", "004", "Arabidopsis thaliana", "NM_005.1")
    cross = identity("MLH1", "001", "Arabidopsis lyrata", "XM_006.1")
    unknown = identity("MLH1", "", "", "XM_007.1")
    other_id = identity("MLH1", "008", "Arabidopsis thaliana", "XM_008.1")
    version = {**a, "Accession": "NM_001.2"}

    def table(pairs):
        return pd.DataFrame([{
            "qseqid": left["Accession"], "sseqid": right["Accession"],
            **{f"{side} {k}": v for side, item in (("Query", left), ("Subject", right)) for k, v in item.items()}
        } for left, right in pairs])

    hits = table([(a,b), (a,b), (c,d), (a,c), (a,c), (a,pms1), (a,cross), (a,unknown), (a,version)])
    original = hits.copy(deep=True)
    assert isoform_hit_mask(hits).tolist() == [True, True, True, False, False, False, False, False, False]
    retained = hits.loc[~isoform_hit_mask(hits)]
    counts = candidate_counts(retained, hits["qseqid"])
    assert len(retained) == 6 and counts.loc[counts.qseqid.eq("NM_001.1"), "候选数量"].iloc[0] == 5
    assert not isoform_hit_mask(table([(a, other_id), (a, b)])).any()
    pd.testing.assert_frame_equal(hits, original)


def test_representatives_keep_longest_valid_and_never_merge_unknown_or_other_species():
    records = [("A", "ATG"), ("B", "ATGATG"), ("invalid", "?" * 12), ("C", "ATG"), ("D", "ATG")]
    project = {"key": ("fixture", "digest"), "records": records,
               "metadata": [{"gene": "MLH1", "gene_id": "01", "species": species}
                            for species in ("Arabidopsis thaliana", "Arabidopsis thaliana",
                                            "Arabidopsis thaliana", "Arabidopsis lyrata", "")]}
    choices = representative_selection(project, list(range(5)))
    assert {i for i, (keep, _) in choices.items() if keep} == {1, 3, 4}
    assert choices[4][1] == "基因身份未核实，保留"
    assert choices[2][1] == "无有效核酸序列"
    assert project["records"] == records


def test_verified_select_annotation_wins_over_longer_cds():
    project = {"key": ("fixture", "digest"), "records": [("short", "ATG"), ("long", "ATG" * 50)],
               "metadata": [{"species": "Arabidopsis thaliana", "gene_id": "01", "select_category": "REFSEQ_SELECT"},
                            {"species": "Arabidopsis thaliana", "gene_id": "01"}]}
    assert representative_selection(project, [0, 1]) == {
        0: (True, "REFSEQ_SELECT"), 1: (False, "同基因已保留 NCBI Select 标注序列"),
    }
