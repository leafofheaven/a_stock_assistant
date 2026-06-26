"""Skeleton tests for factor modules."""

from __future__ import annotations


def test_factor_modules_import() -> None:
    """Factor placeholder modules should be importable."""
    import core.factors.fundamental  # noqa: F401
    import core.factors.liquidity  # noqa: F401
    import core.factors.momentum  # noqa: F401
    import core.factors.trend  # noqa: F401
    import core.factors.volatility  # noqa: F401
