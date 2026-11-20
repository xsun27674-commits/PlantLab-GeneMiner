"""Bounded, in-memory NCBI Datasets CDS import with evidence-based metadata joins."""

import json
import re
import stat
from zlib import error as CompressionError
from collections import defaultdict
from io import BytesIO, StringIO
from pathlib import PurePosixPath
from zipfile import BadZipFile, ZipFile

import pandas as pd
from Bio import SeqIO

from src.fasta_utils import ALPHABETS

MAX_ARCHIVE = 10 * 1024 * 1024
MAX_TOTAL = 64 * 1024 * 1024
MAX_CDS = 8 * 1024 * 1024
MAX_MEMBERS = 512
MAX_RECORDS = 5000
UNKNOWN = "待核实"
COLUMNS = ["Sequence ID", "Gene", "Species", "Accession", "Length (bp)", "Sequence"]
INTERNAL = ["_gene_id", "_transcript", "_original_sequence_id"]
REFSEQ_RNA = r"(?:NM|NR|XM|XR)_[0-9]+(?:\.[0-9]+)?"
REFSEQ_PROTEIN = r"(?:NP|XP|YP|WP|AP|ZP)_[0-9]+(?:\.[0-9]+)?"
TAG = re.compile(r"\[([^=\]]+)=([^\]]*)\]")


def safe_members(archive):
    members = archive.infolist()
    if len(members) > MAX_MEMBERS or sum(item.file_size for item in members) > MAX_TOTAL:
        raise ValueError("ZIP 文件数量或解压总大小超出上限。")
    by_name = {}
    for item in members:
        name = item.filename
        path = PurePosixPath(name)
        if (path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name
                or "\x00" in item.orig_filename or name in by_name
                or stat.S_ISLNK(item.external_attr >> 16) or item.flag_bits & 1):
            raise ValueError("ZIP 包含不安全路径、重复文件、符号链接或加密成员。")
        if item.file_size > max(1024 * 1024, item.compress_size * 300):
            raise ValueError("ZIP 成员的压缩比异常。")
        by_name[name] = item
    return by_name


def metadata_text(value):
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        return ""
    text = str(value).strip()
    return text if len(text) <= 1000 else ""


def field(record, *keys):
    return next((value for key in keys if (value := metadata_text(record.get(key)))), "")


def read_index(archive, report):
    genes, by_rna, by_protein = defaultdict(set), defaultdict(set), defaultdict(set)
    if report is None:
        return genes, by_rna, by_protein
    with archive.open(report) as rows:
        for raw in rows:
            if not raw.strip():
                continue
            try:
                row = json.loads(raw)
            except (UnicodeError, ValueError, RecursionError):
                continue
            if not isinstance(row, dict):
                continue
            gene = row.get("gene", row)
            if not isinstance(gene, dict):
                continue
            gene_id = field(gene, "geneId", "gene_id")
            profile = (gene_id if gene_id.isdecimal() else "", field(gene, "symbol"),
                       field(gene, "taxname", "scientificName", "scientific_name"))
            if profile[0]:
                genes[profile[0]].add(profile)
            transcripts = gene.get("transcripts", [])
            if not isinstance(transcripts, list):
                continue
            for transcript in transcripts:
                if not isinstance(transcript, dict):
                    continue
                accession = field(transcript, "accessionVersion", "accession_version")
                if not accession:
                    continue
                evidence = (*profile, accession)
                by_rna[accession].add(evidence)
                protein = transcript.get("protein")
                if isinstance(protein, dict):
                    protein_id = field(protein, "accessionVersion", "accession_version")
                    if protein_id:
                        by_protein[protein_id].add(evidence)
    return genes, by_rna, by_protein


def match_record(record, index):
    genes, by_rna, by_protein = index
    tags = {key.strip().lower(): metadata_text(value) for key, value in TAG.findall(record.description)}
    gene_id = tags.get("geneid", "")
    if not gene_id.isdecimal():
        gene_id = ""
        match = re.search(r"(?:^|[,; ])GeneID:(\d+)(?:$|[,; ])", tags.get("db_xref", ""))
        if match:
            gene_id = match[1]
    symbol = tags.get("symbol") or tags.get("gene", "")
    species = tags.get("organism") or tags.get("species", "")
    # NCBI's gene-package CDS header explicitly places one symbol before its tagged fields.
    if not symbol and tags.get("region") == "cds" and gene_id and species:
        prefix = record.description.split("[", 1)[0].split()
        if len(prefix) == 2 and re.fullmatch(rf"{REFSEQ_RNA}(?::[0-9,–-]+)?", prefix[0]):
            symbol = prefix[1]
    explicit_rna = tags.get("transcript_id") or tags.get("rna_id") or tags.get("transcript_accession")
    token_rna = re.findall(rf"(?<![A-Za-z0-9]){REFSEQ_RNA}(?![A-Za-z0-9.])", record.id)
    accession = explicit_rna or (token_rna[0] if len(set(token_rna)) == 1 and token_rna else "")
    if not accession and record.id in by_rna:
        accession = record.id
    candidates = by_rna.get(accession, set())
    if not accession:
        protein = tags.get("protein_id", "")
        if not protein:
            matches = re.findall(rf"(?<![A-Za-z0-9]){REFSEQ_PROTEIN}(?![A-Za-z0-9.])", record.id)
            protein = matches[0] if len(set(matches)) == 1 and matches else ""
        candidates = by_protein.get(protein, set())
    matching = {row for row in candidates if not gene_id or row[0] == gene_id}
    if len(matching) == 1:
        g, s, organism, rna = next(iter(matching))
        gene_id, accession = gene_id or g, accession or rna
        symbol, species = reconcile(symbol, s), reconcile(species, organism)
    elif candidates and not matching:
        # Conflicting reference links must not provide a transcript assignment.
        accession = ""
    profiles = genes.get(gene_id, set())
    if len(profiles) == 1:
        _, gene_symbol, organism = next(iter(profiles))
        symbol, species = reconcile(symbol, gene_symbol), reconcile(species, organism)
    return gene_id, symbol, species, accession


def reconcile(left, right):
    return UNKNOWN if left and right and left != right else left or right


def parse_ncbi_zip(data):
    if len(data) > MAX_ARCHIVE:
        raise ValueError("NCBI ZIP 文件超过 10 MB。")
    try:
        with ZipFile(BytesIO(data)) as archive:
            members = safe_members(archive)
            root = PurePosixPath("ncbi_dataset/data")
            cds_members = [item for name, item in members.items()
                           if PurePosixPath(name).name == "cds.fna"
                           and root in PurePosixPath(name).parents]
            if not cds_members:
                raise ValueError("ZIP 中没有找到 ncbi_dataset/data/cds.fna。")
            if sum(item.file_size for item in cds_members) > MAX_CDS:
                raise ValueError("包内 CDS FASTA 解压后超过 8 MB。")
            report = members.get("ncbi_dataset/data/data_report.jsonl")
            index = read_index(archive, report)
            rows = []
            for member in cds_members:
                fasta = archive.read(member).decode("utf-8-sig")
                for record in SeqIO.parse(StringIO(fasta), "fasta"):
                    gene, name, species, transcript = match_record(record, index)
                    sequence = str(record.seq)
                    rows.append((record.id, name or UNKNOWN, species or UNKNOWN, transcript or UNKNOWN,
                                 len(sequence), sequence, gene, transcript, record.id))
                    if len(rows) > MAX_RECORDS:
                        raise ValueError("NCBI ZIP 最多支持 5,000 条 CDS。")
    except (BadZipFile, OSError, EOFError, RuntimeError, NotImplementedError, UnicodeError, CompressionError) as exc:
        raise ValueError("NCBI ZIP 损坏、无法解压或 CDS FASTA 编码无效。") from exc
    if not rows:
        raise ValueError("包内 CDS FASTA 为空或未包含有效 FASTA 记录。")
    return pd.DataFrame(rows, columns=COLUMNS + INTERNAL)


def sequence_quality(frame):
    ids = frame["Sequence ID"].fillna("").astype(str).str.strip()
    seq = frame["Sequence"].fillna("").astype(str)
    return pd.DataFrame({
        "Sequence ID": ids, "Empty": seq.str.strip().eq(""),
        "Duplicate ID": ids.duplicated(keep=False),
        "Invalid characters": seq.map(
            lambda value: "".join(sorted({c for c in value.upper() if not c.isspace()} - ALPHABETS["nucleotide"]))
        ),
    })
