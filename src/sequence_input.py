"""Read bounded sequence tables and turn mapped rows into standard FASTA."""

from io import BytesIO
from zipfile import BadZipFile, ZipFile

import pandas as pd


MAX_BYTES = 10 * 1024 * 1024
MAX_ROWS = 5000
MAX_COLUMNS = 128


def read_sequence_table(name, data):
    if len(data) > MAX_BYTES:
        raise ValueError("序列表超过 10 MB。")
    try:
        if name.lower().endswith(".xlsx"):
            with ZipFile(BytesIO(data)) as book:
                if sum(entry.file_size for entry in book.infolist()) > 48 * 1024 * 1024:
                    raise ValueError("XLSX 解压后超过 48 MB。")
            with pd.ExcelFile(BytesIO(data), engine="openpyxl") as workbook:
                frame = pd.read_excel(workbook, dtype=str, keep_default_na=False, nrows=MAX_ROWS + 1)
                frame = restore_excel_sequences(workbook, frame)
        else:
            frame = pd.read_csv(BytesIO(data), dtype=str, keep_default_na=False,
                                encoding="utf-8-sig", nrows=MAX_ROWS + 1)
    except (BadZipFile, TypeError, OSError, ValueError, KeyError) as exc:
        raise ValueError("无法读取序列表。请检查 CSV 编码或 XLSX 文件是否有效。") from exc
    if len(frame) > MAX_ROWS or len(frame.columns) > MAX_COLUMNS:
        raise ValueError("序列表最多支持 5,000 行与 128 列。")
    if len(frame.columns) < 2:
        raise ValueError("序列表至少需要两列：序列编号与序列内容。")
    if {"qseqid", "sseqid", "evalue"} <= {str(column).strip().lower() for column in frame.columns}:
        raise ValueError("这是 BLAST 命中表，请在 BLAST 候选筛选页面导入。")
    return frame


def table_to_fasta(frame, id_column, sequence_column, *, ignore_blank_rows=False):
    if id_column == sequence_column:
        raise ValueError("序列编号与序列内容必须映射到不同列。")
    if len(frame) > MAX_ROWS:
        raise ValueError("序列表最多支持 5,000 行。")
    lines = []
    used = 0
    for row, (identifier, sequence) in enumerate(
        frame[[id_column, sequence_column]].fillna("").itertuples(index=False, name=None), 1
    ):
        identifier = str(identifier).strip()
        sequence = str(sequence)
        if ignore_blank_rows and not identifier and not sequence.strip():
            continue
        if not identifier or any(char.isspace() for char in identifier) or ">" in identifier:
            raise ValueError(f"第 {row} 行的序列编号为空，或包含空白字符或 >。")
        if any(line.startswith(">") for line in sequence.splitlines()):
            raise ValueError(f"第 {row} 行序列含 FASTA 标题，请只粘贴序列内容。")
        lines.extend((f">{identifier}", sequence))
        used += len(identifier.encode("utf-8")) + len(sequence.encode("utf-8")) + 3
        if used > MAX_BYTES:
            raise ValueError("序列表超过 10 MB。")
    if not lines:
        raise ValueError("序列表为空。")
    return ("\n".join(lines) + "\n").encode("utf-8")


EXCEL_CELL_LIMIT = 32767
CHUNK_SIZE = 30000
CHUNK_SHEET = "PlantLab Sequence Parts"
CHUNK_MARKER = "@PlantLab:parts:"


def write_sequence_xlsx(frame):
    """Keep ordinary sequences in one cell and store Excel-overflow rows losslessly."""
    export = frame.copy()
    chunks = []
    for row, sequence in enumerate(frame["Sequence"].astype(str), 1):
        if len(sequence.encode("utf-16-le")) // 2 > EXCEL_CELL_LIMIT:
            export.iloc[row - 1, export.columns.get_loc("Sequence")] = f"{CHUNK_MARKER}{row}"
            chunks.extend((row, part + 1, sequence[offset:offset + CHUNK_SIZE // 2])
                          for part, offset in enumerate(range(0, len(sequence), CHUNK_SIZE // 2)))
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        export.to_excel(writer, index=False, sheet_name="Sequences")
        if chunks:
            pd.DataFrame(chunks, columns=["Row", "Part", "Sequence"]).to_excel(
                writer, index=False, sheet_name=CHUNK_SHEET)
        for sheet in writer.sheets.values():
            sheet.freeze_panes = "A2"
            for row in sheet.iter_rows():
                for cell in row:
                    if isinstance(cell.value, str):
                        cell.data_type = "s"
    return buffer.getvalue()


def restore_excel_sequences(workbook, frame):
    if CHUNK_SHEET not in workbook.sheet_names:
        return frame
    parts = pd.read_excel(workbook, sheet_name=CHUNK_SHEET, dtype=str, keep_default_na=False)
    if list(parts.columns) != ["Row", "Part", "Sequence"] or "Sequence" not in frame:
        raise ValueError("Excel 的序列分片结构无效。")
    grouped = {}
    for row, part, sequence in parts.itertuples(index=False, name=None):
        row_id, part_id = int(row), int(part)
        group = grouped.setdefault(row_id, {})
        if part_id in group:
            raise ValueError("Excel 的序列分片编号重复。")
        group[part_id] = sequence
    for row, sequence in enumerate(frame["Sequence"], 1):
        if sequence != f"{CHUNK_MARKER}{row}":
            continue
        group = grouped.pop(row, {})
        if not group or set(group) != set(range(1, len(group) + 1)):
            raise ValueError("Excel 的序列分片缺失。")
        complete = "".join(group[index] for index in range(1, len(group) + 1))
        if "Length (bp)" in frame and len(complete) != int(frame.iloc[row - 1]["Length (bp)"]):
            raise ValueError("Excel 的序列分片长度与记录不一致。")
        frame.iat[row - 1, frame.columns.get_loc("Sequence")] = complete
    if grouped:
        raise ValueError("Excel 的序列分片与主表不匹配。")
    return frame
