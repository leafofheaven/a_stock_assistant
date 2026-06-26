"""Factor normalization and total score calculations."""

from __future__ import annotations

import math

import pandas as pd

DEFAULT_WEIGHTS: dict[str, float] = {
    "trend_score": 0.30,
    "momentum_score": 0.20,
    "liquidity_score": 0.20,
    "fundamental_score": 0.15,
    "volatility_score": 0.15,
}


def normalize_factor(
    df: pd.DataFrame,
    factor_col: str,
    higher_is_better: bool = True,
) -> pd.Series:
    """Normalize one factor to 0-100 within each trade_date cross-section.

    Missing and non-numeric values are excluded from the cross-sectional min-max
    calculation and remain ``NaN`` in the returned series. Infinite values are
    also treated as missing. If all valid values on one ``trade_date`` are equal,
    they receive a neutral score of 50. The calculation groups only by the row's
    own ``trade_date`` and therefore does not use future dates.
    """
    if df.empty:
        return pd.Series(dtype="float64", index=df.index, name=f"{factor_col}_score")
    _require_columns(df, ["trade_date", factor_col])

    values = pd.to_numeric(df[factor_col], errors="coerce").replace([math.inf, -math.inf], pd.NA)

    def normalize_group(group: pd.Series) -> pd.Series:
        valid = group.dropna()
        scores = pd.Series(pd.NA, index=group.index, dtype="Float64")
        if valid.empty:
            return scores
        minimum = valid.min()
        maximum = valid.max()
        if minimum == maximum:
            scores.loc[valid.index] = 50.0
            return scores
        normalized = (valid - minimum) / (maximum - minimum) * 100
        if not higher_is_better:
            normalized = 100 - normalized
        scores.loc[valid.index] = normalized
        return scores

    score = values.groupby(df["trade_date"], group_keys=False).apply(normalize_group)
    score.name = f"{factor_col}_score"
    return score.astype("Float64")


def calculate_total_score(
    factor_df: pd.DataFrame,
    weights: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Calculate weighted total score from component score columns.

    By default the model uses trend, momentum, liquidity, fundamental, and
    volatility score columns with weights that sum to 1. Missing component score
    columns are added as ``NaN`` and missing values in existing component columns
    are filled with 0 for ``total_score`` calculation, so incomplete factor data
    does not crash the workflow. The original row order and all input columns are
    preserved, and only same-row component scores are used.
    """
    resolved_weights = weights or DEFAULT_WEIGHTS
    _validate_weights(resolved_weights)

    result = factor_df.copy()
    for column in resolved_weights:
        if column not in result.columns:
            result[column] = pd.NA
        result[column] = pd.to_numeric(result[column], errors="coerce").clip(lower=0, upper=100)

    total = pd.Series(0.0, index=result.index, dtype="float64")
    for column, weight in resolved_weights.items():
        total += result[column].fillna(0).astype(float) * weight

    result["total_score"] = total.clip(lower=0, upper=100)
    return result


def _validate_weights(weights: dict[str, float]) -> None:
    """Validate that weights cover all default score components and sum to 1."""
    expected_columns = set(DEFAULT_WEIGHTS)
    provided_columns = set(weights)
    missing_columns = expected_columns - provided_columns
    extra_columns = provided_columns - expected_columns
    if missing_columns:
        raise ValueError(f"weights are missing required columns: {', '.join(sorted(missing_columns))}")
    if extra_columns:
        raise ValueError(f"weights contain unsupported columns: {', '.join(sorted(extra_columns))}")
    if any(weight < 0 for weight in weights.values()):
        raise ValueError("weights must be non-negative")
    if not math.isclose(sum(weights.values()), 1.0, rel_tol=1e-9, abs_tol=1e-9):
        raise ValueError("weights must sum to 1.0")


def _require_columns(df: pd.DataFrame, columns: list[str]) -> None:
    """Raise a clear error when required columns are missing."""
    missing = [column for column in columns if column not in df.columns]
    if missing:
        raise ValueError(f"DataFrame is missing required columns: {', '.join(missing)}")
