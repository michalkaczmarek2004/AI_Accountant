"""Write the readable HTML report using the existing synthetic demo dataset."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ai_accountant.report import write_wallet_report  # noqa: E402
from audit_demo import WALLET, build_dataframe  # noqa: E402


def main() -> int:
    frame = build_dataframe()
    paths = write_wallet_report(frame, WALLET, "reports")
    print(f"HTML report: {paths['html'].resolve()}")
    print(f"CSV export:   {paths['csv'].resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
