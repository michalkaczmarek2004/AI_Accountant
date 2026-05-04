"""Fetch real Helius wallet data and write a readable HTML/CSV report.

Required:
    HELIUS_API_KEY environment variable or --api-key
    wallet address via --wallet or SOLANA_WALLET
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_accountant import SolanaDataFetcher, SolanaDataFetcherError  # noqa: E402
from ai_accountant.report import write_wallet_report  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch real Solana wallet activity through Helius and write a "
            "human-readable AI Accountant report."
        )
    )
    parser.add_argument(
        "--wallet",
        default=os.getenv("SOLANA_WALLET"),
        help="Solana wallet address. Can also be set with SOLANA_WALLET.",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("HELIUS_API_KEY"),
        help="Helius API key. Can also be set with HELIUS_API_KEY.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=2,
        help="Helius pages to fetch. Use 0 to fetch until Helius returns no more pages.",
    )
    parser.add_argument(
        "--output-dir",
        default="reports",
        help="Directory for the generated HTML and CSV files.",
    )
    parser.add_argument(
        "--max-transactions",
        type=int,
        default=250,
        help="Maximum number of newest transactions shown in the HTML table.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not args.api_key:
        print("Missing Helius API key. Set HELIUS_API_KEY or pass --api-key.", file=sys.stderr)
        return 2
    if not args.wallet:
        print("Missing wallet address. Set SOLANA_WALLET or pass --wallet.", file=sys.stderr)
        return 2
    if args.max_pages < 0:
        print("--max-pages must be 0 or greater.", file=sys.stderr)
        return 2
    if args.max_transactions <= 0:
        print("--max-transactions must be greater than 0.", file=sys.stderr)
        return 2

    max_pages = None if args.max_pages == 0 else args.max_pages
    page_label = "all available pages" if max_pages is None else f"{max_pages} page(s)"

    try:
        print(f"Fetching {page_label} for wallet {args.wallet}...")
        with SolanaDataFetcher(api_key=args.api_key) as fetcher:
            frame = fetcher.fetch_transactions_dataframe(args.wallet, max_pages=max_pages)

        paths = write_wallet_report(
            frame,
            args.wallet,
            args.output_dir,
            max_transactions=args.max_transactions,
        )
    except SolanaDataFetcherError as exc:
        print(f"AI Accountant error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"Could not write report files: {exc}", file=sys.stderr)
        return 1

    print(f"Transactions parsed: {len(frame)}")
    print(f"HTML report: {paths['html'].resolve()}")
    print(f"CSV export:   {paths['csv'].resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
