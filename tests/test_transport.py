from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_accountant.transport import (
    _CaseInsensitiveHeaders,
    _parse_retry_after,
)


class ParseRetryAfterTests(unittest.TestCase):
    def test_numeric_seconds(self):
        self.assertEqual(_parse_retry_after("5"), 5.0)
        self.assertEqual(_parse_retry_after("0.25"), 0.25)
        self.assertEqual(_parse_retry_after("0"), 0.0)

    def test_negative_returns_none(self):
        self.assertIsNone(_parse_retry_after("-1"))

    def test_garbage_returns_none(self):
        self.assertIsNone(_parse_retry_after("not-a-date"))

    def test_none_or_empty_returns_none(self):
        self.assertIsNone(_parse_retry_after(None))
        self.assertIsNone(_parse_retry_after(""))
        self.assertIsNone(_parse_retry_after("   "))

    def test_http_date(self):
        fixed_now = datetime(2026, 5, 4, 12, 0, 0, tzinfo=timezone.utc)
        future_value = "Mon, 04 May 2026 12:00:30 GMT"
        delay = _parse_retry_after(future_value, now=lambda: fixed_now)
        self.assertEqual(delay, 30.0)

    def test_http_date_in_past_returns_zero(self):
        fixed_now = datetime(2026, 5, 4, 12, 0, 0, tzinfo=timezone.utc)
        past_value = "Mon, 04 May 2026 11:59:00 GMT"
        delay = _parse_retry_after(past_value, now=lambda: fixed_now)
        self.assertEqual(delay, 0.0)


class CaseInsensitiveHeadersTests(unittest.TestCase):
    def setUp(self):
        self.headers = _CaseInsensitiveHeaders([
            ("Retry-After", "10"),
            ("Content-Type", "application/json"),
        ])

    def test_lookup_lowercase(self):
        self.assertEqual(self.headers["retry-after"], "10")

    def test_lookup_mixed_case(self):
        self.assertEqual(self.headers["RETRY-after"], "10")

    def test_get_with_default(self):
        self.assertEqual(self.headers.get("missing", "fallback"), "fallback")

    def test_iteration_preserves_original_case(self):
        self.assertEqual(set(self.headers), {"Retry-After", "Content-Type"})

    def test_membership_case_insensitive(self):
        self.assertIn("retry-after", self.headers)
        self.assertIn("Retry-After", self.headers)
        self.assertNotIn("missing", self.headers)

    def test_len(self):
        self.assertEqual(len(self.headers), 2)


if __name__ == "__main__":
    unittest.main()
