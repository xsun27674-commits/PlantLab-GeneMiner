"""Local pairwise sequence alignment with bounded resource usage."""

from dataclasses import dataclass

from Bio.Align import PairwiseAligner

from src.fasta_utils import ALPHABETS

MAX_CELLS = 4_000_000
MAX_SEQUENCE_LENGTH = 10_000


@dataclass(frozen=True)
class AlignmentResult:
    score: float
    length: int
    matches: int
    mismatches: int
    gaps: int
    identity: float
    text: str


def align_sequences(first, second, sequence_type, mode, match, mismatch, gap_open, gap_extend):
    alphabet = ALPHABETS.get(sequence_type)
    if alphabet is None or mode not in ("global", "local"):
        raise ValueError("请选择有效的序列类型与比对模式。")
    sequences = ["".join(item.split()).upper() for item in (first, second)]
    for index, sequence in enumerate(sequences, 1):
        if not sequence:
            raise ValueError(f"第 {index} 条序列为空。")
        invalid = sorted(set(sequence) - alphabet)
        if invalid:
            raise ValueError(f"第 {index} 条序列包含非法字符：{''.join(invalid)}")
    if max(map(len, sequences)) > MAX_SEQUENCE_LENGTH or len(sequences[0]) * len(sequences[1]) > MAX_CELLS:
        raise ValueError("序列长度超过成对比对上限。每条最多 10,000 字符，两条长度之积最多 400 万。")
    if not (0 < match <= 100 and -100 <= mismatch <= 0 and -100 <= gap_open <= gap_extend <= 0):
        raise ValueError("评分须满足：匹配为正，错配和 gap 为非正，gap 开启罚分不弱于延伸罚分。")
    aligner = PairwiseAligner(mode=mode, match_score=match, mismatch_score=mismatch,
                             open_gap_score=gap_open, extend_gap_score=gap_extend)
    alignment = next(iter(aligner.align(*sequences)), None)
    if alignment is None:
        return None
    counts = alignment.counts()
    text = str(alignment)
    return AlignmentResult(alignment.score, alignment.length, counts.identities, counts.mismatches,
                           counts.gaps, 100 * counts.identities / alignment.length, text)
