from io import BytesIO

import pandas as pd
import pytest

from src.fasta_utils import analyze_fasta
from src.sequence_input import read_sequence_table, table_to_fasta


@pytest.mark.parametrize("extension", ["csv", "xlsx"])
def test_sequence_file_uses_same_qc_as_fasta(extension):
    source = pd.DataFrame({"Sequence ID": ["001", "001", "NA"], "Sequence": ["aCgT", "N?", ""]})
    if extension == "csv":
        data = source.to_csv(index=False).encode()
    else:
        buffer = BytesIO()
        source.to_excel(buffer, index=False, engine="openpyxl")
        data = buffer.getvalue()
    frame = read_sequence_table(f"sequence.{extension}", data)
    fasta = table_to_fasta(frame, "Sequence ID", "Sequence")
    assert b"aCgT" in fasta
    expected = analyze_fasta(b">001\naCgT\n>001\nN?\n>NA\n", "nucleotide")
    pd.testing.assert_frame_equal(analyze_fasta(fasta, "nucleotide"), expected)


def test_sequence_table_rejects_blast_and_fasta_header_in_cell():
    with pytest.raises(ValueError, match="BLAST"):
        read_sequence_table("blast.csv", b"qseqid,sseqid,evalue\nq,s,0\n")
    frame = pd.DataFrame({"id": ["q"], "seq": ["ACGT\n>injected"]})
    with pytest.raises(ValueError, match="第 1 行"):
        table_to_fasta(frame, "id", "seq")
