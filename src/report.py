"""Build structured, bilingual scientific Word reports."""

from datetime import datetime, timezone
from io import BytesIO

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches

from src.brand import logo
from src.i18n import tr

MAX_TABLE_ROWS = 1000

TEXT = {
    "zh": {
        "time": "报告生成时间（UTC）", "missing": "未设置", "empty": "没有记录。",
        "fasta": "使用 Biopython 解析 FASTA，统计长度，检查空序列、非法字符和重复 ID。核酸 GC 含量按可判定碱基计算。",
        "blast": "按用户映射和记录的阈值筛选 BLAST 表。候选数量按每条 Query 的唯一 Subject ID 统计。按比特得分优先选择最佳命中。",
        "alignment": "使用 Biopython PairwiseAligner 对两条序列评分。一致性分母包含所有比对列和 gap。",
        "limits": "BLAST 相似性证据需结合独立证据判断基因功能和直系同源关系。候选基因仍需进一步验证。",
        "demo": "文件含模拟教学数据，仅用于学习软件操作。",
        "discussion": "保留数量取决于输入表与当前阈值。覆盖度有缺失时，低覆盖度统计仅使用已知覆盖度。",
        "truncated": "显示前 {limit} 条，共 {total} 条。完整结果见 CSV 或 Excel。",
        "table": "表", "fig": "图", "page": "第 ", "suffix": " 页",
    },
    "en": {
        "time": "Report generated (UTC)", "missing": "Not set", "empty": "No records.",
        "fasta": "Biopython parsed FASTA and checked sequence length, empty entries, invalid characters and duplicate IDs. Nucleotide GC used classifiable bases.",
        "blast": "The BLAST table was screened using the recorded mapping and thresholds. Counts use unique subject IDs per query. Best-hit ranking prioritizes bitscore.",
        "alignment": "Biopython PairwiseAligner scored two sequences. The identity denominator includes all alignment columns, including gaps.",
        "limits": "Sequence similarity alone cannot establish gene function or orthology. Candidate genes require independent validation.",
        "demo": "This report includes synthetic teaching data. Do not use these data for biological inference.",
        "discussion": "Retention depends on the input table and current thresholds. Low-coverage counts use only reported coverage values.",
        "truncated": "Showing the first {limit} of {total} rows. See CSV or Excel for the full result.",
        "table": "Table", "fig": "Figure", "page": "Page ", "suffix": "",
    },
}


def word_report(title, background, notes, record, metrics, tables, figures, language="zh", mode="full"):
    text = TEXT[language]

    def label(value):
        return tr(value, language)

    def display(value):
        return text["missing"] if value is None else str(label(value))

    doc = Document()
    for style in ("Normal", "Title", "Heading 1", "Heading 2", "Caption"):
        doc.styles[style].element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), "宋体")
    doc.add_heading(title, 0)
    try:
        doc.add_picture(str(logo()), width=Inches(0.85))
    except (OSError, ValueError):
        pass
    demonstration = any(record.get(group, {}).get("文件来源") == "模拟教学数据" for group in ("FASTA", "BLAST"))
    if demonstration:
        doc.add_heading(label("教学演示报告"), level=2)
        doc.add_paragraph(text["demo"])
    doc.add_paragraph(f"{text['time']} · {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    doc.add_paragraph(f"{label('软件版本')} · {record['软件版本']}")
    doc.add_heading(label("分析概览"), level=1)
    for key, value in record["科研信息"].items():
        if value:
            doc.add_paragraph(f"{label(key)} · {display(value)}")
    if background:
        doc.add_heading(label("研究背景"), level=2)
        doc.add_paragraph(background)

    doc.add_heading(label("数据与方法"), level=1)
    for group, key in (("FASTA", "fasta"), ("BLAST", "blast"), ("成对序列比对", "alignment")):
        if group in record:
            doc.add_heading(label(group), level=2)
            doc.add_paragraph(text[key])
            for name, value in record[group].items():
                doc.add_paragraph(f"{label(name)} · {display(value)}")

    doc.add_heading(label("分析结果"), level=1)
    for name, value in metrics.items():
        doc.add_paragraph(f"{label(name)} · {display(value)}")
    if not metrics:
        doc.add_paragraph(text["empty"])
    if figures:
        doc.add_heading(label("数据可视化"), level=1)
        for number, (name, image) in enumerate(figures, 1):
            doc.add_picture(BytesIO(image), width=Inches(6))
            doc.paragraphs[-1].paragraph_format.keep_with_next = True
            doc.add_paragraph(f"{text['fig']} {number}  {label(name)}", style="Caption")
    if tables:
        doc.add_heading(label("候选基因比较"), level=1)
        for number, (name, frame) in enumerate(tables.items(), 1):
            doc.add_heading(f"{text['table']} {number} · {label(name)}", level=2)
            if frame.empty:
                doc.add_paragraph(text["empty"])
                continue
            limit = 25 if mode == "concise" else MAX_TABLE_ROWS
            if len(frame) > limit:
                doc.add_paragraph(text["truncated"].format(limit=limit, total=len(frame)))
            table = doc.add_table(rows=1, cols=len(frame.columns))
            table.style = "Light Shading Accent 1"
            table.rows[0]._tr.get_or_add_trPr().append(OxmlElement("w:tblHeader"))
            for cell, column in zip(table.rows[0].cells, frame.columns):
                cell.text = label(column)
            for values in frame.head(limit).fillna("").itertuples(index=False, name=None):
                row = table.add_row()
                row._tr.get_or_add_trPr().append(OxmlElement("w:cantSplit"))
                for cell, value in zip(row.cells, values):
                    cell.text = display(value)

    doc.add_heading(label("结果讨论"), level=1)
    if "BLAST" in record:
        doc.add_paragraph(text["discussion"])
    if notes:
        doc.add_paragraph(notes)
    doc.add_heading(label("分析局限性"), level=1)
    doc.add_paragraph(text["limits"])
    if mode == "full":
        appendix = {key: record[key] for key in ("字段映射", "筛选阈值") if key in record}
    else:
        appendix = {key: record[key] for key in ("筛选阈值",) if key in record}
    if appendix:
        doc.add_heading(label("附录"), level=1)
        for section, entries in appendix.items():
            doc.add_heading(label(section), level=2)
            for name, value in entries.items():
                doc.add_paragraph(f"{label(name)} · {display(value)}")

    footer = doc.sections[0].footer.paragraphs[0]
    footer.add_run(text["page"])
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), "PAGE")
    footer._p.append(field)
    footer.add_run(text["suffix"])
    buffer = BytesIO()
    doc.save(buffer)
    return buffer.getvalue()
