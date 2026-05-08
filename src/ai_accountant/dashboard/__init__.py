"""Local web dashboard for real Solana wallet activity (parser-level views)."""

from __future__ import annotations

from .fetcher import DashboardError, RefreshLocked, run_fetch

__all__ = ["DashboardError", "RefreshLocked", "run_fetch"]
