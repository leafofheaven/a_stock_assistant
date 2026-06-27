"""Export manual review template CSV from current candidates."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings
from core.jobs.export_selection_review import _load_selection_payload
from core.reporting.review_template_report import (
    build_console_summary,
    build_review_template,
    save_review_template,
)
from core.storage.duckdb_store import DuckDBStore


def export_review_template(
    *,
    top_n: int = 20,
    output_dir: Path | str = "reports",
    report_format: str = "csv",
    quiet: bool = False,
    settings: Settings | None = None,
    store: DuckDBStore | None = None,
) -> dict[str, Any]:
    """Export a CSV template for manual candidate review."""
    resolved_settings = settings or get_settings()
    resolved_store = store or DuckDBStore(resolved_settings.duckdb_path)
    payload = _load_selection_payload(resolved_settings, resolved_store, top_n, use_existing=False)
    template = build_review_template(payload["selection_df"], top_n=top_n)
    files = save_review_template(template, output_dir=output_dir, report_format=report_format)
    if not quiet:
        print(build_console_summary(files, len(template)))
    return {"status": "success", "row_count": int(len(template)), "generated_files": files, "template_df": template}


def main(argv: list[str] | None = None) -> None:
    """Parse command-line arguments and export review template."""
    parser = argparse.ArgumentParser(description="Export manual review template CSV.")
    parser.add_argument("--top-n", type=int, default=20, help="Number of candidates to include.")
    parser.add_argument("--output-dir", default="reports", help="Output directory.")
    parser.add_argument("--format", choices=["csv"], default="csv", help="Template format.")
    args = parser.parse_args(argv)
    export_review_template(top_n=args.top_n, output_dir=args.output_dir, report_format=args.format)


if __name__ == "__main__":
    main()
