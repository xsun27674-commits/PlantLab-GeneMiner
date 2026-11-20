"""Run NCBI BLAST+ on the nucleotide records in the active project."""

import os
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock

import pandas as pd

from src.blast_utils import COVERAGE, OUTFMT6, normalize_hits, read_blast
from src.fasta_utils import ALPHABETS
from src.project_data import record_info, record_labels

FIELDS = (*OUTFMT6, *COVERAGE)
MAX_SEQUENCES = 128
MAX_BASES = 500_000
MAX_SEQUENCE_BASES = 50_000
MAX_OUTPUT = 20 * 1024 * 1024
SEARCH_EVALUE = "10"
_WORKER = Lock()


def executable_paths():
    paths = tuple(shutil.which(program) for program in ("makeblastdb", "blastn"))
    if not all(paths):
        raise ValueError("未找到 makeblastdb 或 blastn。请安装 NCBI BLAST+ 并确认它们在 PATH 中。")
    return paths


def valid_records(project):
    if not project or project["type"] != "nucleotide":
        return {}
    records = {}
    for index, (_, sequence) in enumerate(project["records"]):
        dna = "".join(sequence.split()).upper()
        if dna and not set(dna) - ALPHABETS["nucleotide"]:
            records[index] = dna.replace("U", "T")
    return records


def _command(executable, arguments, folder, timeout):
    limiter = shutil.which("prlimit")
    command = [executable, *arguments]
    if limiter:
        command = [limiter, "--as=805306368", "--", *command]
    try:
        output = subprocess.run(command, cwd=folder, check=True, capture_output=True, text=True,
                                timeout=timeout, env={**os.environ, "LC_ALL": "C"}).stdout
    except subprocess.TimeoutExpired as exc:
        raise ValueError(f"{Path(executable).name} 超过 {timeout} 秒。请缩小查询或目标范围。") from exc
    except subprocess.CalledProcessError as exc:
        name = Path(executable).name
        raise ValueError(f"{name} 运行失败（退出码 {exc.returncode}）。请检查 BLAST+ 安装，或缩小序列范围。") from exc
    except OSError as exc:
        raise ValueError(f"无法启动 {Path(executable).name}。请检查 BLAST+ 安装和运行权限。") from exc
    return output


def run_local_blast(project, records, queries, targets):
    queries, targets = tuple(dict.fromkeys(queries)), tuple(dict.fromkeys(targets))
    if not queries or not targets or not set((*queries, *targets)) <= records.keys():
        raise ValueError("请选择有效的查询序列和目标序列。")
    for selected in (queries, targets):
        sizes = [len(records[index]) for index in selected]
        if len(sizes) > MAX_SEQUENCES or sum(sizes) > MAX_BASES or max(sizes) > MAX_SEQUENCE_BASES:
            raise ValueError("本地 BLAST 超过资源上限。查询和目标各限 128 条、总长各限 500,000 bp，单条限 50,000 bp。")
    makeblastdb, blastn = executable_paths()
    token = {index: f"plantlab_{index + 1:06d}" for index in set((*queries, *targets))}

    def write_fasta(path, selected):
        with path.open("w", encoding="ascii") as stream:
            for index in selected:
                stream.write(f">{token[index]}\n{records[index]}\n")

    if not _WORKER.acquire(blocking=False):
        raise ValueError("当前有一个本地 BLAST 任务正在运行，请稍后重试。")
    try:
        with TemporaryDirectory(prefix="plantlab-blast-") as tmp:
            folder = Path(tmp)
            write_fasta(folder / "target.fa", targets)
            write_fasta(folder / "query.fa", queries)
            version = _command(blastn, ["-version"], folder, 5).splitlines()[0]
            _command(makeblastdb, ["-in", "target.fa", "-dbtype", "nucl", "-parse_seqids",
                                   "-blastdb_version", "4", "-out", "project_db"], folder, 15)
            _command(blastn, ["-task", "blastn", "-query", "query.fa", "-db", "project_db",
                             "-num_threads", "1", "-evalue", SEARCH_EVALUE, "-max_target_seqs", str(len(targets)),
                             "-max_hsps", "5", "-outfmt", "6 " + " ".join(FIELDS), "-out", "hits.tsv"], folder, 45)
            output = folder / "hits.tsv"
            if output.stat().st_size > MAX_OUTPUT:
                raise ValueError("本地 BLAST 输出超过 20 MiB，请缩小搜索范围。")
            data = output.read_bytes()
    except OSError as exc:
        raise ValueError("无法创建或读取本地 BLAST 临时文件。请检查临时目录权限和空间。") from exc
    finally:
        _WORKER.release()

    raw = read_blast(("\t".join(FIELDS) + "\n").encode() + data, "\t", "yes") if data.strip() else pd.DataFrame(columns=FIELDS)
    mapping = {column: column for column in FIELDS}
    normalized = normalize_hits(raw, mapping)
    hits = raw.assign(**normalized.to_dict("series"))
    for column in set(OUTFMT6) - set(normalized):
        hits[column] = pd.to_numeric(hits[column], errors="raise").astype("int64")

    by_token = {name: index for index, name in token.items()}
    labels = record_labels(project)
    queries_for_hits, targets_for_hits = [], []
    for column, side, indices in (("qseqid", "Query", queries_for_hits), ("sseqid", "Subject", targets_for_hits)):
        # Some BLAST+ builds prefix local IDs with lcl|.
        indices.extend(by_token[identifier.removeprefix("lcl|")] for identifier in hits[column])
        information = [record_info(project, index) for index in indices]
        hits[f"{side} Name"] = [labels[index] for index in indices]
        for key, label in (("original", "Sequence ID"), ("gene", "Gene"), ("accession", "Accession"), ("id", "Internal ID")):
            hits[f"{side} {label}"] = [item[key] for item in information]
    groups = {}
    sequence_class = {index: groups.setdefault(records[index], len(groups)) for index in token}
    identical = [sequence_class[q] == sequence_class[s] for q, s in zip(queries_for_hits, targets_for_hits)]
    query_ids = {**token, **dict(zip(queries_for_hits, hits["qseqid"]))}
    return {"key": (project["key"], queries, targets), "hits": hits,
            "identical": pd.Series(identical, index=hits.index, dtype=bool).to_frame("identical"),
            "queries": [query_ids[index] for index in queries],
            "query_names": {query_ids[index]: labels[index] for index in queries},
            "version": version, "query_count": len(queries), "target_count": len(targets)}
