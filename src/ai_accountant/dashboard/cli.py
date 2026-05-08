"""argparse entry point: `dashboard {serve, fetch}`."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

DEFAULT_PORT = 8770
DEFAULT_HOST = "127.0.0.1"
DEFAULT_MAX_PAGES = 5
DEFAULT_CACHE_DIR = ".ai_accountant/wallets"


def main(argv: list[str] | None = None, *, fetcher_factory: Callable[[], Any] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "serve":
        return _run_serve(args)
    if args.command == "fetch":
        return _run_fetch(args, fetcher_factory=fetcher_factory)
    parser.print_help(sys.stderr)
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dashboard", description="AI Accountant local dashboard.")
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="Start the local Flask web UI.")
    serve.add_argument("--host", default=DEFAULT_HOST)
    serve.add_argument("--port", type=int, default=DEFAULT_PORT)
    serve.add_argument("--api-key", default=None)
    serve.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES)
    serve.add_argument("--cache-dir", default=DEFAULT_CACHE_DIR)

    fetch = sub.add_parser("fetch", help="Fetch one wallet into the cache without starting a server.")
    fetch.add_argument("address")
    fetch.add_argument("--api-key", default=None)
    fetch.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES)
    fetch.add_argument("--cache-dir", default=DEFAULT_CACHE_DIR)
    return parser


def _resolve_api_key(args: argparse.Namespace) -> str | None:
    return (args.api_key or os.environ.get("HELIUS_API_KEY") or "").strip() or None


def _ensure_cache_dir(path: Path) -> int | None:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"Cannot write to {path}: {exc}", file=sys.stderr)
        return 1
    return None


def _run_serve(args: argparse.Namespace) -> int:
    api_key = _resolve_api_key(args)
    if not api_key:
        print(
            "Missing Helius API key. Set HELIUS_API_KEY or pass --api-key.",
            file=sys.stderr,
        )
        return 2
    if args.max_pages < 0:
        print("--max-pages must be 0 or greater.", file=sys.stderr)
        return 2

    cache_dir = Path(args.cache_dir).resolve()
    rc = _ensure_cache_dir(cache_dir)
    if rc is not None:
        return rc

    if args.host != DEFAULT_HOST:
        print(
            "Binding to non-loopback exposes wallet activity to your local network.",
            file=sys.stderr,
        )

    try:
        from .server import create_app
    except ImportError as exc:
        print(
            "This feature requires the 'dashboard' extra. "
            "Install with: pip install ai-accountant[dashboard]",
            file=sys.stderr,
        )
        print(str(exc), file=sys.stderr)
        return 1

    app = create_app(
        helius_api_key=api_key,
        max_pages=args.max_pages,
        cache_root=cache_dir,
    )
    print(f"Open http://{args.host}:{args.port} in your browser. Ctrl-C to stop.")
    try:
        app.run(host=args.host, port=args.port, debug=False)
    except OSError as exc:
        print(f"Could not bind {args.host}:{args.port}: {exc}", file=sys.stderr)
        return 1
    return 0


def _run_fetch(args: argparse.Namespace, *, fetcher_factory: Callable[[], Any] | None = None) -> int:
    api_key = _resolve_api_key(args)
    if not api_key:
        print(
            "Missing Helius API key. Set HELIUS_API_KEY or pass --api-key.",
            file=sys.stderr,
        )
        return 2
    if args.max_pages < 0:
        print("--max-pages must be 0 or greater.", file=sys.stderr)
        return 2

    cache_dir = Path(args.cache_dir).resolve()
    rc = _ensure_cache_dir(cache_dir)
    if rc is not None:
        return rc

    from .fetcher import DashboardError, run_fetch

    try:
        df, meta = run_fetch(
            args.address,
            helius_api_key=api_key,
            max_pages=args.max_pages,
            cache_root=cache_dir,
            fetcher_factory=fetcher_factory,
        )
    except DashboardError as exc:
        print(f"Fetch failed [{exc.category}]: {exc.message}", file=sys.stderr)
        return 1
    print(f"Fetched {len(df)} transactions for {args.address} (pages={meta['pages_fetched']}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
