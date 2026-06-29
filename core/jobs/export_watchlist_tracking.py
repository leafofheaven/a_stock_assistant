"""Compatibility CLI for exporting watchlist tracking reports."""

from __future__ import annotations

from core.jobs.export_watchlist_tracking_report import export_watchlist_tracking_report, main

__all__ = ["export_watchlist_tracking_report", "main"]


if __name__ == "__main__":
    main()
