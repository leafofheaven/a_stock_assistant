"""Tests for Task 34 Mac launcher and local console documentation."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_mac_launcher_files_exist() -> None:
    """Mac launcher and README should exist."""
    assert (ROOT / "scripts/mac/A股选股助手.command").exists()
    assert (ROOT / "scripts/mac/README.md").exists()


def test_mac_launcher_starts_streamlit_and_opens_localhost() -> None:
    """Launcher should delegate to the safe starter to avoid duplicate browser windows."""
    source = _read("scripts/mac/A股选股助手.command")

    assert 'PROJECT_DIR="/Users/wanghao/Documents/股票"' in source
    assert "source .venv/bin/activate" in source
    assert "python scripts/start_streamlit_safe.py --port 8501" in source
    assert 'open "$APP_URL"' not in source
    assert "streamlit run web/streamlit_app.py" not in source
    assert "http://localhost:8501" in source


def test_docs_describe_local_console_and_mac_launcher() -> None:
    """README and docs should explain the local console workflow."""
    combined = "\n".join(
        [
            _read("README.md"),
            _read("docs/v0_1_handbook.md"),
            _read("docs/commands_reference.md"),
            _read("docs/daily_workflow.md"),
            _read("docs/troubleshooting.md"),
            _read("scripts/mac/README.md"),
        ]
    )
    for phrase in [
        "参数设置",
        "本地控制台",
        "Mac 双击启动器",
        "Chrome",
        "localhost:8501",
        "不做完整原生 Swift App",
        "不做菜单栏常驻",
        "不做自动后台更新",
        "不做 dmg",
        "不做云同步",
    ]:
        assert phrase in combined
