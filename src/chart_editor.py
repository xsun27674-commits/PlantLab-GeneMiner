"""Shared Plotly styling, session registry, and export controls."""

import json
from html import escape
import os
import re
from dataclasses import asdict, dataclass, replace
from math import ceil
from unicodedata import east_asian_width

import plotly.io as pio
from plotly.colors import qualitative
import streamlit as st
import streamlit.components.v1 as components

from src.i18n import tr, translator

from src.export_utils import csv_bytes

PALETTE = tuple(qualitative.Dark24)


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
    category_colors: bool = False
    before_color: str = "#9BC9B1"
    after_color: str = "#176B4D"
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
    for color in (style.color, style.font_color, style.background, style.before_color, style.after_color):
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
        if style.category_colors:
            color = {"筛选前": style.before_color, "筛选后": style.after_color}.get(trace.name, color)
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


def label_lines(value, width=18):
    """Wrap display text without shortening or rewriting identifiers."""
    lines, line, used = [], "", 0
    for character in str(value):
        cells = 2 if east_asian_width(character) in ("F", "W") else 1
        if used + cells > width:
            lines.append(line)
            line, used = "", 0
        line += character
        used += cells
    return [*lines, line]


def fit_category_axis(figure):
    """Choose readable ticks while retaining every plotted point."""
    axis = figure.layout.xaxis
    if axis.type not in (None, "category") or not axis.showticklabels:
        return
    values = [value for trace in figure.data if getattr(trace, "x", None) is not None
              for value in trace.x]
    if not values or not all(isinstance(value, str) for value in values):
        return
    ordered = list(dict.fromkeys(axis.categoryarray if axis.categoryarray is not None else values))
    source_labels = (figure.layout.meta or {}).get("category_labels", {})
    count = len(ordered)
    angle = 0 if count <= 6 else -50
    # The same ticks must fit the narrow preview as well as the wider export.
    budget = (4 if count > 3 else 12) if angle == 0 else 14
    wrapped = {tick: label_lines(source_labels.get(tick, tick), budget) for tick in ordered}
    if angle:
        narrow_width = min(320, figure.layout.width) - figure.layout.margin.l - figure.layout.margin.r
        thickest = max(map(len, wrapped.values()))
        max_ticks = max(2, min(10, int(narrow_width / (19 * thickest + 3))))
    else:
        max_ticks = 6
    ticks = ordered[::ceil(count / max_ticks)]
    labels = [wrapped[tick] for tick in ticks]
    height = max(len(lines) for lines in labels) * 15
    if angle:
        height += 75
    bottom = max(figure.layout.margin.b, height + 40)
    extra = bottom - figure.layout.margin.b
    figure.update_layout(height=figure.layout.height + extra, margin_b=bottom)
    figure.update_xaxes(
        type="category", tickmode="array", tickvals=ticks,
        ticktext=["<br>".join(escape(line) for line in lines) for lines in labels],
        tickangle=angle, tickfont_size=11, title_standoff=12, automargin=True,
    )
    figure.update_yaxes(automargin=True)


def fit_query_legend(figure, width=None):
    """Reserve a dedicated bottom legend region, including one column on narrow screens."""
    if not figure.layout.showlegend or not any(trace.name for trace in figure.data):
        return figure
    entries = []
    for trace in figure.data:
        chunks = label_lines(trace.name)
        trace.name = "<br>".join(escape(chunk) for chunk in chunks)
        if trace.name:
            entries.append(16 * len(chunks) + 14)
    columns = max(1, (int(width or figure.layout.width) - 100) // 218)
    space = 42 + sum(max(entries[start:start + columns])
                     for start in range(0, len(entries), columns))
    figure.update_layout(
        height=figure.layout.height + space,
        margin_b=figure.layout.margin.b + space,
        legend=dict(orientation="h", x=0.035, xref="container", xanchor="left",
                    y=0.015, yanchor="bottom", yref="container", entrywidth=169,
                    entrywidthmode="pixels", font_size=12,
                    font_family="Noto Sans Mono CJK SC, monospace", maxheight=space),
    )
    return figure


def static_images_enabled():
    return os.environ.get("GENEMINER_LIGHTWEIGHT_PREVIEW") != "1"


def image_bytes(figure, format, scale=None):
    return pio.to_image(figure, format=format, scale=scale or (2 if format == "png" else 1))


def export_filename(value, fallback):
    value = re.sub(r"[^\w.-]", "_", value.strip())[:80].strip(".")
    return value or fallback


def chart_panel(key, builder, data, defaults, groupable=False):
    with st.container(border=True, key=f"chart_card_{key}"):
        _chart_panel(key, builder, data, defaults, groupable)


def _chart_panel(key, builder, data, defaults, groupable):
    baseline = defaults
    heading = st.empty()
    preview = st.container()
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
    with st.expander(tr("编辑图表")):
        if st.button(tr("恢复默认样式"), key=f"reset_style_{key}"):
            defaults = baseline
            reset_controls(key, defaults)
        config = st.file_uploader(tr("导入绘图配置 JSON"), type=["json"], key=f"style_file_{key}")
        if config is not None and st.button(tr("恢复样式"), key=f"style_import_{key}"):
            try:
                defaults = load_style(config.getvalue())
                reset_controls(key, defaults)
            except (ValueError, TypeError, OverflowError) as exc:
                st.error(f"配置无效：{exc}")
        names = {
            "category_colors": "按类别配色", "before_color": "筛选前颜色", "after_color": "筛选后颜色",
            "title": "图表标题", "x_title": "横轴名称", "y_title": "纵轴名称",
            "color": "绘图颜色", "font_color": "字体颜色", "background": "背景颜色",
            "legend_title": "图例名称", "x_range": "横轴范围（最小,最大）",
            "y_range": "纵轴范围（最小,最大）", "margin": "边距",
            "opacity": "透明度", "font_size": "字体大小", "width": "宽度",
            "height": "高度", "point_size": "散点大小", "bar_gap": "柱间距",
            "grid": "网格线", "ticks": "显示刻度", "legend": "显示图例",
            "query_colors": "按 Query 分色", "query_palette": "Query 颜色映射（JSON）",
        }
        basic = st.container()
        with st.expander(tr("标题与坐标轴")):
            axes = st.columns(2)
        with st.expander(tr("布局与高级设置")):
            advanced = st.columns(2)
        trace_type = {trace.type for trace in builder(False).data}
        basics = {"title", "category_colors", "before_color", "after_color", "color"}
        values = asdict(defaults)
        for index, (field, label) in enumerate(names.items()):
            control = basic if field in basics else (
                axes[index % 2] if field in ("x_title", "y_title", "x_range", "y_range", "ticks")
                else advanced[index % 2])
            label = tr(label)
            widget_key = f"style_value_{key}_{field}"
            value = values[field]
            if field in ("category_colors", "before_color", "after_color") and key != "blast_comparison":
                continue
            if field in ("query_colors", "query_palette") and not groupable:
                continue
            if field == "point_size" and not trace_type.intersection({"scatter", "scattergl"}):
                continue
            if field == "bar_gap" and not trace_type.intersection({"bar", "histogram"}):
                continue
            if key == "blast_comparison":
                if field == "color" and values["category_colors"]:
                    continue
                if field in ("before_color", "after_color") and not values["category_colors"]:
                    continue
            if field in ("color", "font_color", "background", "before_color", "after_color"):
                values[field] = control.color_picker(label, value, key=widget_key)
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
    fit_category_axis(figure)
    figure.update_xaxes(automargin=True)
    figure.update_yaxes(automargin=True)
    figure.update_layout(meta={"axis_source": [style.x_title, style.y_title]})
    responsive = type(figure)(figure)
    if style.query_colors:
        fit_query_legend(figure)
        fit_query_legend(responsive, width=300)
    st.session_state.setdefault("report_figures", {})[key] = (style.title, figure)
    with heading.container():
        st.markdown(f"**{escape(visible_style.title)}**")
        if key == "blast_comparison":
            st.caption(tr("柱形统计 BLAST 命中记录。一个 Subject 可对应多条记录。"))
    filename = export_filename(key, "chart")
    responsive.update_layout(width=None, autosize=True)
    html = pio.to_html(responsive, full_html=False, include_plotlyjs=True, div_id="chart",
                       config={"displaylogo": False, "responsive": True,
                               "modeBarButtonsToRemove": ["toImage"]})
    with preview:
        components.html(browser_chart(html, filename, figure.layout), height=responsive.layout.height + 66)
    with st.expander(tr("更多")):
        exports = st.columns(3)
        exports[0].download_button(tr("交互 HTML"), pio.to_html(figure, full_html=True, include_plotlyjs=True),
                                   f"{filename}.html", "text/html", key=f"html_{key}")
        exports[1].download_button(tr("图表数据 CSV"), csv_bytes(data), f"{filename}.csv", "text/csv", key=f"csv_{key}")
        exports[2].download_button(tr("样式 JSON"), json.dumps(asdict(style), ensure_ascii=False, indent=2),
                                   f"{filename}.json", "application/json", key=f"json_{key}")
def browser_chart(plot_html, filename, layout):
    buttons = "".join(
        f'<button type="button" data-format="{kind}">{escape(tr(f"下载 {kind.upper()}"))}</button>'
        for kind in ("png", "svg")
    )
    options = json.dumps({"filename": filename, "width": layout.width, "height": layout.height})
    export_layout = json.dumps({key: layout[key].to_plotly_json() for key in ("margin", "legend")}).replace("<", "\\u003c")
    failure = json.dumps(tr("图片下载失败，请重试。"), ensure_ascii=True)
    return f"""
<style>
body {{ margin:0; font:14px system-ui,sans-serif; }}
.plotly-graph-div {{ max-width:100%; }}
section {{ display:flex; gap:8px; flex-wrap:wrap; margin:5px 0; }}
button {{ border:1px solid #bad2c8; border-radius:7px; padding:7px 12px;
          background:#f5faf7; color:#176b4d; cursor:pointer; }}
</style>
{plot_html}
<section>{buttons}<span role="status"></span></section>
<script>
document.querySelectorAll('button[data-format]').forEach(button => {{
  button.addEventListener('click', async () => {{
    const status = document.querySelector('[role="status"]');
    const format = button.dataset.format;
    button.disabled = true;
    status.textContent = '';
    try {{
      const chart = document.getElementById('chart');
      await Plotly.downloadImage({{data: chart.data, layout: {{...chart.layout, ...{export_layout}}}}},
        {{...{options}, format, scale: format === 'png' ? 2 : 1}});
    }} catch (error) {{
      status.textContent = {failure};
    }} finally {{
      button.disabled = false;
    }}
  }});
}});
</script>"""


def reset_controls(key, style):
    for field, value in asdict(style).items():
        widget_key = f"style_value_{key}_{field}"
        st.session_state[widget_key] = value
