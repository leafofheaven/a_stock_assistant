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
