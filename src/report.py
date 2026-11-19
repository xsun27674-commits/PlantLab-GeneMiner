"""Build a Word report from analysis records, selected tables and styled charts."""

from datetime import datetime, timezone
from io import BytesIO

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches

MAX_TABLE_ROWS = 1000


def word_report(title, background, notes, record, metrics, tables, figures):
    doc = Document()
    doc.styles["Normal"].element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), "宋体")
    doc.add_heading(title, 0)
    doc.add_heading("项目基本信息", level=1)
    doc.add_paragraph(f"报告生成时间（UTC）：{datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    doc.add_paragraph(f"软件版本：{record['软件版本']}")
    for label, value in record["科研信息"].items():
        if value:
            doc.add_paragraph(f"{label}：{value}")
    if background:
        doc.add_heading("研究背景", level=2)
        doc.add_paragraph(background)

    doc.add_heading("数据与方法", level=1)
    for group, entries in record.items():
        if not isinstance(entries, dict) or group == "科研信息":
            continue
        doc.add_heading(group, level=2)
        for name, value in entries.items():
            doc.add_paragraph(f"{name}：{'未设置' if value is None else value}")
    if "FASTA" in record:
        doc.add_paragraph("使用 Biopython 解析 FASTA，统计序列长度并检查空序列、字符和重复 ID。核酸数据按可判定碱基计算 GC。")
    if "BLAST" in record:
        doc.add_paragraph("映射用户提交的 BLAST 表格字段，按记录的阈值筛选，按 Query 与唯一 Subject ID 计数。最佳命中优先按比特得分选取。")

    if "成对序列比对" in record:
        doc.add_paragraph("使用 Biopython PairwiseAligner 对两条序列评分。一致性以所有比对列（含 gap）为分母。")

    doc.add_heading("分析结果", level=1)
    for label, value in metrics.items():
        doc.add_paragraph(f"{label}：{value}")
    for label, frame in tables.items():
        doc.add_heading(label, level=2)
        if len(frame) > MAX_TABLE_ROWS:
            doc.add_paragraph(f"显示前 {MAX_TABLE_ROWS} 条，共 {len(frame)} 条；完整结果请使用 CSV 或 Excel。")
        if frame.empty:
            doc.add_paragraph("没有记录。")
            continue
        table = doc.add_table(rows=1, cols=len(frame.columns))
        table.style = "Light Shading Accent 1"
        for cell, name in zip(table.rows[0].cells, frame.columns):
            cell.text = str(name)
        for values in frame.head(MAX_TABLE_ROWS).fillna("").itertuples(index=False, name=None):
            for cell, value in zip(table.add_row().cells, values):
                cell.text = str(value)

    if figures:
        doc.add_heading("图表", level=1)
        for number, (label, image) in enumerate(figures, 1):
            doc.add_picture(BytesIO(image), width=Inches(6))
            doc.add_paragraph(f"图 {number}  {label}", style="Caption")
    doc.add_heading("结果说明与局限性", level=1)
    if notes:
        doc.add_paragraph(notes)
    doc.add_paragraph("BLAST 相似性证据需结合独立证据判断基因功能和直系同源关系。候选基因仍需进一步验证。模拟教学数据仅用于学习软件操作。")
    footer = doc.sections[0].footer.paragraphs[0]
    footer.add_run("第 ")
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), "PAGE")
    footer._p.append(field)
    footer.add_run(" 页")
    buffer = BytesIO()
    doc.save(buffer)
    return buffer.getvalue()
