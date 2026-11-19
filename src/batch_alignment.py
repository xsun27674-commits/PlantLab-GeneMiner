"""Bounded local PairwiseAligner batches. Results intentionally lack BLAST statistics."""

from itertools import combinations_with_replacement

import pandas as pd
from Bio.Align import PairwiseAligner

from src.fasta_utils import ALPHABETS

MAX_RECORDS = 32
MAX_PAIR_CELLS = 25_000_000
MAX_BATCH_CELLS = 1_200_000_000
RESULT_COLUMNS = ("Query ID", "Subject ID", "Alignment Length", "Identity (%)", "Matches",
                  "Mismatches", "Gaps", "Alignment Score", "Algorithm")


def make_plan(records, indices, query=None):
    indices = list(dict.fromkeys(indices))
    if not 2 <= len(indices) <= MAX_RECORDS:
        raise ValueError("请选择 2–32 条记录。")
    if query is not None and query not in indices:
        raise ValueError("查询记录必须包含在选定记录中。")
    clean = {}
    for index in indices:
        identifier, sequence = records[index]
        sequence = "".join(sequence.split()).upper()
        if not sequence or set(sequence) - ALPHABETS["nucleotide"]:
            raise ValueError(f"请在 FASTA 质检中修正空序列或非法核酸字符：{identifier}")
        clean[index] = sequence
    if query is None:
        pairs = list(combinations_with_replacement(indices, 2))
    else:
        pairs = [(query, other) for other in indices if other != query]
    cells = [len(clean[a]) * len(clean[b]) for a, b in pairs]
    if max(cells) > MAX_PAIR_CELLS or sum(cells) > MAX_BATCH_CELLS:
        raise ValueError("计算量超限。请减少记录数量或使用更短序列。")
    return clean, pairs, sum(cells)


def local_aligner(mode, scores):
    match, mismatch, opening, extension = scores
    if not (0 < match <= 100 and -100 <= mismatch <= 0 and -100 <= opening <= extension <= 0):
        raise ValueError("评分须满足：匹配为正，错配和 gap 为非正，gap 开启罚分不弱于延伸罚分。")
    return PairwiseAligner(mode=mode, match_score=match, mismatch_score=mismatch,
                           open_gap_score=opening, extend_gap_score=extension)


def run_batch(records, clean, pairs, mode, scores, progress=None):
    aligner = local_aligner(mode, scores)
    rows = []
    for index, (first, second) in enumerate(pairs, 1):
        alignment = next(iter(aligner.align(clean[first], clean[second])), None)
        if alignment is None:
            length, identity, matches, mismatches, gaps, score = 0, None, 0, 0, 0, 0.0
        else:
            counts = alignment.counts()
            length, matches, mismatches, gaps, score = (
                alignment.length, counts.identities, counts.mismatches, counts.gaps, alignment.score)
            identity = 100 * matches / length
        rows.append((records[first][0], records[second][0], length, identity,
                     matches, mismatches, gaps, score, f"{mode} / {aligner.algorithm}"))
        del alignment
        if progress and (index == len(pairs) or index % max(1, len(pairs) // 30) == 0):
            progress(index / len(pairs))
    return pd.DataFrame(rows, columns=RESULT_COLUMNS)


def matrix_data(results, pairs, indices, field, symmetric, query=None):
    row_ids = indices if query is None else [query]
    rows = {index: position for position, index in enumerate(row_ids)}
    columns = {index: position for position, index in enumerate(indices)}
    matrix = [[None for _ in indices] for _ in row_ids]
    for (first, second), value in zip(pairs, results[field]):
        if pd.notna(value):
            matrix[rows[first]][columns[second]] = float(value)
            if symmetric:
                matrix[rows[second]][columns[first]] = float(value)
    return row_ids, matrix
