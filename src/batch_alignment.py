"""Bounded local PairwiseAligner batches. Results intentionally lack BLAST statistics."""

from itertools import combinations, combinations_with_replacement
from multiprocessing import get_context
from threading import Event, Lock, Semaphore, Thread
from time import monotonic, sleep

import pandas as pd
from Bio.Align import PairwiseAligner

from src.fasta_utils import ALPHABETS

MAX_PAIR_CELLS = 64_000_000
MAX_BATCH_CELLS = 12_000_000_000
MAX_TASKS = 12_000
_WORKER = Semaphore(1)
RESULT_COLUMNS = ("Query ID", "Subject ID", "Alignment Length", "Identity (%)", "Matches",
                  "Mismatches", "Gaps", "Alignment Score", "Algorithm", "Query Coverage (%)", "Subject Coverage (%)")


def make_plan(records, indices, query=None, *, include_self=False, groups=None):
    indices = list(dict.fromkeys(indices))
    if len(indices) < 2:
        raise ValueError("请选择至少两条记录。")
    count = len(indices)
    if groups is not None:
        grouped = {}
        for index in indices:
            if groups.get(index):
                grouped.setdefault(groups[index], []).append(index)
        tasks = sum(len(group) * (len(group) - 1) // 2 for group in grouped.values())
    else:
        tasks = (count * (count + (1 if include_self else -1))) // 2 if query is None else count - 1
    if not tasks:
        raise ValueError("当前没有可比较的同组序列。")
    if tasks > MAX_TASKS:
        raise ValueError(f"任务数超过 {MAX_TASKS:,} 对。请指定查询序列或缩小记录范围。")
    if query is not None and query not in indices:
        raise ValueError("查询记录必须包含在选定记录中。")
    clean = {}
    for index in indices:
        identifier, sequence = records[index]
        sequence = "".join(sequence.split()).upper()
        if not sequence or set(sequence) - ALPHABETS["nucleotide"]:
            raise ValueError(f"请在 FASTA 质检中修正空序列或非法核酸字符：{identifier}")
        clean[index] = sequence
    if groups is not None:
        pairs = [pair for group in grouped.values() for pair in combinations(group, 2)]
    elif query is None:
        pair_builder = combinations_with_replacement if include_self else combinations
        pairs = list(pair_builder(indices, 2))
    else:
        pairs = [(query, other) for other in indices if other != query]
    cells = [len(clean[a]) * len(clean[b]) for a, b in pairs]
    if max(cells) > MAX_PAIR_CELLS or sum(cells) > MAX_BATCH_CELLS:
        reason = "单对过长" if max(cells) > MAX_PAIR_CELLS else "整批工作量过大"
        raise ValueError(f"计算量超限（{reason}，最大单对 {max(cells):,}，整批 {sum(cells):,} 单元）。"
                         "请减少记录数量、选择单查询或使用更短序列。")
    return clean, pairs, sum(cells)


def local_aligner(mode, scores):
    match, mismatch, opening, extension = scores
    if not (0 < match <= 100 and -100 <= mismatch <= 0 and -100 <= opening <= extension <= 0):
        raise ValueError("评分须满足：匹配为正，错配和 gap 为非正，gap 开启罚分不弱于延伸罚分。")
    return PairwiseAligner(mode=mode, match_score=match, mismatch_score=mismatch,
                           open_gap_score=opening, extend_gap_score=extension)


class BatchCancelled(Exception):
    pass


def run_batch(records, clean, pairs, mode, scores, progress=None, cancel=None, *, rows=None):
    aligner = local_aligner(mode, scores)
    rows = [] if rows is None else rows
    offset = len(rows)
    for index, (first, second) in enumerate(pairs[offset:], offset + 1):
        if cancel and cancel.is_set():
            raise BatchCancelled
        alignment = next(iter(aligner.align(clean[first], clean[second])), None)
        if alignment is None:
            length, identity, matches, mismatches, gaps, score = 0, None, 0, 0, 0, 0.0
        else:
            counts = alignment.counts()
            length, matches, mismatches, gaps, score = (
                alignment.length, counts.identities, counts.mismatches, counts.gaps, alignment.score)
            identity = 100 * matches / length
        coverage = (0.0, 0.0) if alignment is None else tuple(
            100 * int(end - start) / len(clean[record])
            for (start, end), record in zip(alignment.coordinates[:, [0, -1]], (first, second))
        )
        rows.append((records[first][0], records[second][0], length, identity,
                     matches, mismatches, gaps, score, f"{mode} / {aligner.algorithm}", *coverage))
        del alignment
        if progress:
            progress(index)
        if index % 8 == 0:
            sleep(0)
    if cancel and cancel.is_set():
        raise BatchCancelled
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


def _process_batch(output, cancel, records, clean, pairs, mode, scores, rows):
    def progress(count):
        if count % 8 == 0 or count == len(pairs):
            output.send(("progress", count))

    try:
        run_batch(records, clean, pairs, mode, scores, progress, cancel, rows=rows)
        output.send(("done", rows))
    except BatchCancelled:
        output.send(("cancelled", rows))
    except (ValueError, MemoryError, OverflowError, RuntimeError):
        output.send(("failed", None))
    finally:
        output.close()


class AlignmentJob:
    """One cancellable worker per session, with an app-wide compute slot."""

    def __init__(self, key, records, clean, pairs, mode, scores, *, checkpoint=()):
        local_aligner(mode, scores)
        self.key = key
        self.total = len(pairs)
        self.rows = list(checkpoint)
        self.completed = len(self.rows)
        self.started = monotonic()
        self.finished = None
        self.state = "queued"
        self.results = None
        self.pairs = pairs
        self.cancel = Event()
        self.lock = Lock()
        Thread(target=self._work, args=(records, clean, mode, scores), daemon=True).start()

    def _progress(self, count):
        with self.lock:
            self.completed = count

    def _work(self, records, clean, mode, scores):
        acquired = False
        state, result = "cancelled", None
        try:
            while not self.cancel.is_set() and not acquired:
                acquired = _WORKER.acquire(timeout=0.25)
            if acquired and not self.cancel.is_set():
                context = get_context("spawn")
                incoming, outgoing = context.Pipe(duplex=False)
                cancel = context.Event()
                process = context.Process(target=_process_batch, args=(
                    outgoing, cancel, records, clean, self.pairs, mode, scores, self.rows,
                ), daemon=True)
                with incoming, outgoing:
                    process.start()
                    outgoing.close()
                    with self.lock:
                        self.state = "running"
                    try:
                        state = "failed"
                        while True:
                            if self.cancel.is_set():
                                cancel.set()
                            if incoming.poll(0.15):
                                message, value = incoming.recv()
                                if message == "progress":
                                    self._progress(value)
                                    continue
                                state = message
                                if message in ("done", "cancelled"):
                                    self.rows = value
                                    self._progress(len(value))
                                break
                            if not process.is_alive():
                                break
                    finally:
                        process.join(timeout=2)
                        if process.is_alive():
                            process.terminate()
                            process.join()
                        process.close()
                if state == "done":
                    result = pd.DataFrame(self.rows, columns=RESULT_COLUMNS)
        except (EOFError, OSError, ValueError, MemoryError, OverflowError, RuntimeError):
            state = "failed"
        finally:
            with self.lock:
                if self.cancel.is_set() and state == "done":
                    state, result = "cancelled", None
                self.state, self.results, self.finished = state, result, monotonic()
            if acquired:
                _WORKER.release()

    def status(self):
        with self.lock:
            return self.state, self.completed, (self.finished or monotonic()) - self.started, self.results


def similarity_order(results, pairs, indices):
    """Average linkage of observed identity distances, not a phylogenetic tree."""
    complete = {(a, b): value for (a, b), value in zip(pairs, results["Identity (%)"])
                if a != b and pd.notna(value)}
    if len(complete) != len(indices) * (len(indices) - 1) // 2:
        raise ValueError("聚类需要完整的两两一致性结果。")
    clusters = {idx: [idx] for idx in indices}
    distances = {tuple(sorted((a, b))): 100 - value for (a, b), value in complete.items()}
    parent = max(indices) + 1
    while len(clusters) > 1:
        first, second = min(distances, key=lambda pair: (distances[pair], pair))
        left, right = clusters.pop(first), clusters.pop(second)
        for other in clusters:
            a = distances.pop(tuple(sorted((first, other))))
            b = distances.pop(tuple(sorted((second, other))))
            distances[other, parent] = (a * len(left) + b * len(right)) / (len(left) + len(right))
        distances.pop((first, second))
        clusters[parent] = left + right
        parent += 1
    return next(iter(clusters.values()))
