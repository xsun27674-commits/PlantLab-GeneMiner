"""Versioned JSON snapshots of scientific session state; never deserialize executable objects."""

import base64
import json
import math
from dataclasses import asdict
from io import StringIO

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio

from src.alignment import AlignmentResult
from src.blast_utils import Thresholds
from src.chart_editor import ChartStyle, validate_style

RECORDS = {"project_sequences", "batch_alignment", "local_candidates_record", "fasta_result", "blast_result", "pairwise_result", "pairwise_record", "report_figures",
           "fasta_source", "blast_source", "last_report", "alignment_fasta", "sequence_grid_base", "sequence_grid_source", "sequence_ncbi_applied",
           "sequence_ncbi_table", "sequence_ncbi_selection", "sequence_ncbi_revision"}
SCALARS = {"result_view", "fasta_example", "blast_example", "sequence_type", "identity", "evalue",
           "alignment_length", "coverage_cutoff", "blast_preset", "sequence_input_mode"}
PREFIXES = ("delimiter_", "header_", "mapping_", "coverage_", "research_", "chart_mode_",
            "chart_style_", "chart_defaults_", "report_setting_", "alignment_setting_")
TYPES = {"ChartStyle": ChartStyle, "Thresholds": Thresholds, "AlignmentResult": AlignmentResult}


def keeps(key):
    return key in RECORDS or key in SCALARS or key.startswith(PREFIXES)


def encode(value):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, bytes):
        return ["bytes", base64.b64encode(value).decode()]
    if isinstance(value, pd.DataFrame):
        return ["frame", value.to_json(orient="split", force_ascii=False, double_precision=15)]
    if isinstance(value, go.Figure):
        return ["figure", value.to_json()]
    if type(value).__name__ in TYPES:
        return [type(value).__name__, encode(asdict(value))]
    if isinstance(value, (tuple, list)):
        return ["tuple" if isinstance(value, tuple) else "list", [encode(item) for item in value]]
    if isinstance(value, dict):
        return ["dict", {key: encode(item) for key, item in sorted(value.items())}]
    raise ValueError("项目包含无法保存的数据类型。")


def decode(value):
    if not isinstance(value, list):
        return value
    kind, data = value
    if kind == "bytes":
        return base64.b64decode(data, validate=True)
    if kind == "frame":
        return pd.read_json(StringIO(data), orient="split", dtype=False, convert_dates=False)
    if kind == "figure":
        return pio.from_json(data)
    if kind == "dict":
        return {key: decode(item) for key, item in data.items()}
    if kind in ("tuple", "list"):
        return (tuple if kind == "tuple" else list)(map(decode, data))
    if kind in TYPES:
        result = TYPES[kind](**decode(data))
        return validate_style(result) if kind == "ChartStyle" else result
    raise ValueError("项目数据格式不受支持。")


def snapshot(session):
    return json.dumps({"version": 1, "analysis": encode({
        key: session[key] for key in session if keeps(key)})}, ensure_ascii=False, separators=(",", ":"))


def restore(payload):
    document = json.loads(payload)
    if document["version"] != 1:
        raise ValueError("此项目使用不受支持的版本。")
    return {key: value for key, value in decode(document["analysis"]).items() if keeps(key)}


def clear(session):
    job = session.pop("_batch_job", None)
    if job:
        job.cancel.set()
    session.pop("_batch_history", None)
    session.pop("_batch_outcome", None)
    session.pop("_batch_checkpoint", None)
    for key in list(session):
        if key.startswith(("_matrix_click_", "matrix_")):
            session.pop(key, None)
    for key in list(session):
        if keeps(key) or key.startswith(("style_value_", "image_", "open_", "workspace_", "_timed_", "_prepared_", "ncbi_",
                                             "x_range_", "y_range_", "category_limit_", "category_count_", "fasta_upload_")) or key in {
            "fasta_upload", "blast_upload", "fasta_upload_revision", "alignment_upload", "project_name", "project_species", "project_target",
        }:
            session.pop(key, None)
