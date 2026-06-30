"""Safely diagnose and start the local Streamlit dashboard."""

from __future__ import annotations

import argparse
import socket
import subprocess
import sys
import time
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
        "--server.headless",
        "true",
        "--server.fileWatcherType",
        "none",
    ]


def build_streamlit_url(port: int = 8501) -> str:
    """Return the local dashboard URL opened by the safe starter."""
    return f"http://localhost:{int(port)}"


def build_open_command(port: int = 8501) -> list[str]:
    """Return the macOS open command used once after Streamlit is reachable."""
    return ["open", build_streamlit_url(port)]


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
    open_command = build_open_command(args.port)
    print("- 启动命令:")
    print("  " + " ".join(command))
    print("- 打开页面命令:")
    print("  " + " ".join(open_command))
    if args.kill_stale:
        print("- --kill-stale 已收到，但当前脚本不会自动结束用户进程。请先手动确认占用进程。")
    if args.dry_run:
        return 0
    if diagnostics.get("port_in_use"):
        print(f"{args.port} 端口已有服务运行，未启动新的 Streamlit，只打开已有页面一次。")
        _open_browser_once(args.port)
        return 0
    try:
        process = subprocess.Popen(command, cwd=ROOT)
        if _wait_for_port(args.port, timeout_seconds=30):
            _open_browser_once(args.port)
        else:
            print(f"等待 {args.port} 端口启动超时，请查看终端日志。")
        return process.wait()
    except KeyboardInterrupt:
        return 130


def _open_browser_once(port: int) -> None:
    """Open the dashboard URL once from the launcher side."""
    subprocess.run(build_open_command(port), check=False)


def _wait_for_port(port: int, timeout_seconds: int = 30) -> bool:
    """Wait until localhost:port accepts TCP connections."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("localhost", int(port)), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.5)
    return False


if __name__ == "__main__":
    raise SystemExit(main())
