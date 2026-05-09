"""Launch the AI Accountant local dashboard and open it in the browser.

Usage:
    python examples/open_dashboard.py
    python examples/open_dashboard.py --api-key YOUR_KEY --port 8770
    python examples/open_dashboard.py --wallet 86xCnPeV...  # pre-fetch on startup

Environment variables:
    HELIUS_API_KEY   Helius Enhanced API key (required unless --api-key is passed)
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

HOST = "127.0.0.1"
DEFAULT_PORT = 8770
DEFAULT_MAX_PAGES = 5
DEFAULT_CACHE_DIR = ROOT / ".ai_accountant" / "wallets"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Start the AI Accountant dashboard.")
    p.add_argument("--api-key", default=None, help="Helius API key (or set HELIUS_API_KEY)")
    p.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Port (default {DEFAULT_PORT})")
    p.add_argument(
        "--max-pages",
        type=int,
        default=DEFAULT_MAX_PAGES,
        help=f"Max Helius pages per fetch (default {DEFAULT_MAX_PAGES}, 0 = unlimited)",
    )
    p.add_argument(
        "--cache-dir", type=Path, default=DEFAULT_CACHE_DIR, help="Directory for cached wallet data"
    )
    p.add_argument(
        "--wallet",
        default=None,
        help="Optional wallet address to pre-fetch before opening the browser",
    )
    p.add_argument(
        "--no-browser", action="store_true", help="Start server without opening the browser"
    )
    return p.parse_args()


def _resolve_api_key(args: argparse.Namespace) -> str:
    key = (args.api_key or os.environ.get("HELIUS_API_KEY") or "").strip()
    if not key:
        print(
            "Error: Helius API key required.\n"
            "  Set HELIUS_API_KEY in your environment, or pass --api-key KEY.",
            file=sys.stderr,
        )
        sys.exit(2)
    return key


def _open_browser(url: str, delay: float = 1.2) -> None:
    def _open():
        time.sleep(delay)
        webbrowser.open(url)

    t = threading.Thread(target=_open, daemon=True)
    t.start()


def main() -> None:
    args = _parse_args()
    api_key = _resolve_api_key(args)

    try:
        from ai_accountant.dashboard.server import create_app
    except ImportError:
        print(
            'Error: dashboard dependencies not installed.\n  Run: pip install -e ".[dashboard]"',
            file=sys.stderr,
        )
        sys.exit(1)

    cache_dir = Path(args.cache_dir).resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)

    app = create_app(
        helius_api_key=api_key,
        max_pages=args.max_pages if args.max_pages > 0 else None,
        cache_root=cache_dir,
    )

    if args.wallet:
        from ai_accountant.dashboard.fetcher import DashboardError, run_fetch

        print(f"Pre-fetching wallet {args.wallet} …")
        try:
            df, meta = run_fetch(
                args.wallet,
                helius_api_key=api_key,
                max_pages=args.max_pages if args.max_pages > 0 else None,
                cache_root=cache_dir,
            )
            print(f"  Cached {meta['row_count']} transactions.")
        except DashboardError as exc:
            print(f"  Warning: pre-fetch failed [{exc.category}]: {exc.message}", file=sys.stderr)

    url = f"http://{HOST}:{args.port}"
    print(f"Dashboard running at {url}  (Ctrl-C to stop)")

    if not args.no_browser:
        _open_browser(url)

    app.run(host=HOST, port=args.port, debug=False)


if __name__ == "__main__":
    main()
