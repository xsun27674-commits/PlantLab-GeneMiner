"""Session analysis record used identically by JSON, Excel and document exports."""

from dataclasses import asdict

VERSION = "3.0.0"


def build_record(metadata, fasta_result=None, blast_result=None, pairwise_record=None):
    record = {"软件版本": VERSION, "科研信息": dict(metadata)}
    if fasta_result:
        record["FASTA"] = {key: value for key, value in fasta_result.items() if key not in {"key", "统计数据"}}
    if blast_result:
        record["BLAST"] = {
            "上传文件名称": blast_result["name"], "文件来源": blast_result["origin"],
            "分析时间（UTC）": blast_result["timestamp"], "原始命中数": blast_result["before"],
            "筛选后命中数": len(blast_result["filtered"]),
            "保留比例": f'{len(blast_result["filtered"]) / blast_result["before"]:.1%}' if blast_result["before"] else "0.0%",
            "分隔符": blast_result["delimiter"],
            "表头模式": blast_result["header"],
        }
        record["字段映射"] = blast_result["mapping"]
        record["筛选阈值"] = asdict(blast_result["thresholds"])
    if pairwise_record:
        record["成对序列比对"] = dict(pairwise_record)
    return record
