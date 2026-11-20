"""Configurable brand asset with a first-party monogram fallback."""

import os
from base64 import b64encode
from functools import lru_cache
from pathlib import Path

import streamlit as st
from PIL import Image

from src.i18n import tr

NAME = "PlantLab-GeneMiner"
TAGLINE = "Explore Genes. Discover Possibilities."
ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"


def image_size(path):
    if path is None:
        return None
    try:
        with Image.open(path) as image:
            if image.format == "PNG":
                return image.size
    except (OSError, ValueError):
        pass
    return None


def logo():
    path = Path(os.environ.get("GENEMINER_LOGO_PATH") or ASSETS / "logo.png")
    return path if image_size(path) else None


def is_wide_logo(path):
    size = image_size(path)
    return bool(size and size[0] >= 1.4 * size[1])


def logo_icon():
    path = Path(os.environ.get("GENEMINER_LOGO_ICON_PATH") or ASSETS / "logo-icon.png")
    if image_size(path) and not is_wide_logo(path):
        return path
    banner = logo()
    return None if is_wide_logo(banner) else banner


@lru_cache(maxsize=2)
def brand_mark_uri(compact=False):
    suffix, mime = ("png", "image/png") if compact else ("svg", "image/svg+xml")
    encoded = b64encode((ASSETS / f"plantlab-mark.{suffix}").read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def brand_banner():
    path = logo()
    if is_wide_logo(path):
        st.image(str(path), width=720, caption=NAME)
        st.caption(TAGLINE)
        return
    if path is None:
        st.title(NAME)
        st.caption(TAGLINE)
        return
    left, right = st.columns([1, 7])
    left.image(str(path), width=90)
    right.title(NAME)
    right.caption(TAGLINE)


def help_center():
    st.title(tr("帮助中心"))
    from src.pages import DATA, EXAMPLES
    st.subheader(tr("模拟教学数据"))
    st.caption(tr("模拟教学数据，不代表真实科研结果。"))
    tips = ("用于 FASTA 序列统计。在「数据导入与管理」上传 .fasta 文件。",
            "用于导入与筛选示例。打开 BLAST 候选筛选页上传 .tsv 文件。")
    for column, (name, label), tip in zip(st.columns(2), EXAMPLES.values(), tips):
        column.download_button(f"{tr('下载')} {tr(label)}", (DATA / name).read_bytes(), name, "text/plain")
        column.caption(tr(tip))
    sections = (
        ("FASTA 文件", "每条记录从 > 和序列 ID 开始，随后为核酸或蛋白质序列。导入时请选择类型。"),
        ("BLAST 字段", "pident 是序列一致性百分比，bitscore 是比特得分，E-value 是期望随机命中数，qcovs 是每个 Subject 的查询覆盖度。"),
        ("候选筛选", "先查看字段映射，再调整一致性、E-value、长度和覆盖度。成对比对、数据库搜索与命中筛选是不同操作。"),
        ("图表与导出", "编辑样式后使用图表工具栏导出图片。可在分析记录页面下载结果和参数。"),
        ("账户与项目", "游客可以直接分析。项目保存需要登录和可用的持久化服务。退出前请确认保存成功。"),
        ("常见问题", "覆盖度缺失时不要当作 0%。相似性证据无法单独确认基因功能。恢复项目时请确认是否替换当前工作区。"),
    )
    for title, body in sections:
        with st.expander(tr(title)):
            st.write(tr(body))
