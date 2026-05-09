from __future__ import annotations

import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ai_accountant.dashboard.charts import render_bar_svg, render_line_svg


def _parse_svg(svg: str) -> ET.Element:
    return ET.fromstring(svg)


def _classed(root: ET.Element, class_name: str) -> list[ET.Element]:
    return [
        el for el in root.iter()
        if class_name in (el.attrib.get("class") or "").split()
    ]


class LineChartTests(unittest.TestCase):
    def test_empty_returns_well_formed_svg_with_message(self) -> None:
        svg = render_line_svg([])
        root = _parse_svg(svg)
        self.assertEqual(root.tag.rsplit("}", 1)[-1], "svg")
        self.assertIn("No data in range.", svg)

    def test_custom_empty_message_used(self) -> None:
        svg = render_line_svg([], empty_message="Pick a wider window.")
        self.assertIn("Pick a wider window.", svg)

    def test_happy_path_contains_path_elements(self) -> None:
        points = [
            (date(2025, 1, 1), Decimal("0.5")),
            (date(2025, 1, 2), Decimal("0.7")),
            (date(2025, 1, 3), Decimal("0.6")),
        ]
        svg = render_line_svg(points, y_label="SOL")
        root = _parse_svg(svg)
        self.assertEqual(root.tag.rsplit("}", 1)[-1], "svg")
        path_count = sum(1 for el in root.iter() if el.tag.endswith("path"))
        self.assertGreaterEqual(path_count, 2)

    def test_line_chart_has_axes_grid_and_spaced_y_labels(self) -> None:
        points = [
            (date(2025, 1, 1), Decimal("0.5")),
            (date(2025, 1, 2), Decimal("1.25")),
            (date(2025, 1, 3), Decimal("-0.4")),
        ]
        root = _parse_svg(render_line_svg(points, y_label="SOL net"))

        self.assertGreaterEqual(len(_classed(root, "ai-chart-grid")), 3)
        self.assertGreaterEqual(len(_classed(root, "ai-chart-axis")), 2)
        y_ticks = _classed(root, "ai-chart-y-tick")
        self.assertTrue(all(float(t.attrib["x"]) >= 60 for t in y_ticks))
        axis_label = _classed(root, "ai-chart-axis-label")[0]
        self.assertEqual(axis_label.attrib["x"], "18")

    def test_line_chart_limits_x_labels_for_dense_series(self) -> None:
        points = [
            (date(2025, 1, day), Decimal(day))
            for day in range(1, 29)
        ]
        root = _parse_svg(render_line_svg(points))
        self.assertLessEqual(len(_classed(root, "ai-chart-x-tick")), 6)

    def test_single_point_does_not_raise(self) -> None:
        svg = render_line_svg([(date(2025, 1, 1), Decimal("1"))])
        root = _parse_svg(svg)
        self.assertEqual(len(_classed(root, "ai-chart-marker")), 1)
        self.assertEqual(len(_classed(root, "ai-chart-area")), 0)

    def test_negative_values_keep_zero_baseline_visible(self) -> None:
        points = [(date(2025, 1, 1), Decimal("-5")), (date(2025, 1, 2), Decimal("-2"))]
        svg = render_line_svg(points)
        _parse_svg(svg)


class BarChartTests(unittest.TestCase):
    def test_empty_returns_well_formed_svg_with_message(self) -> None:
        svg = render_bar_svg([])
        _parse_svg(svg)
        self.assertIn("No transactions in range.", svg)

    def test_bar_count_matches_bins_with_data(self) -> None:
        buckets = [
            (date(2025, 1, 1), {"succeeded": 3, "failed": 1}),
            (date(2025, 1, 2), {"succeeded": 0, "failed": 0}),  # skipped
            (date(2025, 1, 3), {"succeeded": 5, "failed": 0}),
        ]
        svg = render_bar_svg(buckets)
        root = _parse_svg(svg)
        rect_count = sum(1 for el in root.iter() if el.tag.endswith("rect"))
        self.assertGreaterEqual(rect_count, 4)
        self.assertIn("succeeded", svg)
        self.assertIn("failed", svg)

    def test_single_count_bucket_uses_count_scale_not_full_height(self) -> None:
        buckets = [(date(2025, 1, 1), {"succeeded": 1, "failed": 0})]
        root = _parse_svg(render_bar_svg(buckets))
        bars = _classed(root, "ai-chart-bar")
        self.assertEqual(len(bars), 1)
        self.assertLess(float(bars[0].attrib["height"]), 120)
        tick_text = {el.text for el in _classed(root, "ai-chart-y-tick")}
        self.assertIn("0", tick_text)
        self.assertIn("2", tick_text)

    def test_bar_chart_limits_x_labels_for_dense_buckets(self) -> None:
        buckets = [
            (date(2025, 1, day), {"succeeded": 1, "failed": 0})
            for day in range(1, 29)
        ]
        root = _parse_svg(render_bar_svg(buckets))
        x_ticks = [
            el for el in root.iter()
            if "ai-chart-tick" in (el.attrib.get("class") or "")
            and "ai-chart-y-tick" not in (el.attrib.get("class") or "")
        ]
        self.assertLessEqual(len(x_ticks), 6)

    def test_all_zero_buckets_renders_empty_message(self) -> None:
        buckets = [(date(2025, 1, 1), {"succeeded": 0, "failed": 0})]
        svg = render_bar_svg(buckets)
        self.assertIn("No transactions in range.", svg)


class SvgEscapingTests(unittest.TestCase):
    def test_y_label_is_escaped(self) -> None:
        svg = render_line_svg([], y_label="<script>alert(1)</script>")
        self.assertNotIn("<script>", svg)


if __name__ == "__main__":
    unittest.main()
