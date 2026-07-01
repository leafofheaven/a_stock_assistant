from pathlib import Path

from core.factors.scoring import DEFAULT_WEIGHTS


ROOT = Path(__file__).resolve().parents[1]
GUIDE_PATH = ROOT / "docs" / "user_guides" / "core_logic_guide.md"


def test_core_logic_guide_exists() -> None:
    assert GUIDE_PATH.exists()


def test_core_logic_guide_mentions_stock_selection_concepts() -> None:
    content = GUIDE_PATH.read_text(encoding="utf-8")
    for phrase in [
        "total_score",
        "trend_score",
        "momentum_score",
        "liquidity_score",
        "fundamental_score",
        "volatility_score",
        "仅供个人研究使用",
        "不自动交易",
    ]:
        assert phrase in content


def test_core_logic_guide_mentions_elder_review_concepts() -> None:
    content = GUIDE_PATH.read_text(encoding="utf-8")
    for phrase in [
        "elder_score",
        "action_hint",
        "elder_reason",
        "weekly_trend",
        "daily_pullback",
        "不改变 `total_score`",
        "不代表买入优先级",
    ]:
        assert phrase in content


def test_core_logic_guide_mentions_excel_and_no_rank_policy() -> None:
    content = GUIDE_PATH.read_text(encoding="utf-8")
    assert "Excel 默认应避免导出 rank 字段" in content
    assert "序号只代表当前 Sheet 显示顺序" in content


def test_core_logic_guide_has_formula_details() -> None:
    content = GUIDE_PATH.read_text(encoding="utf-8")
    for phrase in [
        "total_score =",
        "0.30 * trend_score",
        "0.20 * momentum_score",
        "0.20 * liquidity_score",
        "0.15 * fundamental_score",
        "0.15 * volatility_score",
        "return_20d = close / close.shift(20) - 1",
        "avg_amount_20d = amount",
        "pe_score = 1 / pe",
        "volatility_20d",
        "min-max",
    ]:
        assert phrase in content


def test_core_logic_guide_has_source_locations() -> None:
    content = GUIDE_PATH.read_text(encoding="utf-8")
    for phrase in [
        "## 15. 源码位置索引",
        "core/jobs/run_daily_selection.py::_calculate_minimal_real_scores",
        "core/factors/scoring.py::calculate_total_score",
        "core/strategy/selector.py::select_top_stocks",
        "core/technical/elder.py::_classify_elder_state",
        "core/entry_zones/calculator.py::_entry_zone_record",
        "web/streamlit_app.py",
    ]:
        assert phrase in content


def test_core_logic_guide_has_elder_rule_table() -> None:
    content = GUIDE_PATH.read_text(encoding="utf-8")
    for phrase in [
        "### 7.1 埃尔德复核规则表",
        "EMA13",
        "EMA22",
        "MACD",
        "Force Index",
        "Bull Power",
        "Bear Power",
        "elder_score",
        "action_hint",
        "周线趋势改善：+35",
        "close_to_ema13_pct > 10",
        "close_to_ema22_pct > 12",
    ]:
        assert phrase in content


def test_core_logic_guide_has_entry_zone_calculation() -> None:
    content = GUIDE_PATH.read_text(encoding="utf-8")
    for phrase in [
        "### 8.1 买入区间计算口径",
        "entry_low",
        "entry_high",
        "stop_loss = min(base - buffer, entry_mid * 0.92)",
        "target_price",
        "reward_risk_ratio = reward / risk",
        "nearest_support",
        "nearest_resistance",
        "ATR14",
        "entry_zone_status",
        "启发式研究规则，不是交易信号",
    ]:
        assert phrase in content


def test_core_logic_guide_not_generic() -> None:
    content = GUIDE_PATH.read_text(encoding="utf-8")
    for forbidden in [
        "来自趋势相关指标。",
        "来自动量信息",
        "来自成交额、换手率等流动性信息。",
        "来自 ROE、PE、PB、营收增长等基础面或估值字段。",
        "来自波动率、回撤等风险相关指标。",
    ]:
        assert forbidden not in content
    assert "| `trend_score` | `daily_price.ts_code`, `trade_date`, `close` |" in content
    assert "标准化 / 处理方式" in content
    assert "源码位置" in content


def test_streamlit_has_core_logic_doc_download() -> None:
    source = (ROOT / "web" / "streamlit_app.py").read_text(encoding="utf-8")
    for phrase in [
        "CORE_LOGIC_GUIDE_PATH",
        "docs",
        "user_guides",
        "core_logic_guide.md",
        "核心说明文件",
        "下载核心逻辑说明",
        "A股选股辅助系统_核心逻辑说明.md",
        "st.download_button",
    ]:
        assert phrase in source
    assert "export_logic_docs" not in source
    assert "write_text" not in source


def test_no_algorithm_changes() -> None:
    assert DEFAULT_WEIGHTS == {
        "trend_score": 0.30,
        "momentum_score": 0.20,
        "liquidity_score": 0.20,
        "fundamental_score": 0.15,
        "volatility_score": 0.15,
    }
    selection_source = (ROOT / "core" / "strategy" / "selector.py").read_text(encoding="utf-8")
    elder_source = (ROOT / "core" / "technical" / "elder.py").read_text(encoding="utf-8")
    entry_zone_source = (ROOT / "core" / "entry_zones" / "calculator.py").read_text(encoding="utf-8")
    assert 'sort_values(["trade_date", "total_score", "ts_code"], ascending=[True, False, True])' in selection_source
    assert "does not replace or\n    modify ``total_score``" in elder_source
    assert "calculate_entry_zones_for_targets" in entry_zone_source
