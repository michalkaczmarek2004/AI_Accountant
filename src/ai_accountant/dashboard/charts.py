"""Hand-rolled inline-SVG chart renderers (no JS, no third-party deps)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from html import escape

LINE_WIDTH = 880
LINE_HEIGHT = 220
BAR_WIDTH = 880
BAR_HEIGHT = 220
LEFT_MARGIN = 40
RIGHT_MARGIN = 8
TOP_MARGIN = 8
BOTTOM_MARGIN = 24


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
    y_min = min(0.0, min(ys))
    y_max = max(0.0, max(ys))
    if y_min == y_max:
        y_max = y_min + 1.0

    plot_w = width - LEFT_MARGIN - RIGHT_MARGIN
    plot_h = height - TOP_MARGIN - BOTTOM_MARGIN

    def project(i: int, y: float) -> tuple[float, float]:
        if len(sorted_points) == 1:
            x = LEFT_MARGIN + plot_w / 2
        else:
            x = LEFT_MARGIN + (i / (len(sorted_points) - 1)) * plot_w
        py = TOP_MARGIN + plot_h - ((y - y_min) / (y_max - y_min)) * plot_h
        return x, py

    line_points = [project(i, y) for i, y in enumerate(ys)]
    line_d = "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in line_points)

    base_y = TOP_MARGIN + plot_h - ((0.0 - y_min) / (y_max - y_min)) * plot_h
    area_d = (
        f"M {line_points[0][0]:.1f} {base_y:.1f} "
        + " L ".join(f"{x:.1f} {y:.1f}" for x, y in line_points)
        + f" L {line_points[-1][0]:.1f} {base_y:.1f} Z"
    )

    y_ticks = _line_y_ticks(y_min, y_max)
    y_tick_lines: list[str] = []
    for tv in y_ticks:
        ty = TOP_MARGIN + plot_h - ((tv - y_min) / (y_max - y_min)) * plot_h
        y_tick_lines.append(
            f'<text class="ai-chart-tick" x="{LEFT_MARGIN - 4:.1f}" y="{ty:.1f}" '
            f'text-anchor="end" dominant-baseline="middle">{escape(_fmt_y(tv))}</text>'
        )

    x_tick_count = min(5, len(sorted_points))
    x_tick_lines: list[str] = []
    if x_tick_count >= 2:
        for k in range(x_tick_count):
            idx = round(k * (len(sorted_points) - 1) / (x_tick_count - 1))
            tx, _ = project(idx, ys[idx])
            label = escape(xs[idx].isoformat())
            x_tick_lines.append(
                f'<text class="ai-chart-tick" x="{tx:.1f}" '
                f'y="{TOP_MARGIN + plot_h + 14:.1f}" text-anchor="middle">{label}</text>'
            )

    return _wrap_svg(
        width,
        height,
        title=f"{y_label or 'Series'} over time",
        body="\n".join(
            [
                f'<line class="ai-chart-baseline" x1="{LEFT_MARGIN}" y1="{base_y:.1f}" '
                f'x2="{width - RIGHT_MARGIN}" y2="{base_y:.1f}" />',
                f'<path class="ai-chart-area" d="{area_d}" />',
                f'<path class="ai-chart-line" d="{line_d}" />',
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
    n = len(active)
    band = plot_w / n
    bar_w = band * 0.8
    bar_pad = (band - bar_w) / 2

    max_total = max(sum(b[1].get(s, 0) for s in series_order) for b in active)
    if max_total == 0:
        return _empty_svg(width, height, empty_message)

    rects: list[str] = []
    label_lines: list[str] = []
    every_n = max(1, n // 8)
    for i, (bin_start, counts) in enumerate(active):
        x_left = LEFT_MARGIN + i * band + bar_pad
        accumulated = 0
        for series in series_order:
            value = int(counts.get(series, 0) or 0)
            if value <= 0:
                continue
            seg_h = (value / max_total) * plot_h
            top_y = TOP_MARGIN + plot_h - accumulated - seg_h
            rects.append(
                f'<rect class="ai-chart-bar ai-chart-bar-{escape(series)}" '
                f'x="{x_left:.1f}" y="{top_y:.1f}" '
                f'width="{bar_w:.1f}" height="{seg_h:.1f}" />'
            )
            accumulated += seg_h
        if i % every_n == 0:
            label_lines.append(
                f'<text class="ai-chart-tick" x="{x_left + bar_w / 2:.1f}" '
                f'y="{TOP_MARGIN + plot_h + 14:.1f}" text-anchor="middle">'
                f"{escape(bin_start.isoformat())}</text>"
            )

    legend_items: list[str] = []
    for j, series in enumerate(series_order):
        ly = TOP_MARGIN + 4 + j * 14
        legend_items.append(
            f'<rect class="ai-chart-bar-{escape(series)}" '
            f'x="{width - RIGHT_MARGIN - 80}" y="{ly}" width="10" height="10" />'
            f'<text class="ai-chart-legend" x="{width - RIGHT_MARGIN - 66}" '
            f'y="{ly + 9}">{escape(series)}</text>'
        )

    return _wrap_svg(
        width,
        height,
        title="Activity over time",
        body="\n".join([*rects, *label_lines, *legend_items]),
        styles=_BAR_STYLES,
    )


def _decimate(points: list[tuple[date, Decimal]], *, max_points: int) -> list[tuple[date, Decimal]]:
    if len(points) <= max_points:
        return points
    step = len(points) / max_points
    return [points[int(i * step)] for i in range(max_points)]


def _fmt_y(value: float) -> str:
    if abs(value) < 1e-9:
        return "0"
    if abs(value) >= 1:
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _line_y_ticks(y_min: float, y_max: float) -> list[float]:
    if y_max <= y_min:
        return [y_min]
    span = y_max - y_min
    return [y_min + span * k / 3 for k in range(4)]


def _y_label_text(y_label: str, height: int) -> str:
    if not y_label:
        return ""
    return (
        f'<text class="ai-chart-axis-label" x="6" y="{height / 2:.1f}" '
        f'transform="rotate(-90 6 {height / 2:.1f})" '
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
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'role="img" aria-label="{escape(title)}">'
        f"<title>{escape(title)}</title>"
        f"<style>{styles}</style>"
        f"{body}"
        f"</svg>"
    )


_LINE_STYLES = (
    ".ai-chart-line { fill: none; stroke: #126a72; stroke-width: 2; }"
    ".ai-chart-area { fill: rgba(18, 106, 114, 0.15); stroke: none; }"
    ".ai-chart-baseline { stroke: #66737b; stroke-dasharray: 2 3; }"
    ".ai-chart-tick { fill: #66737b; font: 11px sans-serif; }"
    ".ai-chart-axis-label { fill: #172126; font: 11px sans-serif; }"
)
_BAR_STYLES = (
    ".ai-chart-bar { stroke: none; }"
    ".ai-chart-bar-succeeded { fill: #19734d; }"
    ".ai-chart-bar-failed { fill: #a83d31; }"
    ".ai-chart-tick { fill: #66737b; font: 11px sans-serif; }"
    ".ai-chart-legend { fill: #172126; font: 11px sans-serif; }"
)
_EMPTY_STYLES = ".ai-chart-empty { fill: #66737b; font: 13px sans-serif; }"


__all__ = ["render_line_svg", "render_bar_svg"]
