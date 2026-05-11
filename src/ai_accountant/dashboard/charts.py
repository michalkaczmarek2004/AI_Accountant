"""Hand-rolled inline-SVG chart renderers (no JS, no third-party deps)."""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from html import escape

LINE_WIDTH = 880
LINE_HEIGHT = 220
BAR_WIDTH = 880
BAR_HEIGHT = 220
LEFT_MARGIN = 78
RIGHT_MARGIN = 22
TOP_MARGIN = 18
BOTTOM_MARGIN = 40


def render_line_svg(
    points: Sequence[tuple[date, Decimal]],
    *,
    width: int = LINE_WIDTH,
    height: int = LINE_HEIGHT,
    y_label: str = "",
    empty_message: str = "No data in range.",
) -> str:
    if not points:
        return _empty_svg(width, height, empty_message)

    sorted_points = sorted(points, key=lambda p: p[0])
    sorted_points = _decimate(sorted_points, max_points=400)

    xs = [p[0] for p in sorted_points]
    ys = [float(p[1]) for p in sorted_points]
    y_min, y_max = _padded_domain(ys)
    y_ticks = _nice_ticks(y_min, y_max, max_ticks=5)
    y_min, y_max = y_ticks[0], y_ticks[-1]

    plot_w = width - LEFT_MARGIN - RIGHT_MARGIN
    plot_h = height - TOP_MARGIN - BOTTOM_MARGIN
    plot_bottom = TOP_MARGIN + plot_h

    def project(i: int, y: float) -> tuple[float, float]:
        if len(sorted_points) == 1:
            x = LEFT_MARGIN + plot_w / 2
        else:
            x = LEFT_MARGIN + (i / (len(sorted_points) - 1)) * plot_w
        py = _project_y(y, y_min, y_max, plot_h)
        return x, py

    line_points = [project(i, y) for i, y in enumerate(ys)]

    base_y = _project_y(0.0, y_min, y_max, plot_h)

    grid_lines: list[str] = []
    y_tick_lines: list[str] = []
    for tv in y_ticks:
        ty = _project_y(tv, y_min, y_max, plot_h)
        grid_lines.append(
            f'<line class="ai-chart-grid" x1="{LEFT_MARGIN}" y1="{ty:.1f}" '
            f'x2="{width - RIGHT_MARGIN}" y2="{ty:.1f}" />'
        )
        y_tick_lines.append(
            f'<text class="ai-chart-tick ai-chart-y-tick" x="{LEFT_MARGIN - 8:.1f}" y="{ty:.1f}" '
            f'text-anchor="end" dominant-baseline="middle">{escape(_fmt_y(tv))}</text>'
        )

    x_tick_lines: list[str] = []
    max_x_ticks = max(2, min(6, plot_w // 120))
    for idx in _x_tick_indices(len(sorted_points), max_ticks=max_x_ticks):
        tx, _ = project(idx, ys[idx])
        label = escape(_fmt_date(xs[idx], xs))
        x_tick_lines.append(
            f'<text class="ai-chart-tick ai-chart-x-tick" x="{tx:.1f}" '
            f'y="{plot_bottom + 22:.1f}" text-anchor="{_x_anchor(tx, width)}">{label}</text>'
        )

    has_negative = y_min < 0
    negative_layer = ""
    if has_negative and base_y < plot_bottom:
        negative_layer = (
            f'<rect class="ai-chart-negative-band" x="{LEFT_MARGIN}" y="{base_y:.1f}" '
            f'width="{plot_w:.1f}" height="{plot_bottom - base_y:.1f}" />'
        )

    marker_layers = [
        (
            '<g class="ai-chart-point">'
            f"<title>{escape(xs[i].isoformat())}: {escape(_fmt_y(ys[i]))} {escape(y_label)}</title>"
            f'<circle class="ai-chart-hit" cx="{x:.1f}" cy="{y:.1f}" r="8" />'
            f'<circle class="ai-chart-marker" cx="{x:.1f}" cy="{y:.1f}" r="2.8" />'
            "</g>"
        )
        for i, (x, y) in enumerate(line_points)
    ]

    data_layers: list[str]
    if len(line_points) == 1:
        x, y = line_points[0]
        data_layers = [
            (
                '<g class="ai-chart-point">'
                f"<title>{escape(xs[0].isoformat())}: {escape(_fmt_y(ys[0]))} {escape(y_label)}</title>"
                f'<circle class="ai-chart-hit" cx="{x:.1f}" cy="{y:.1f}" r="9" />'
                f'<circle class="ai-chart-marker" cx="{x:.1f}" cy="{y:.1f}" r="4.2" />'
                "</g>"
            )
        ]
    else:
        line_d = "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in line_points)
        area_d = (
            f"M {line_points[0][0]:.1f} {base_y:.1f} "
            + " L ".join(f"{x:.1f} {y:.1f}" for x, y in line_points)
            + f" L {line_points[-1][0]:.1f} {base_y:.1f} Z"
        )
        data_layers = [
            f'<path class="ai-chart-area" d="{area_d}" />',
            f'<path class="ai-chart-line" d="{line_d}" />',
            *marker_layers,
        ]

    return _wrap_svg(
        width,
        height,
        title=f"{y_label or 'Series'} over time",
        body="\n".join(
            [
                _line_defs(),
                negative_layer,
                *grid_lines,
                f'<line class="ai-chart-axis" x1="{LEFT_MARGIN}" y1="{TOP_MARGIN}" '
                f'x2="{LEFT_MARGIN}" y2="{plot_bottom:.1f}" />',
                f'<line class="ai-chart-axis" x1="{LEFT_MARGIN}" y1="{plot_bottom:.1f}" '
                f'x2="{width - RIGHT_MARGIN}" y2="{plot_bottom:.1f}" />',
                f'<line class="ai-chart-baseline{" ai-chart-baseline-warning" if has_negative else ""}" x1="{LEFT_MARGIN}" y1="{base_y:.1f}" '
                f'x2="{width - RIGHT_MARGIN}" y2="{base_y:.1f}" />',
                *data_layers,
                *y_tick_lines,
                *x_tick_lines,
                _y_label_text(y_label, height),
            ]
        ),
        styles=_LINE_STYLES,
    )


def render_bar_svg(
    buckets: Sequence[tuple[date, dict[str, int]]],
    *,
    series_order: tuple[str, ...] = ("succeeded", "failed"),
    width: int = BAR_WIDTH,
    height: int = BAR_HEIGHT,
    empty_message: str = "No transactions in range.",
) -> str:
    if not buckets:
        return _empty_svg(width, height, empty_message)

    active = [b for b in buckets if sum(b[1].get(s, 0) for s in series_order) > 0]
    if not active:
        return _empty_svg(width, height, empty_message)

    plot_w = width - LEFT_MARGIN - RIGHT_MARGIN
    plot_h = height - TOP_MARGIN - BOTTOM_MARGIN
    plot_bottom = TOP_MARGIN + plot_h
    n = len(active)
    band = plot_w / n
    bar_w = max(1.0, min(34.0, band * 0.72))
    bar_pad = (band - bar_w) / 2

    max_total = max(sum(b[1].get(s, 0) for s in series_order) for b in active)
    if max_total == 0:
        return _empty_svg(width, height, empty_message)
    y_axis_max = _count_axis_max(max_total)
    y_ticks = _count_ticks(y_axis_max)

    rects: list[str] = []
    label_lines: list[str] = []
    x_tick_indexes = set(_x_tick_indices(n, max_ticks=max(2, min(6, plot_w // 120))))
    for i, (bin_start, counts) in enumerate(active):
        x_left = LEFT_MARGIN + i * band + bar_pad
        accumulated = 0
        for series in series_order:
            value = int(counts.get(series, 0) or 0)
            if value <= 0:
                continue
            seg_h = (value / y_axis_max) * plot_h
            top_y = plot_bottom - accumulated - seg_h
            date_label = escape(_fmt_date(bin_start, [b[0] for b in active]))
            series_label = escape(series.replace("_", " ").title())
            rects.append(
                f'<rect class="ai-chart-bar ai-chart-bar-{escape(series)}" '
                f'x="{x_left:.1f}" y="{top_y:.1f}" '
                f'width="{bar_w:.1f}" height="{seg_h:.1f}" rx="4" ry="4">'
                f"<title>{date_label} - {series_label}: {value}</title>"
                "</rect>"
            )
            accumulated += seg_h
        if i in x_tick_indexes:
            label_lines.append(
                f'<text class="ai-chart-tick" x="{x_left + bar_w / 2:.1f}" '
                f'y="{plot_bottom + 22:.1f}" '
                f'text-anchor="{_x_anchor(x_left + bar_w / 2, width)}">'
                f"{escape(_fmt_date(bin_start, [b[0] for b in active]))}</text>"
            )

    grid_lines: list[str] = []
    y_tick_lines: list[str] = []
    for tick in y_ticks:
        ty = plot_bottom - (tick / y_axis_max) * plot_h
        grid_lines.append(
            f'<line class="ai-chart-grid" x1="{LEFT_MARGIN}" y1="{ty:.1f}" '
            f'x2="{width - RIGHT_MARGIN}" y2="{ty:.1f}" />'
        )
        y_tick_lines.append(
            f'<text class="ai-chart-tick ai-chart-y-tick" x="{LEFT_MARGIN - 8:.1f}" '
            f'y="{ty:.1f}" text-anchor="end" dominant-baseline="middle">{tick}</text>'
        )

    legend_items: list[str] = []
    for j, series in enumerate(series_order):
        ly = TOP_MARGIN + 4 + j * 14
        legend_items.append(
            f'<rect class="ai-chart-bar-{escape(series)}" '
            f'x="{width - RIGHT_MARGIN - 80}" y="{ly}" width="10" height="10" rx="3" ry="3" />'
            f'<text class="ai-chart-legend" x="{width - RIGHT_MARGIN - 66}" '
            f'y="{ly + 9}">{escape(series)}</text>'
        )

    return _wrap_svg(
        width,
        height,
        title="Activity over time",
        body="\n".join([
            *grid_lines,
            f'<line class="ai-chart-axis" x1="{LEFT_MARGIN}" y1="{TOP_MARGIN}" '
            f'x2="{LEFT_MARGIN}" y2="{plot_bottom:.1f}" />',
            f'<line class="ai-chart-axis" x1="{LEFT_MARGIN}" y1="{plot_bottom:.1f}" '
            f'x2="{width - RIGHT_MARGIN}" y2="{plot_bottom:.1f}" />',
            *rects,
            *y_tick_lines,
            *label_lines,
            *legend_items,
            _y_label_text("Count", height),
        ]),
        styles=_BAR_STYLES,
    )


def _decimate(points: list[tuple[date, Decimal]], *, max_points: int) -> list[tuple[date, Decimal]]:
    if len(points) <= max_points:
        return points
    step = len(points) / max_points
    return [points[int(i * step)] for i in range(max_points)]


def _project_y(value: float, y_min: float, y_max: float, plot_h: float) -> float:
    return TOP_MARGIN + plot_h - ((value - y_min) / (y_max - y_min)) * plot_h


def _padded_domain(values: Sequence[float]) -> tuple[float, float]:
    low = min(0.0, min(values))
    high = max(0.0, max(values))
    span = high - low
    pad = max(1.0, abs(high) * 0.1) if span <= 0 else span * 0.08
    return low - pad, high + pad


def _fmt_y(value: float) -> str:
    if abs(value) < 1e-9:
        return "0"
    sign = "-" if value < 0 else ""
    value = abs(value)
    if value >= 1_000_000:
        return f"{sign}{value / 1_000_000:.1f}M".replace(".0M", "M")
    if value >= 1_000:
        return f"{sign}{value / 1_000:.1f}k".replace(".0k", "k")
    if value >= 10:
        return f"{sign}{value:.0f}"
    if value >= 1:
        return f"{sign}{value:.2f}".rstrip("0").rstrip(".")
    return f"{sign}{value:.4f}".rstrip("0").rstrip(".")


def _nice_ticks(y_min: float, y_max: float, *, max_ticks: int) -> list[float]:
    if y_max <= y_min:
        return [y_min, y_min + 1.0]
    span = y_max - y_min
    step = _nice_number(span / max(1, max_ticks - 1), round_result=True)
    nice_min = math.floor(y_min / step) * step
    nice_max = math.ceil(y_max / step) * step
    ticks: list[float] = []
    current = nice_min
    guard = 0
    while current <= nice_max + step / 2 and guard < 20:
        ticks.append(0.0 if abs(current) < step / 1000 else current)
        current += step
        guard += 1
    if len(ticks) > max_ticks + 2:
        return _nice_ticks(y_min, y_max, max_ticks=max(2, max_ticks - 1))
    return ticks


def _nice_number(value: float, *, round_result: bool) -> float:
    if value <= 0:
        return 1.0
    exponent = math.floor(math.log10(value))
    fraction = value / (10 ** exponent)
    if round_result:
        if fraction < 1.5:
            nice_fraction = 1
        elif fraction < 3:
            nice_fraction = 2
        elif fraction < 7:
            nice_fraction = 5
        else:
            nice_fraction = 10
    else:
        if fraction <= 1:
            nice_fraction = 1
        elif fraction <= 2:
            nice_fraction = 2
        elif fraction <= 5:
            nice_fraction = 5
        else:
            nice_fraction = 10
    return nice_fraction * (10 ** exponent)


def _count_axis_max(max_total: int) -> int:
    if max_total <= 1:
        return 2
    raw = max_total * 1.15
    step = _nice_number(raw / 4, round_result=False)
    return max(max_total + 1, int(math.ceil(raw / step) * step))


def _count_ticks(max_count: int) -> list[int]:
    if max_count <= 5:
        return list(range(0, max_count + 1))
    step = max(1, int(_nice_number(max_count / 4, round_result=True)))
    ticks = list(range(0, max_count + 1, step))
    if ticks[-1] != max_count:
        ticks.append(max_count)
    return ticks


def _x_tick_indices(count: int, *, max_ticks: int) -> list[int]:
    if count <= 0:
        return []
    if count == 1:
        return [0]
    target = max(2, min(max_ticks, count))
    return sorted({round(i * (count - 1) / (target - 1)) for i in range(target)})


def _fmt_date(value: date, all_dates: Sequence[date]) -> str:
    if any(d.year != value.year for d in all_dates):
        return value.isoformat()
    return f"{value.month}/{value.day}"


def _x_anchor(x: float, width: int) -> str:
    if x < LEFT_MARGIN + 24:
        return "start"
    if x > width - RIGHT_MARGIN - 24:
        return "end"
    return "middle"


def _y_label_text(y_label: str, height: int) -> str:
    if not y_label:
        return ""
    return (
        f'<text class="ai-chart-axis-label" x="18" y="{height / 2:.1f}" '
        f'transform="rotate(-90 18 {height / 2:.1f})" '
        f'text-anchor="middle" dominant-baseline="hanging">{escape(y_label)}</text>'
    )


def _empty_svg(width: int, height: int, message: str) -> str:
    return _wrap_svg(
        width,
        height,
        title="Empty chart",
        body=(
            f'<text class="ai-chart-empty" x="{width / 2:.1f}" y="{height / 2:.1f}" '
            f'text-anchor="middle" dominant-baseline="middle">{escape(message)}</text>'
        ),
        styles=_EMPTY_STYLES,
    )


def _wrap_svg(width: int, height: int, *, title: str, body: str, styles: str) -> str:
    return (
        f'<svg class="ai-chart" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'role="img" aria-label="{escape(title)}">'
        f"<title>{escape(title)}</title>"
        f"<style>{styles}</style>"
        f"{body}"
        f"</svg>"
    )


def _line_defs() -> str:
    return (
        "<defs>"
        '<linearGradient id="ai-balance-gradient" x1="0" x2="0" y1="0" y2="1">'
        '<stop offset="0%" stop-color="#a78bfa" stop-opacity="0.28" />'
        '<stop offset="100%" stop-color="#7c3aed" stop-opacity="0.02" />'
        "</linearGradient>"
        "</defs>"
    )


_LINE_STYLES = (
    ".ai-chart-line { fill: none; stroke: #a78bfa; stroke-width: 2.8; stroke-linecap: round; stroke-linejoin: round; filter: drop-shadow(0 0 8px rgba(167, 139, 250, 0.35)); }"
    ".ai-chart-area { fill: url(#ai-balance-gradient); stroke: none; }"
    ".ai-chart-negative-band { fill: rgba(245, 158, 11, 0.08); stroke: none; }"
    ".ai-chart-baseline { stroke: rgba(148, 163, 184, 0.42); stroke-dasharray: 3 5; }"
    ".ai-chart-baseline-warning { stroke: rgba(245, 158, 11, 0.58); }"
    ".ai-chart-axis { stroke: rgba(148, 163, 184, 0.55); stroke-width: 1; }"
    ".ai-chart-grid { stroke: rgba(255, 255, 255, 0.06); stroke-width: 1; }"
    ".ai-chart-hit { fill: transparent; pointer-events: all; }"
    ".ai-chart-marker { fill: #a78bfa; stroke: #070711; stroke-width: 1.8; opacity: 0.82; }"
    ".ai-chart-point:hover .ai-chart-marker { fill: #22d3ee; opacity: 1; }"
    ".ai-chart-tick { fill: #94a3b8; font: 11px Inter, ui-sans-serif, system-ui, sans-serif; }"
    ".ai-chart-axis-label { fill: #cbd5e1; font: 11px Inter, ui-sans-serif, system-ui, sans-serif; }"
)
_BAR_STYLES = (
    ".ai-chart-bar { stroke: rgba(255, 255, 255, 0.06); stroke-width: 0.6; transition: opacity 150ms ease; }"
    ".ai-chart-bar:hover { opacity: 0.86; }"
    ".ai-chart-bar-succeeded { fill: #22c55e; }"
    ".ai-chart-bar-processed { fill: #22c55e; }"
    ".ai-chart-bar-confirmed { fill: #22c55e; }"
    ".ai-chart-bar-failed { fill: #ef4444; }"
    ".ai-chart-bar-error { fill: #ef4444; }"
    ".ai-chart-bar-warning { fill: #f59e0b; }"
    ".ai-chart-bar-review { fill: #f59e0b; }"
    ".ai-chart-bar-pending { fill: #3b82f6; }"
    ".ai-chart-bar-unknown { fill: #94a3b8; }"
    ".ai-chart-axis { stroke: rgba(148, 163, 184, 0.55); stroke-width: 1; }"
    ".ai-chart-grid { stroke: rgba(255, 255, 255, 0.06); stroke-width: 1; }"
    ".ai-chart-tick { fill: #94a3b8; font: 11px Inter, ui-sans-serif, system-ui, sans-serif; }"
    ".ai-chart-legend { fill: #cbd5e1; font: 11px Inter, ui-sans-serif, system-ui, sans-serif; }"
    ".ai-chart-axis-label { fill: #cbd5e1; font: 11px Inter, ui-sans-serif, system-ui, sans-serif; }"
)
_EMPTY_STYLES = ".ai-chart-empty { fill: #94a3b8; font: 13px Inter, ui-sans-serif, system-ui, sans-serif; }"


__all__ = ["render_line_svg", "render_bar_svg"]
