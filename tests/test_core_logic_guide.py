from pathlib import Path

from core.factors.scoring import DEFAULT_WEIGHTS


ROOT = Path(__file__).resolve().parents[1]
GUIDE_PATH = ROOT / "docs" / "user_guides" / "core_logic_guide.md"


def test_core_logic_guide_exists() -> None:
    assert GUIDE_PATH.exists()


def test_core_logic_guide_mentions_stock_selection_concepts() -> None:
    content = GUIDE_PATH.read_text(encoding="utf-8")
    for phrase in [
        "综合分（total_score）",
        "趋势分（trend_score）",
        "动量分（momentum_score）",
        "流动性分（liquidity_score）",
        "基本面分（fundamental_score）",
        "波动分（volatility_score）",
        "仅供个人研究使用",
        "不自动交易",
    ]:
        assert phrase in content


def test_core_logic_guide_mentions_elder_review_concepts() -> None:
    content = GUIDE_PATH.read_text(encoding="utf-8")
    for phrase in [
        "埃尔德分（elder_score）",
        "操作提示（action_hint）",
        "复核原因（elder_reason）",
        "周线趋势（weekly_trend）",
        "日线回调（daily_pullback）",
        "强力指数（Force Index）",
        "埃尔德射线（Elder-ray）",
        "不覆盖综合分（total_score）",
        "不代表买入优先级",
    ]:
        assert phrase in content


def test_core_logic_guide_mentions_excel_and_no_rank_policy() -> None:
    content = GUIDE_PATH.read_text(encoding="utf-8")
    assert "Excel 默认应避免导出排名字段（rank）" in content
    assert "序号只代表当前 Sheet 显示顺序" in content


def test_core_logic_guide_has_formula_details() -> None:
    content = GUIDE_PATH.read_text(encoding="utf-8")
    for phrase in [
        "total_score =",
        "0.30 * 趋势分（trend_score）",
        "0.20 * 动量分（momentum_score）",
        "0.20 * 流动性分（liquidity_score）",
        "0.15 * 基本面分（fundamental_score）",
        "0.15 * 波动分（volatility_score）",
        "20日收益率（return_20d）= 当前收盘价 / 20 个交易日前收盘价 - 1",
        "20日平均成交额（avg_amount_20d）= 最近 20 个交易日成交额均值",
        "市盈率倒数指标（pe_score）= 1 / 市盈率（pe）",
        "20日波动率（volatility_20d）",
        "score = (value - min_value) / (max_value - min_value) * 100",
    ]:
        assert phrase in content


def test_core_logic_guide_omits_source_location_index() -> None:
    content = GUIDE_PATH.read_text(encoding="utf-8")
    assert "源码位置索引" not in content
    assert "core/jobs/" not in content
    assert "core/factors/" not in content
    assert "::" not in content


def test_core_logic_guide_has_elder_rule_table() -> None:
    content = GUIDE_PATH.read_text(encoding="utf-8")
    for phrase in [
        "## 8. 埃尔德复核计算公式",
        "EMA13",
        "EMA22",
        "MACD",
        "强力指数（Force Index）",
        "多头力量（Bull Power / bull_power）",
        "空头力量（Bear Power / bear_power）",
        "埃尔德分（elder_score）",
        "操作提示（action_hint）",
        "周线趋势改善：+35",
        "相对EMA13距离（close_to_ema13_pct）> 10",
        "相对EMA22距离（close_to_ema22_pct）> 12",
    ]:
        assert phrase in content


def test_core_logic_guide_has_entry_zone_calculation() -> None:
    content = GUIDE_PATH.read_text(encoding="utf-8")
    for phrase in [
        "## 9. 买入区间计算公式",
        "买入区间下限（entry_low）",
        "买入区间上限（entry_high）",
        "止损价（stop_loss）= min",
        "目标价（target_price）",
        "盈亏比（reward_risk_ratio）= 收益距离（reward） / 风险距离（risk）",
        "最近支撑位（nearest_support）",
        "最近阻力位（nearest_resistance）",
        "ATR14",
        "买入区间状态（entry_zone_status）",
        "启发式研究计划参考，不是买入卖出指令",
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
    assert "计算目的：衡量股票过去约 20 个交易日的价格趋势强弱。" in content
    assert "输入数据：" in content
    assert "缺失处理：" in content
    assert "用户如何理解：" in content


def test_core_logic_guide_has_user_formula_usage_section() -> None:
    content = GUIDE_PATH.read_text(encoding="utf-8")
    assert "## 10. 普通用户如何使用这些公式" in content
    for phrase in [
        "先用综合分（total_score）缩小候选范围",
        "看趋势分（trend_score） / 动量分（momentum_score）",
        "看流动性分（liquidity_score）",
        "看基本面分（fundamental_score）",
        "看波动分（volatility_score）",
        "看埃尔德复核",
        "看买入区间",
        "不使用排名字段（rank）或序号作为买入优先级",
    ]:
        assert phrase in content


def test_core_logic_guide_defines_chinese_first_field_naming() -> None:
    content = GUIDE_PATH.read_text(encoding="utf-8")
    assert "中文名称（英文名）" in content
    for phrase in [
        "综合分（total_score）",
        "趋势分（trend_score）",
        "动量分（momentum_score）",
        "流动性分（liquidity_score）",
        "基本面分（fundamental_score）",
        "波动分（volatility_score）",
        "埃尔德分（elder_score）",
        "操作提示（action_hint）",
        "买入区间下限（entry_low）",
        "止损价（stop_loss）",
        "盈亏比（reward_risk_ratio）",
    ]:
        assert phrase in content


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
