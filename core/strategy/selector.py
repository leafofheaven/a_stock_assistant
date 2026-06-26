"""Stock selection strategy helpers."""

from __future__ import annotations

import pandas as pd

OUTPUT_COLUMNS = [
    "trade_date",
    "rank",
    "ts_code",
    "name",
    "industry",
    "trend_score",
    "momentum_score",
    "liquidity_score",
    "fundamental_score",
    "volatility_score",
    "total_score",
    "select_reason",
    "risk_note",
]


def select_top_stocks(scored_df: pd.DataFrame, top_n: int = 30) -> pd.DataFrame:
    """Select top scoring stocks for each trade date.

    Rows with missing ``total_score`` are excluded. Selection is grouped by
    ``trade_date`` and sorted descending by ``total_score`` within each date.
    Missing descriptive or component score columns are added as ``NA`` so partial
    upstream data does not crash the strategy layer.
    """
    if top_n <= 0 or scored_df.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    _require_columns(scored_df, ["trade_date", "ts_code", "total_score"])

    df = scored_df.copy()
    _ensure_optional_columns(df)
    df["total_score"] = pd.to_numeric(df["total_score"], errors="coerce")
    df = df.dropna(subset=["total_score"])
    if df.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    df = df.sort_values(["trade_date", "total_score", "ts_code"], ascending=[True, False, True])
    selected = df.groupby("trade_date", group_keys=False).head(top_n).copy()
    selected["rank"] = selected.groupby("trade_date").cumcount() + 1
    selected["select_reason"] = selected.apply(_build_select_reason, axis=1)
    selected["risk_note"] = selected.apply(_build_risk_note, axis=1)
    return selected[OUTPUT_COLUMNS].reset_index(drop=True)


def _ensure_optional_columns(df: pd.DataFrame) -> None:
    """Add optional output columns when upstream data is partial."""
    for column in OUTPUT_COLUMNS:
        if column not in df.columns and column not in {"rank", "select_reason", "risk_note"}:
            df[column] = pd.NA


def _build_select_reason(row: pd.Series) -> str:
    """Create a short human-readable selection reason."""
    highlights: list[str] = [f"综合分 {row['total_score']:.2f}"]
    score_labels = [
        ("trend_score", "趋势"),
        ("momentum_score", "动量"),
        ("liquidity_score", "流动性"),
        ("fundamental_score", "基本面"),
        ("volatility_score", "风险"),
    ]
    for column, label in score_labels:
        value = pd.to_numeric(pd.Series([row.get(column)]), errors="coerce").iloc[0]
        if pd.notna(value) and value >= 70:
            highlights.append(f"{label}较强")
    return "；".join(highlights)


def _build_risk_note(row: pd.Series) -> str:
    """Create a concise risk note from available score components."""
    notes: list[str] = []
    volatility_score = pd.to_numeric(pd.Series([row.get("volatility_score")]), errors="coerce").iloc[0]
    liquidity_score = pd.to_numeric(pd.Series([row.get("liquidity_score")]), errors="coerce").iloc[0]
    if pd.notna(volatility_score) and volatility_score < 40:
        notes.append("波动风险较高")
    if pd.notna(liquidity_score) and liquidity_score < 40:
        notes.append("流动性偏弱")
    if not notes:
        notes.append("需结合基本面与市场环境复核")
    return "；".join(notes)


def _require_columns(df: pd.DataFrame, columns: list[str]) -> None:
    """Raise a clear error when required columns are missing."""
    missing = [column for column in columns if column not in df.columns]
    if missing:
        raise ValueError(f"scored_df is missing required columns: {', '.join(missing)}")
