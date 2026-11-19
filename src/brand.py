"""Configurable brand asset with a first-party monogram fallback."""

import os
from pathlib import Path

import streamlit as st
from PIL import Image

from src.i18n import tr

NAME = "PlantLab-GeneMiner"
TAGLINE = "Explore Genes. Discover Possibilities."
ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
PLACEHOLDER = ASSETS / "logo-placeholder.png"


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
    for column, (name, label) in zip(st.columns(2), EXAMPLES.values()):
        column.download_button(f"{tr('下载')} {tr(label)}", (DATA / name).read_bytes(), name, "text/plain")
    sections = (
        ("FASTA 文件", "每条记录从 > 和序列 ID 开始，随后为核酸或蛋白质序列。导入时请选择类型。"),
        ("BLAST 字段", "pident 是序列一致性百分比，bitscore 是比特得分，E-value 是期望随机命中数，qcovs 是每个 Subject 的查询覆盖度。"),
        ("候选筛选", "先查看字段映射，再调整一致性、E-value、长度和覆盖度。成对比对、数据库搜索与命中筛选是不同操作。"),
        ("图表与报告", "编辑样式后使用图表工具栏或图片导出。打开分析记录页面，选择报告语言、图表和结果表。"),
        ("账户与项目", "游客可以直接分析。项目保存需要登录和可用的持久化服务。退出前请确认保存成功。"),
        ("常见问题", "覆盖度缺失时不要当作 0%。相似性证据无法单独确认基因功能。恢复项目时请确认是否替换当前工作区。"),
    )
    for title, body in sections:
        with st.expander(tr(title)):
            st.write(tr(body))
