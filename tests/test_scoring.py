"""Tests for factor scoring."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from core.factors.scoring import calculate_total_score, normalize_factor


def test_normalize_factor_higher_is_better() -> None:
    """Higher factor values should receive higher scores."""
    df = pd.DataFrame(
        {
            "trade_date": ["20240101", "20240101", "20240101"],
            "factor": [1.0, 2.0, 3.0],
        }
    )

    result = normalize_factor(df, "factor", higher_is_better=True)

    assert result.tolist() == [0.0, 50.0, 100.0]


def test_normalize_factor_lower_is_better() -> None:
    """Lower factor values should receive higher scores when requested."""
    df = pd.DataFrame(
        {
            "trade_date": ["20240101", "20240101", "20240101"],
            "factor": [1.0, 2.0, 3.0],
        }
    )

    result = normalize_factor(df, "factor", higher_is_better=False)

    assert result.tolist() == [100.0, 50.0, 0.0]


def test_normalize_factor_is_cross_sectional_by_trade_date() -> None:
    """Normalization should be independent for each trade_date."""
    df = pd.DataFrame(
        {
            "trade_date": ["20240101", "20240101", "20240102", "20240102"],
            "factor": [1.0, 3.0, 10.0, 30.0],
        }
    )

    result = normalize_factor(df, "factor")

    assert result.tolist() == [0.0, 100.0, 0.0, 100.0]


def test_normalize_factor_all_equal_values_get_neutral_score() -> None:
    """All equal cross-sectional values should not crash or divide by zero."""
    df = pd.DataFrame(
        {
            "trade_date": ["20240101", "20240101", "20240101"],
            "factor": [5.0, 5.0, 5.0],
        }
    )

    result = normalize_factor(df, "factor")

    assert result.tolist() == [50.0, 50.0, 50.0]


def test_normalize_factor_keeps_nan_and_handles_extreme_values() -> None:
    """NaN and infinite values should not crash normalization."""
    df = pd.DataFrame(
        {
            "trade_date": ["20240101", "20240101", "20240101", "20240101"],
            "factor": [1.0, pd.NA, float("inf"), 3.0],
        }
    )

    result = normalize_factor(df, "factor")

    assert result.iloc[0] == 0.0
    assert pd.isna(result.iloc[1])
    assert pd.isna(result.iloc[2])
    assert result.iloc[3] == 100.0


def test_calculate_total_score_uses_default_weights() -> None:
    """Default weights should produce the expected total score."""
    df = pd.DataFrame(
        {
            "ts_code": ["000001.SZ"],
            "trade_date": ["20240101"],
            "trend_score": [100.0],
            "momentum_score": [50.0],
            "liquidity_score": [50.0],
            "fundamental_score": [20.0],
            "volatility_score": [80.0],
        }
    )

    result = calculate_total_score(df)

    assert math.isclose(result.loc[0, "total_score"], 65.0)
    assert "trend_score" in result.columns


def test_calculate_total_score_supports_custom_weights() -> None:
    """Custom weights should be used when valid."""
    df = _score_df()
    weights = {
        "trend_score": 0.5,
        "momentum_score": 0.2,
        "liquidity_score": 0.1,
        "fundamental_score": 0.1,
        "volatility_score": 0.1,
    }

    result = calculate_total_score(df, weights=weights)

    assert math.isclose(result.loc[0, "total_score"], 69.0)


def test_calculate_total_score_handles_missing_components() -> None:
    """Missing score columns and values should be treated as 0 in total_score."""
    df = pd.DataFrame(
        {
            "ts_code": ["000001.SZ"],
            "trade_date": ["20240101"],
            "trend_score": [100.0],
            "momentum_score": [pd.NA],
        }
    )

    result = calculate_total_score(df)

    assert result.loc[0, "total_score"] == 30.0
    assert pd.isna(result.loc[0, "liquidity_score"])


def test_calculate_total_score_rejects_invalid_weights() -> None:
    """Invalid weights must be rejected when incomplete, negative, or not summing to 1."""
    with pytest.raises(ValueError, match="missing required columns"):
        calculate_total_score(_score_df(), weights={"trend_score": 1.0})

    invalid_sum = {
        "trend_score": 0.5,
        "momentum_score": 0.2,
        "liquidity_score": 0.2,
        "fundamental_score": 0.2,
        "volatility_score": 0.2,
    }
    with pytest.raises(ValueError, match="sum to 1.0"):
        calculate_total_score(_score_df(), weights=invalid_sum)

    negative = {
        "trend_score": 1.1,
        "momentum_score": -0.1,
        "liquidity_score": 0.0,
        "fundamental_score": 0.0,
        "volatility_score": 0.0,
    }
    with pytest.raises(ValueError, match="non-negative"):
        calculate_total_score(_score_df(), weights=negative)


def test_total_score_stays_in_reasonable_range() -> None:
    """Total score should be clipped to the 0-100 range."""
    result = calculate_total_score(
        pd.DataFrame(
            {
                "trend_score": [150.0],
                "momentum_score": [100.0],
                "liquidity_score": [100.0],
                "fundamental_score": [100.0],
                "volatility_score": [100.0],
            }
        )
    )

    assert 0 <= result.loc[0, "total_score"] <= 100


def _score_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts_code": ["000001.SZ"],
            "trade_date": ["20240101"],
            "trend_score": [80.0],
            "momentum_score": [70.0],
            "liquidity_score": [60.0],
            "fundamental_score": [50.0],
            "volatility_score": [40.0],
        }
    )
