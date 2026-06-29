"""Run Elder-style technical review for current selected candidates."""

from __future__ import annotations

import argparse
from typing import Any

import pandas as pd

from app.config import Settings, get_settings
from core.jobs.diagnose_factors import diagnose_factors
from core.sample_data import get_sample_dashboard_data
from core.storage.duckdb_store import DuckDBStore, DuckDBStoreError
from core.technical.elder import ELDER_REVIEW_COLUMNS, build_elder_review


def run_elder_review(
    settings: Settings | None = None,
    store: DuckDBStore | None = None,
    top_n: int = 10,
    use_sample: bool = True,
) -> dict[str, Any]:
    """Run a secondary Elder technical review from local data only.

    The review does not fetch external data, write trading instructions, or
    change the existing ``total_score`` formula/order. It only appends
    ``elder_score``, ``action_hint`` and Chinese review reasons to the current
    candidate rows.
    """
    resolved_settings = settings or get_settings()
    resolved_store = store or DuckDBStore(resolved_settings.duckdb_path)
    payload = _load_review_payload(resolved_settings, resolved_store, top_n, use_sample)
    review_df = build_elder_review(payload["selection_df"], payload["price_df"])
    return {
        "data_source": payload["data_source"],
        "latest_price_date": _latest_date(payload["price_df"], "trade_date"),
        "candidate_count": int(len(payload["selection_df"])),
        "review_count": int(len(review_df)),
        "elder_review_df": review_df,
        "notes": [
            "elder_score 是技术状态 / 节奏复核分，不覆盖 total_score，也不代表买入优先级。",
            "不自动交易，不接券商；需要人工复核。",
        ],
    }


def main() -> None:
    """Run the Elder review command and print a text or Markdown summary."""
    parser = argparse.ArgumentParser(description="Run Elder-style technical review for selected candidates.")
    parser.add_argument("--format", choices=["text", "markdown"], default="text")
    parser.add_argument("--top-n", type=int, default=10)
    args = parser.parse_args()

    result = run_elder_review(top_n=args.top_n)
    if args.format == "markdown":
        print(render_elder_review_markdown(result))
    else:
        print("埃尔德技术复核摘要")
        print(f"- 数据来源: {result['data_source']}")
        print(f"- 最新行情日期: {result.get('latest_price_date') or '暂无'}")
        print(f"- 候选股票数量: {result['candidate_count']}")
        print(f"- 复核股票数量: {result['review_count']}")
        for note in result["notes"]:
            print(f"- {note}")
        review_df = result["elder_review_df"]
        if review_df.empty:
            print("- 暂无复核结果。")
            return
        print("- 复核结果:")
        for item in review_df.to_dict("records"):
            print(
                f"  {item.get('rank')}. {item.get('ts_code')} {item.get('name')} "
                f"total_score={_fmt(item.get('total_score'))} elder_score={_fmt(item.get('elder_score'))} "
                f"action_hint={item.get('action_hint')} reason={item.get('elder_reason')}"
            )


def render_elder_review_markdown(result: dict[str, Any]) -> str:
    """Render an Elder review result as Markdown."""
    lines = [
        "# 埃尔德技术复核",
        "",
        f"- 数据来源: {result['data_source']}",
        f"- 最新行情日期: {result.get('latest_price_date') or '暂无'}",
        f"- 候选股票数量: {result['candidate_count']}",
        f"- 复核股票数量: {result['review_count']}",
        "- 说明: elder_score 是技术状态 / 节奏复核分，不覆盖 total_score，也不代表买入优先级。",
        "- 个人研究工具，结果需自行复核。",
        "",
    ]
    review_df = result["elder_review_df"]
    if review_df.empty:
        lines.append("暂无复核结果。")
        return "\n".join(lines)
    columns = [
        "rank",
        "ts_code",
        "name",
        "total_score",
        "elder_score",
        "review_action",
        "action_hint",
        "weekly_trend",
        "daily_pullback",
        "force_signal",
        "elder_ray_signal",
        "elder_reason",
    ]
    for column in columns:
        if column not in review_df.columns:
            review_df[column] = ""
    lines.extend(
        [
            "| rank | ts_code | name | total_score | elder_score | 操作建议 | action_hint | weekly | pullback | force | elder_ray | reason |",
            "| --- | --- | --- | ---: | ---: | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for item in review_df[columns].to_dict("records"):
        lines.append(
            "| {rank} | {ts_code} | {name} | {total_score} | {elder_score} | {review_action} | {action_hint} | {weekly_trend} | {daily_pullback} | {force_signal} | {elder_ray_signal} | {reason} |".format(
                rank=item.get("rank") or "",
                ts_code=item.get("ts_code") or "",
                name=item.get("name") or "",
                total_score=_fmt(item.get("total_score")),
                elder_score=_fmt(item.get("elder_score")),
                review_action=item.get("review_action") or "",
                action_hint=item.get("action_hint") or "",
                weekly_trend=item.get("weekly_trend") or "",
                daily_pullback=item.get("daily_pullback") or "",
                force_signal=item.get("force_signal") or "",
                elder_ray_signal=item.get("elder_ray_signal") or "",
                reason=item.get("elder_reason") or "",
            )
        )
    return "\n".join(lines)


def _load_review_payload(
    settings: Settings,
    store: DuckDBStore,
    top_n: int,
    use_sample: bool,
) -> dict[str, Any]:
    """Load local candidate and price frames for Elder review."""
    if settings.data_provider == "sample":
        return _sample_payload(top_n)
    if store.db_path.exists():
        try:
            price_df = store.read_table("daily_price")
            strategy_result = store.read_table("strategy_result")
        except DuckDBStoreError:
            price_df = pd.DataFrame()
            strategy_result = pd.DataFrame()
        if not strategy_result.empty and not price_df.empty:
            selection = _latest_selection(strategy_result, top_n)
            return {
                "data_source": f"{settings.data_provider} 本地 DuckDB 真实数据",
                "selection_df": selection,
                "price_df": price_df,
            }
        diagnostic = diagnose_factors(settings=settings, store=store, use_sample=False)
        selected = diagnostic.get("selected_df", pd.DataFrame())
        if not selected.empty and not price_df.empty:
            return {
                "data_source": f"{settings.data_provider} 本地 DuckDB 真实数据",
                "selection_df": selected.head(top_n).copy(),
                "price_df": price_df,
            }
    if use_sample:
        payload = _sample_payload(top_n)
        payload["data_source"] = "sample 数据（真实数据不足，已回退演示数据）"
        return payload
    return {"data_source": "无数据", "selection_df": pd.DataFrame(), "price_df": pd.DataFrame()}


def _sample_payload(top_n: int) -> dict[str, Any]:
    data = get_sample_dashboard_data()
    return {
        "data_source": "sample 数据（演示）",
        "selection_df": data.get("selection", pd.DataFrame()).head(top_n).copy(),
        "price_df": data.get("price", pd.DataFrame()).copy(),
    }


def _latest_selection(selection_df: pd.DataFrame, top_n: int) -> pd.DataFrame:
    if selection_df.empty:
        return selection_df
    result = selection_df.copy()
    if "trade_date" in result.columns:
        latest = str(result["trade_date"].dropna().astype(str).max())
        result = result[result["trade_date"].astype(str) == latest]
    if "rank" in result.columns:
        result = result.sort_values("rank")
    return result.head(top_n).reset_index(drop=True)


def _latest_date(df: pd.DataFrame, column: str) -> str | None:
    if df.empty or column not in df.columns:
        return None
    values = df[column].dropna().astype(str)
    return str(values.max()) if not values.empty else None


def _fmt(value: Any) -> str:
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return "暂无"
    if pd.isna(converted):
        return "暂无"
    return f"{converted:.2f}"


if __name__ == "__main__":
    main()
