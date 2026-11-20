"""Fixtures follow the CDS header shown in the NCBI TAGC 2024 workshop."""

from io import BytesIO
import json
from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd
import pytest

from src.export_utils import csv_bytes
from src.fasta_utils import analyze_fasta
from src.ncbi_dataset import COLUMNS, UNKNOWN, parse_ncbi_zip, sequence_quality
from src.sequence_input import read_sequence_table, table_to_fasta, write_sequence_xlsx


def package(fasta, reports=None, extra=()):
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("ncbi_dataset/data/cds.fna", fasta)
        if reports is not None:
            archive.writestr("ncbi_dataset/data/data_report.jsonl",
                             "\n".join(map(json.dumps, reports)))
        for name, content in extra:
            archive.writestr(name, content)
    return output.getvalue()


def source_rows(sizes):
    fasta, reports, expected = [], [], []
    for gene, transcripts in enumerate(sizes, 1):
        metadata = []
        for isoform in range(1, transcripts + 1):
            accession = f"XM_{gene:04d}{isoform:02d}.1"
            seq_id = f"{accession}:1-9"
            sequence = "ATGCCCTGA" if isoform % 2 else "ATGAAGTAA"
            metadata.append({"accessionVersion": accession})
            fasta.append(f">{seq_id} GENE{gene} [organism=Arabidopsis thaliana] [GeneID={100+gene}] [region=cds]\n{sequence}\n")
            expected.append([seq_id, f"GENE{gene}", "Arabidopsis thaliana", accession, 9, sequence])
        reports.append({"geneId": str(100 + gene), "symbol": f"GENE{gene}",
                        "taxname": "Arabidopsis thaliana", "transcripts": metadata})
    return "".join(fasta), reports, expected


@pytest.mark.parametrize("sizes", [(1,), (3,), (2, 3)])
def test_ncbi_package_retains_every_cds_and_gene_identity(sizes):
    fasta, reports, expected = source_rows(sizes)
    result = parse_ncbi_zip(package(fasta, reports))
    assert result[COLUMNS].values.tolist() == expected
    assert result["_gene_id"].nunique() == len(sizes)
    assert result["_transcript"].nunique() == sum(sizes)
    assert not sequence_quality(result)["Duplicate ID"].any()
    pd.testing.assert_frame_equal(
        analyze_fasta(table_to_fasta(result, "Sequence ID", "Sequence"), "nucleotide"),
        analyze_fasta(fasta.encode(), "nucleotide").assign(描述=lambda frame: frame["序列 ID"]),
    )


def test_missing_metadata_ambiguous_protein_and_qc():
    fixture = ">custom [protein_id=NP_123.1]\nA?\n>custom\n"
    report = {"gene_id": 111, "symbol": "GENE", "taxname": "Example",
              "transcripts": [{"accession_version": f"NM_{i}.1",
                               "protein": {"accession_version": "NP_123.1"}} for i in range(2)]}
    frame = parse_ncbi_zip(package(fixture, [{"gene": report}]))
    assert (frame[["Gene", "Species", "Accession"]] == UNKNOWN).all().all()
    result = sequence_quality(frame)
    assert result["Duplicate ID"].tolist() == [True, True]
    assert result["Empty"].tolist() == [False, True]
    assert result["Invalid characters"].tolist() == ["?", ""]


@pytest.mark.parametrize("content", [b"broken", package(">id\nATG\n", extra=[("../escape", "unsafe")]),
                                     package(">id\nATG\n", extra=[("huge", "A" * 2_000_000)])])
def test_invalid_or_unsafe_zip(content):
    with pytest.raises(ValueError):
        parse_ncbi_zip(content)


def test_csv_excel_round_trip_including_long_cds():
    fasta, reports, _ = source_rows((2,))
    full = parse_ncbi_zip(package(fasta, reports))[COLUMNS].copy()
    full.loc[1, ["Sequence", "Length (bp)"]] = ["ATG" * 13000, 39000]
    for filename, data in [("result.csv", csv_bytes(full)), ("result.xlsx", write_sequence_xlsx(full))]:
        restored = read_sequence_table(filename, data)
        assert restored.astype(str).values.tolist() == full.astype(str).values.tolist()
        result = analyze_fasta(table_to_fasta(restored, "Sequence ID", "Sequence"), "nucleotide")
        assert result["序列长度"].tolist() == [9, 39000]


def test_no_report_preserves_confirmed_header_evidence_only():
    frame = parse_ncbi_zip(package(
        ">XM_001360232.4:1406-2743 LOC4803562 [organism=Drosophila pseudoobscura] [GeneID=4803562] [region=cds]\nATG\n"
        ">anonymous\nATG\n"
    ))
    assert frame.iloc[0][COLUMNS].tolist() == ["XM_001360232.4:1406-2743", "LOC4803562",
                                              "Drosophila pseudoobscura", "XM_001360232.4", 3, "ATG"]
    assert frame.iloc[1][["Gene", "Species", "Accession"]].tolist() == [UNKNOWN] * 3


def test_joins_only_exact_transcript_version_from_report():
    report = {"geneId": "123", "symbol": "Verified", "taxname": "Arabidopsis thaliana",
              "transcripts": [{"accessionVersion": "NM_123.2"}]}
    frame = parse_ncbi_zip(package(">NM_123.2:1-3\nATG\n>NM_123.1:1-3\nATG\n", [report]))
    assert frame["Gene"].tolist() == ["Verified", UNKNOWN]
    assert frame["Species"].tolist() == ["Arabidopsis thaliana", UNKNOWN]
    assert frame["_gene_id"].tolist() == ["123", ""]


def test_select_annotation_is_linked_by_gene_and_exact_accession():
    fasta, reports, _ = source_rows((2,))
    matching = {**reports[0], "transcripts": [
        {"accessionVersion": "XM_000101.1", "selectCategory": "REFSEQ_SELECT"},
        {"accessionVersion": "XM_000102.2", "selectCategory": "MANE_SELECT"},
    ]}
    result = parse_ncbi_zip(package(fasta, reports, [
        ("ncbi_dataset/data/product_report.jsonl", json.dumps(matching)),
    ]))
    assert result["_select_category"].tolist() == ["REFSEQ_SELECT", ""]
