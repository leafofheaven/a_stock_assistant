"""Review template CSV generation helpers."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

TEMPLATE_COLUMNS = [
    "ts_code",
    "name",
    "selection_date",
    "total_score",
    "trend_score",
    "momentum_score",
    "liquidity_score",
    "volatility_score",
    "fundamental_score",
    "decision",
    "reason",
    "notes",
    "reviewer",
]


def build_review_template(selection_df: pd.DataFrame, top_n: int = 20) -> pd.DataFrame:
    """Return a CSV-ready review template from selected candidates."""
    if selection_df.empty:
        return pd.DataFrame(columns=TEMPLATE_COLUMNS)
    df = selection_df.copy().head(max(top_n, 0))
    if "selection_date" not in df.columns:
        df["selection_date"] = df.get("trade_date", pd.NA)
    df["decision"] = "pending"
    for column in ["reason", "notes", "reviewer"]:
        if column not in df.columns:
            df[column] = ""
    for column in TEMPLATE_COLUMNS:
        if column not in df.columns:
            df[column] = pd.NA
    return df[TEMPLATE_COLUMNS].reset_index(drop=True)


def save_review_template(
    template_df: pd.DataFrame,
    output_dir: Path | str = "reports",
    report_format: str = "csv",
) -> dict[str, str]:
    """Save review template files and return paths."""
    if report_format != "csv":
        raise ValueError("review template currently supports csv only")
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"review_template_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    template_df.to_csv(path, index=False, encoding="utf-8-sig")
    return {"csv": str(path)}


def build_console_summary(files: dict[str, str], row_count: int) -> str:
    """Return a concise review template export summary."""
    return "\n".join(
        [
            "人工复核模板导出摘要",
            f"- 模板行数: {row_count}",
            f"- 生成文件: {', '.join(files.values())}",
        ]
    )


def latest_review_template_path(output_dir: Path | str = "reports") -> Path | None:
    """Return latest review template CSV path if present."""
    directory = Path(output_dir)
    if not directory.exists():
        return None
    candidates = list(directory.glob("review_template_*.csv"))
    return max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None


def template_metadata(path: Path | str | None) -> dict[str, Any] | None:
    """Return compact metadata for a review template path."""
    if path is None:
        return None
    resolved = Path(path)
    if not resolved.exists():
        return None
    return {"path": str(resolved), "updated_at": datetime.fromtimestamp(resolved.stat().st_mtime).isoformat(timespec="seconds")}
