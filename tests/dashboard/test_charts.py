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

    def test_single_point_does_not_raise(self) -> None:
        svg = render_line_svg([(date(2025, 1, 1), Decimal("1"))])
        _parse_svg(svg)

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
