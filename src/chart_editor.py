"""Shared Plotly styling, session registry, and export controls."""

import json
import os
import re
from dataclasses import asdict, dataclass, replace

import plotly.io as pio
from plotly.colors import qualitative
import streamlit as st

from src.i18n import tr, translator

from src.export_utils import csv_bytes

PALETTE = tuple(qualitative.Dark24)
PRESETS = ("教学展示", "科研论文", "自定义")


@dataclass(frozen=True)
class ChartStyle:
    title: str
    x_title: str
    y_title: str
    color: str = "#147756"
    font_color: str = "#17332A"
    background: str = "#FFFFFF"
    opacity: float = 0.9
    font_size: int = 16
    width: int = 800
    height: int = 420
    margin: int = 55
    point_size: int = 9
    bar_gap: float = 0.35
    grid: bool = True
    ticks: bool = True
    legend: bool = True
    legend_title: str = "Query"
    query_colors: bool = False
    query_palette: str = ""
    x_range: str = ""
    y_range: str = ""


def axis_range(value):
    if not value.strip():
        return None
    bounds = tuple(float(item) for item in value.split(","))
    if len(bounds) != 2 or not -1e100 < bounds[0] < bounds[1] < 1e100:
        raise ValueError("坐标轴范围请输入递增的两个有限数值，用逗号分隔。")
    return bounds


def query_palette(value):
    if not isinstance(value, str) or len(value) > 2000:
        raise ValueError("Query 配色应为不超过 2,000 字符的 JSON 对象。")
    try:
        palette = json.loads(value) if value.strip() else {}
    except json.JSONDecodeError as exc:
        raise ValueError('Query 配色需要 JSON 格式，例如 {"Q1": "#147756"}。') from exc
    if not isinstance(palette, dict) or any(
        not isinstance(color, str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", color)
        for color in palette.values()
    ):
        raise ValueError("Query 配色需要使用 Query ID 与 HEX 色号。")
    return palette


def validate_style(style):
    for color in (style.color, style.font_color, style.background):
        if not isinstance(color, str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
            raise ValueError("颜色须为 6 位 HEX 色号，如 #147756。")
    for value, minimum, maximum in (
        (style.width, 340, 1800), (style.height, 260, 1200), (style.margin, 15, 120),
        (style.font_size, 9, 32), (style.point_size, 3, 30),
    ):
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError("图表尺寸、字体、边距或散点大小超出允许范围。")
    for value in (style.opacity, style.bar_gap):
        if type(value) not in (int, float) or not 0 <= value <= 1:
            raise ValueError("透明度和柱间距应在 0 到 1 之间。")
    for value in (style.title, style.x_title, style.y_title, style.legend_title, style.x_range, style.y_range):
        if not isinstance(value, str) or len(value) > 300:
            raise ValueError("标题或坐标轴配置无效。")
    if any(type(value) is not bool for value in (style.grid, style.ticks, style.legend, style.query_colors)):
        raise ValueError("图表开关须使用布尔值。")
    query_palette(style.query_palette)
    axis_range(style.x_range)
    axis_range(style.y_range)
    return style


def load_style(raw):
    if len(raw) > 16000:
        raise ValueError("绘图配置超过 16 KB。")
    return validate_style(ChartStyle(**json.loads(raw)))


def apply_style(figure, style):
    validate_style(style)
    fig = type(figure)(figure)
    custom_palette = query_palette(style.query_palette) if style.query_colors else {}
    for index, trace in enumerate(fig.data):
        color = PALETTE[(index - 1) % len(PALETTE)] if style.query_colors and index else style.color
        color = custom_palette.get(trace.name, color)
        updates = {"opacity": style.opacity}
        if trace.type in ("scatter", "scattergl"):
            updates.update(marker_color=color, marker_size=style.point_size, line_color=color)
        elif trace.type in ("bar", "histogram"):
            updates["marker_color"] = color
        trace.update(updates)
    fig.update_layout(
        title_text=style.title, font_size=style.font_size, font_color=style.font_color,
        width=style.width, height=style.height, bargap=style.bar_gap,
        font_family="Noto Sans CJK SC, Microsoft YaHei, sans-serif",
        margin=dict.fromkeys(("l", "r", "t", "b"), style.margin),
        paper_bgcolor=style.background, plot_bgcolor=style.background,
        showlegend=style.legend, legend_title_text=style.legend_title,
    )
    for update, title, limits in (
        (fig.update_xaxes, style.x_title, style.x_range),
        (fig.update_yaxes, style.y_title, style.y_range),
    ):
        update(title_text=title, showgrid=style.grid, showticklabels=style.ticks,
               ticks="outside" if style.ticks else "", range=axis_range(limits))
    return fig


def static_images_enabled():
    return os.environ.get("GENEMINER_LIGHTWEIGHT_PREVIEW") != "1"


def image_bytes(figure, format, scale=None):
    return pio.to_image(figure, format=format, scale=scale or (2 if format == "png" else 1))


def export_filename(value, fallback):
    value = re.sub(r"[^\w.-]", "_", value.strip())[:80].strip(".")
    return value or fallback


def chart_panel(key, builder, data, defaults, groupable=False):
    style_key = f"chart_style_{key}"
    previous_defaults = st.session_state.get(f"chart_defaults_{key}", defaults)
    st.session_state[f"chart_defaults_{key}"] = defaults
    current = st.session_state.get(style_key, defaults)
    for field in ("x_title", "y_title"):
        if getattr(current, field) == getattr(previous_defaults, field) != getattr(defaults, field):
            value = getattr(defaults, field)
            current = replace(current, **{field: value})
            st.session_state[f"style_value_{key}_{field}"] = value
    defaults = current
    with st.expander(tr("图表样式与导出")):
        preset = st.selectbox(tr("绘图模板"), PRESETS, index=2, key=f"style_preset_{key}", format_func=translator())
        if st.button(tr("应用模板"), key=f"style_apply_{key}"):
            if preset != "自定义":
                defaults = replace(defaults, font_size=19 if preset == "教学展示" else 13,
                                   grid=preset == "教学展示", background="#FFFFFF",
                                   color="#147756" if preset == "教学展示" else "#203C5F")
            reset_controls(key, defaults)
        config = st.file_uploader(tr("导入绘图配置 JSON"), type=["json"], key=f"style_file_{key}")
        if config is not None and st.button(tr("恢复样式"), key=f"style_import_{key}"):
            try:
                defaults = load_style(config.getvalue())
                reset_controls(key, defaults)
            except (ValueError, TypeError, OverflowError) as exc:
                st.error(f"配置无效：{exc}")
        names = {
            "title": "图表标题", "x_title": "横轴名称", "y_title": "纵轴名称",
            "color": "绘图颜色", "font_color": "字体颜色", "background": "背景颜色",
            "legend_title": "图例名称", "x_range": "横轴范围（最小,最大）",
            "y_range": "纵轴范围（最小,最大）", "margin": "边距",
            "opacity": "透明度", "font_size": "字体大小", "width": "宽度",
            "height": "高度", "point_size": "散点大小", "bar_gap": "柱间距",
            "grid": "网格线", "ticks": "显示刻度", "legend": "显示图例",
            "query_colors": "按 Query 分色", "query_palette": "Query 颜色映射（JSON）",
        }
        controls = st.columns(3)
        values = asdict(defaults)
        for index, (field, label) in enumerate(names.items()):
            control = controls[index % 3]
            label = tr(label)
            widget_key = f"style_value_{key}_{field}"
            value = values[field]
            if field in ("query_colors", "query_palette") and not groupable:
                continue
            if field in ("color", "font_color", "background"):
                def update_hex(picker=widget_key, hex_key=f"{widget_key}_hex"):
                    st.session_state[hex_key] = st.session_state[picker]
                control.color_picker(label, value, key=widget_key, on_change=update_hex)
                values[field] = control.text_input(f"{label} HEX", value, key=f"{widget_key}_hex")
            elif isinstance(value, bool):
                values[field] = control.checkbox(label, value, key=widget_key)
            elif isinstance(value, (int, float)):
                ranges = {"width": (340, 1800), "height": (260, 1200), "margin": (15, 120),
                          "point_size": (3, 30), "font_size": (9, 32)}
                lower, upper = ranges.get(field, (0.0, 1.0))
                values[field] = control.slider(label, lower, upper, value, key=widget_key)
            else:
                values[field] = control.text_input(
                    label, value, max_chars=2000 if field == "query_palette" else 300, key=widget_key,
                    help='例如 {"SIM_Q01": "#AA0033"}。启用按 Query 分色后应用。'
                    if field == "query_palette" else None,
                )
        try:
            style = validate_style(ChartStyle(**values))
        except ValueError as exc:
            st.warning(f"{exc} 暂时保留上一次有效样式。")
            style = defaults

    st.session_state[style_key] = style
    visible_style = replace(style, title=tr(style.title), x_title=tr(style.x_title),
                            y_title=tr(style.y_title), legend_title=tr(style.legend_title))
    figure = apply_style(builder(style.query_colors if groupable else False), visible_style)
    figure.update_layout(meta={"axis_source": [style.x_title, style.y_title]})
    st.session_state.setdefault("report_figures", {})[key] = (style.title, figure)
    with st.expander(tr("图片导出")):
        filename = export_filename(
            st.text_input(tr("文件名"), key, max_chars=80, key=f"filename_{key}"), key)
        scale = st.slider(tr("PNG 倍率"), 1, 3, 2, key=f"scale_{key}")
        formats = ["png", "svg", "pdf"] if static_images_enabled() else ["png", "svg"]
        fmt = st.selectbox(tr("图片格式"), formats, key=f"format_{key}")
        if not static_images_enabled():
            st.caption(tr("选择 PNG 或 SVG 后，点击图表工具栏的相机图标下载。"))
    st.plotly_chart(figure, key=f"plot_{key}", width="content", config={
        "displaylogo": False, "toImageButtonOptions": {
            "format": fmt if fmt != "pdf" else "png", "filename": filename,
            "width": style.width, "height": style.height, "scale": scale if fmt != "svg" else 1,
        },
    })
    with st.expander(tr("高级导出")):
        exports = st.columns(3)
        exports[0].download_button(tr("交互 HTML"), pio.to_html(figure, full_html=True, include_plotlyjs=True),
                                   f"{filename}.html", "text/html", key=f"html_{key}")
        exports[1].download_button(tr("图表数据 CSV"), csv_bytes(data), f"{filename}.csv", "text/csv", key=f"csv_{key}")
        exports[2].download_button(tr("样式 JSON"), json.dumps(asdict(style), ensure_ascii=False, indent=2),
                                   f"{filename}.json", "application/json", key=f"json_{key}")
    if static_images_enabled():
        asset_key = f"image_{key}"
        signature = (fmt, scale, figure.to_json())
        if st.button(tr("生成静态图"), key=f"render_{key}"):
            st.session_state.pop(asset_key, None)
            try:
                st.session_state[asset_key] = (signature, image_bytes(figure, fmt, scale if fmt == "png" else 1))
            except Exception:
                st.error(tr("静态图生成失败。请确认 Kaleido 和 Chrome/Chromium 可正常运行。"))
        asset = st.session_state.get(asset_key)
        if asset and asset[0] == signature:
            mime = {"png": "image/png", "svg": "image/svg+xml", "pdf": "application/pdf"}[fmt]
            st.download_button(f"下载 {fmt.upper()}", asset[1], f"{filename}.{fmt}", mime, key=f"image_download_{key}")


def reset_controls(key, style):
    for field, value in asdict(style).items():
        widget_key = f"style_value_{key}_{field}"
        st.session_state[widget_key] = value
        if field in ("color", "font_color", "background"):
            st.session_state[f"{widget_key}_hex"] = value
