"""Read BLAST tables, validate mapped fields, and compute candidate results."""

import csv
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import numpy as np
import pandas as pd

OUTFMT6 = (
    "qseqid", "sseqid", "pident", "length", "mismatch", "gapopen",
    "qstart", "qend", "sstart", "send", "evalue", "bitscore",
)
REQUIRED = ("qseqid", "sseqid", "pident", "length", "evalue", "bitscore")
COVERAGE = ("qcovs", "qcovhsp")
ALIASES = {
    "qseqid": {"qseqid", "query", "queryid", "queryaccver"},
    "sseqid": {"sseqid", "subject", "subjectid", "subjectaccver"},
    "pident": {"pident", "identity", "percentageidentity", "percentidentity"},
    "length": {"length", "alignmentlength", "alnlength"},
    "evalue": {"evalue", "expect", "expectvalue"},
    "bitscore": {"bitscore", "bitscores"},
    "qcovs": {"qcovs", "querycoverage", "querycoveragepersubject"},
    "qcovhsp": {"qcovhsp", "querycoverageperhsp"},
}


def suggest_mapping(columns) -> dict[str, str]:
    by_name = {}
    for column in columns:
        key = re.sub(r"[^a-z0-9]", "", column.lower())
        by_name.setdefault(key, []).append(column)
    mapping = {}
    for field, aliases in ALIASES.items():
        exact = by_name.get(field, [])
        matches = [column for key in aliases for column in by_name.get(key, [])]
        choices = exact or matches
        if len(choices) == 1:
            mapping[field] = choices[0]
    return mapping


def read_blast(data: bytes, delimiter: str, header: str = "auto") -> pd.DataFrame:
    try:
        raw = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("BLAST 表格须使用 UTF-8 编码。") from exc
    lines = [line for line in raw.splitlines(keepends=True)
             if line.strip() and not line.lstrip().startswith("#")]
    if not lines:
        raise ValueError("BLAST 文件没有可读取的表格数据。")
    try:
        rows = list(csv.reader(lines, delimiter=delimiter, strict=True))
    except csv.Error as exc:
        raise ValueError(f"BLAST 表格格式有误：{exc}") from exc
    width = len(rows[0])
    if width < len(REQUIRED):
        raise ValueError("BLAST 表格至少需要 6 列，请检查分隔符。")
    for number, row in enumerate(rows, 1):
        if len(row) != width:
            raise ValueError(f"表格第 {number} 行有 {len(row)} 列，预期 {width} 列。")

    has_header = header == "yes" or (
        header == "auto" and len(suggest_mapping(rows[0])) >= 2
    )
    if has_header:
        columns = [name.strip() for name in rows.pop(0)]
        if "" in columns or len(set(columns)) != len(columns):
            raise ValueError("表头包含空列名或重复列名。")
    elif width == len(OUTFMT6):
        columns = OUTFMT6
    else:
        columns = [f"第 {number} 列" for number in range(1, width + 1)]
    if not rows:
        raise ValueError("BLAST 表格只有表头，没有命中记录。")
    return pd.DataFrame(rows, columns=columns)


def parse_evalue(value: str) -> Decimal:
    try:
        number = Decimal(value.strip())
    except InvalidOperation as exc:
        raise ValueError("请输入有效的非负 E-value，支持科学计数法。") from exc
    if not number.is_finite() or number < 0:
        raise ValueError("请输入有效的非负 E-value，支持科学计数法。")
    return number


def normalize_hits(raw: pd.DataFrame, mapping: dict[str, str]) -> pd.DataFrame:
    fields = [field for field in (*REQUIRED, *COVERAGE) if field in mapping]
    missing = set(REQUIRED) - set(fields)
    if missing:
        raise ValueError("请映射必需字段：" + "、".join(sorted(missing)))
    columns = [mapping[field] for field in fields]
    if len(set(columns)) != len(columns) or not set(columns) <= set(raw.columns):
        raise ValueError("请为各字段选择不同且有效的来源列。")
    hits = raw.loc[:, columns].copy()
    hits.columns = fields
    for field in fields:
        hits[field] = hits[field].astype("string").str.strip().fillna("")

    def reject(field, bad):
        positions = np.flatnonzero(bad)
        if positions.size:
            raise ValueError(f"第 {positions[0] + 1} 条命中的 {field} 缺失或超出有效范围。")

    for field in ("qseqid", "sseqid"):
        reject(field, hits[field].eq(""))
    for field in ("pident", "length", "bitscore", *COVERAGE):
        if field not in hits:
            continue
        blank = hits[field].eq("")
        values = pd.to_numeric(hits[field], errors="coerce").astype(float)
        bad = ~np.isfinite(values) | (values < 0)
        if field in ("pident", *COVERAGE):
            bad |= values > 100
        if field == "length":
            bad |= (values < 1) | (values % 1 != 0) | (values >= 2**63)
        reject(field, bad & ~blank if field in COVERAGE else bad)
        hits[field] = values.astype("int64") if field == "length" else values

    for position, value in enumerate(hits["evalue"], 1):
        try:
            parse_evalue(value)
        except ValueError as exc:
            raise ValueError(f"第 {position} 条命中的 evalue 无效。") from exc
    return hits


@dataclass(frozen=True)
class Thresholds:
    identity: float = 0
    evalue: str = "1e-5"
    length: int = 1
    coverage_field: str | None = None
    coverage: float | None = None


def threshold_checks(hits: pd.DataFrame, thresholds: Thresholds) -> pd.DataFrame:
    maximum = parse_evalue(thresholds.evalue)
    checks = pd.DataFrame({
        "pident 低于阈值": hits["pident"] >= thresholds.identity,
        "E-value 高于阈值": hits["evalue"].map(lambda value: parse_evalue(value) <= maximum),
        "比对长度低于阈值": hits["length"] >= thresholds.length,
    }, index=hits.index)
    if thresholds.coverage_field is not None and thresholds.coverage is not None:
        if thresholds.coverage_field not in COVERAGE or thresholds.coverage_field not in hits:
            raise ValueError("所选 Query coverage 字段不存在。")
        coverage = hits[thresholds.coverage_field]
        checks["覆盖度低于阈值"] = coverage.isna() | (coverage >= thresholds.coverage)
        checks["覆盖度缺失"] = coverage.notna()
    return checks


def filter_hits(hits: pd.DataFrame, thresholds: Thresholds) -> pd.DataFrame:
    return hits.loc[threshold_checks(hits, thresholds).all(axis=1)].copy()


def rejection_reasons(hits: pd.DataFrame, thresholds: Thresholds) -> pd.DataFrame:
    checks = threshold_checks(hits, thresholds)
    rejected = checks.loc[~checks.all(axis=1)]
    reasons = ["；".join(name for name, passed in zip(checks, row) if not passed)
               for row in rejected.itertuples(index=False, name=None)]
    return hits.loc[rejected.index, ["qseqid", "sseqid"]].assign(排除原因=reasons)


def best_hits(hits: pd.DataFrame) -> pd.DataFrame:
    ranked = hits.assign(
        _evalue=hits["evalue"].map(parse_evalue),
        _order=np.arange(len(hits)),
    ).sort_values(
        ["qseqid", "bitscore", "_evalue", "pident", "length", "sseqid", "_order"],
        ascending=[True, False, True, False, False, True, True],
    )
    return ranked.drop_duplicates("qseqid").loc[:, hits.columns]


def candidate_counts(hits: pd.DataFrame, queries: pd.Series) -> pd.DataFrame:
    counts = hits.groupby("qseqid")["sseqid"].nunique()
    counts = counts.reindex(pd.Index(queries.unique(), name="qseqid"), fill_value=0)
    return counts.rename("候选数量").reset_index()
