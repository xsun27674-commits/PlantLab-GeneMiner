"""FASTA validation and per-record statistics."""

from io import StringIO

import pandas as pd
from Bio import SeqIO
from Bio.SeqUtils import gc_fraction

ALPHABETS = {
    "nucleotide": frozenset("ACGTURYSWKMBDHVN"),
    "protein": frozenset("ACDEFGHIKLMNPQRSTVWYBJOUXZ*"),
}


def analyze_fasta(data: bytes, sequence_type: str) -> pd.DataFrame:
    if sequence_type not in ALPHABETS:
        raise ValueError("请选择核酸或蛋白质序列类型。")
    try:
        raw = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("FASTA 文件须使用 UTF-8 编码。") from exc
    if not raw.strip():
        raise ValueError("FASTA 文件为空。")

    seen_header = False
    for number, line in enumerate(raw.splitlines(), 1):
        if not line.strip():
            continue
        if line.startswith(">"):
            if not line[1:].strip():
                raise ValueError(f"第 {number} 行缺少序列 ID。")
            seen_header = True
        elif not seen_header:
            raise ValueError(f"第 {number} 行应为以 > 开头的 FASTA 标题。")

    rows = []
    for record in SeqIO.parse(StringIO(raw.lstrip("\r\n \t")), "fasta"):
        seq = str(record.seq).upper()
        invalid = sorted(set(seq) - ALPHABETS[sequence_type])
        row = {
            "序列 ID": record.id,
            "描述": record.description,
            "序列长度": len(seq),
            "非法字符": "".join(invalid),
            "空序列": not seq,
        }
        if sequence_type == "nucleotide":
            row["GC (%)"] = (
                100 * gc_fraction(seq.replace("U", "T"), ambiguous="remove")
                if not invalid and set(seq) & set("ACGTUSW")
                else None
            )
        rows.append(row)

    if not rows:
        raise ValueError("文件中未找到 FASTA 序列。")
    frame = pd.DataFrame(rows)
    frame["重复 ID"] = frame["序列 ID"].duplicated(keep=False)
    return frame
