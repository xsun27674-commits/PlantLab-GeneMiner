"""Produce downloads from the current analysis tables and parameters."""

import json
from io import BytesIO

import pandas as pd


def csv_bytes(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False).encode("utf-8-sig")


def json_bytes(record: dict) -> bytes:
    return json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")


def excel_bytes(filtered: pd.DataFrame, best: pd.DataFrame, record: dict) -> bytes:
    parameters = [
        {"类别": group, "参数": key, "值": value}
        for group, fields in record.items()
        for key, value in (fields.items() if isinstance(fields, dict) else [(group, fields)])
    ]
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for name, frame in (
            ("筛选结果", filtered),
            ("最佳命中", best),
            ("分析参数", pd.DataFrame(parameters, columns=["类别", "参数", "值"])),
        ):
            frame.to_excel(writer, sheet_name=name, index=False)
            sheet = writer.sheets[name]
            sheet.freeze_panes = "A2"
            sheet.auto_filter.ref = sheet.dimensions
            for row in sheet.iter_rows():
                for cell in row:
                    if isinstance(cell.value, str):
                        cell.data_type = "s"
    return buffer.getvalue()
