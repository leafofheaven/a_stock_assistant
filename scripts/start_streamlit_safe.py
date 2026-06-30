"""Safely diagnose and start the local Streamlit dashboard."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.jobs.diagnose_streamlit_startup import build_console_summary, diagnose_streamlit_startup


def build_streamlit_command(port: int = 8501) -> list[str]:
    """Return the Streamlit launch command used by the safe starter."""
    return [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        "web/streamlit_app.py",
        "--server.port",
        str(port),
        "--server.fileWatcherType",
        "none",
    ]


def main(argv: list[str] | None = None) -> int:
    """Run startup checks, then launch Streamlit unless --dry-run is used."""
    parser = argparse.ArgumentParser(description="Diagnose and start Streamlit safely.")
    parser.add_argument("--port", type=int, default=8501, help="Streamlit port.")
    parser.add_argument("--dry-run", action="store_true", help="Print diagnostics and command without launching.")
    parser.add_argument("--kill-stale", action="store_true", help="Reserved flag; this script does not kill processes automatically.")
    args = parser.parse_args(argv)

    diagnostics = diagnose_streamlit_startup(port=args.port)
    print(build_console_summary(diagnostics))
    command = build_streamlit_command(args.port)
    print("- 启动命令:")
    print("  " + " ".join(command))
    if args.kill_stale:
        print("- --kill-stale 已收到，但当前脚本不会自动结束用户进程。请先手动确认占用进程。")
    if args.dry_run:
        return 0
    if diagnostics.get("port_in_use"):
        print("8501 端口已被占用，未启动新的 Streamlit。")
        return 2
    try:
        return subprocess.call(command, cwd=ROOT)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
