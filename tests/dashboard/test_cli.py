from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ai_accountant import DATAFRAME_COLUMNS

WALLET = "86xCnPeV69n6t3DnyGvkKobf9FdN2H9oiVDdaMpo2MMY"


class CliHelpTests(unittest.TestCase):
    def test_help_exits_zero(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "ai_accountant.dashboard.cli", "--help"],
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "PYTHONPATH": "src"},
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("serve", result.stdout)
        self.assertIn("fetch", result.stdout)

    def test_serve_help_exits_zero(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "ai_accountant.dashboard.cli", "serve", "--help"],
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "PYTHONPATH": "src"},
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("--max-pages", result.stdout)


class CliMissingKeyTests(unittest.TestCase):
    def test_serve_without_api_key_exits_2(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "HELIUS_API_KEY"}
        env["PYTHONPATH"] = "src"
        result = subprocess.run(
            [sys.executable, "-m", "ai_accountant.dashboard.cli", "serve"],
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("HELIUS_API_KEY", result.stderr)


class CliFetchProgrammaticTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(self.id().replace(".", "_") + "_tmp")
        self.tmp.mkdir(exist_ok=True)
        self.addCleanup(self._cleanup)

    def _cleanup(self) -> None:
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_fetch_writes_cache(self) -> None:
        from ai_accountant.dashboard import cli

        class _FakeFetcher:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *_a):
                return None

            def fetch_transactions_dataframe(self_inner, _wallet, *, max_pages=None, **_kw):
                return pd.DataFrame(columns=DATAFRAME_COLUMNS)

        rc = cli.main(
            [
                "fetch",
                WALLET,
                "--api-key",
                "k",
                "--max-pages",
                "1",
                "--cache-dir",
                str(self.tmp),
            ],
            fetcher_factory=lambda: _FakeFetcher(),
        )
        self.assertEqual(rc, 0)
        self.assertTrue((self.tmp / WALLET / "transactions.pkl").exists())

    def test_fetch_with_negative_max_pages_exits_2(self) -> None:
        from ai_accountant.dashboard import cli

        rc = cli.main(
            [
                "fetch",
                WALLET,
                "--api-key",
                "k",
                "--max-pages",
                "-1",
                "--cache-dir",
                str(self.tmp),
            ]
        )
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
