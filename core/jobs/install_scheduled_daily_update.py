"""Install a user LaunchAgent for scheduled daily updates."""

from __future__ import annotations

import argparse
import getpass
import plistlib
import subprocess
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LABEL = "com.a_stock_assistant.scheduled_daily_update"


def build_launchd_plist(
    *,
    label: str = DEFAULT_LABEL,
    scheduled_time: str = "18:00",
    python_path: str | Path | None = None,
    project_dir: str | Path = PROJECT_ROOT,
    status_path: str | Path | None = None,
) -> dict[str, Any]:
    """Build a LaunchAgent plist dictionary."""
    hour, minute = [int(part) for part in scheduled_time.split(":", 1)]
    py = str(python_path or PROJECT_ROOT / ".venv" / "bin" / "python")
    project = Path(project_dir)
    args = [
        py,
        "-m",
        "core.jobs.run_scheduled_daily_update",
        "--catch-up",
        "--scheduled-time",
        scheduled_time,
        "--update-mode",
        "daily_incremental",
    ]
    if status_path:
        args.extend(["--status-path", str(status_path)])
    log_dir = project / "data" / "runtime"
    return {
        "Label": label,
        "ProgramArguments": args,
        "WorkingDirectory": str(project),
        "StartCalendarInterval": {"Hour": hour, "Minute": minute},
        "StandardOutPath": str(log_dir / "scheduled_daily_update.out.log"),
        "StandardErrorPath": str(log_dir / "scheduled_daily_update.err.log"),
        "RunAtLoad": False,
    }


def install_scheduled_daily_update(
    *,
    scheduled_time: str = "18:00",
    label: str = DEFAULT_LABEL,
    python_path: str | Path | None = None,
    project_dir: str | Path = PROJECT_ROOT,
    plist_dir: str | Path | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    """Install a user LaunchAgent plist, or preview it in dry-run mode."""
    target_dir = Path(plist_dir) if plist_dir else Path.home() / "Library" / "LaunchAgents"
    target_path = target_dir / f"{label}.plist"
    plist = build_launchd_plist(label=label, scheduled_time=scheduled_time, python_path=python_path, project_dir=project_dir)
    payload = plistlib.dumps(plist).decode("utf-8")
    if dry_run:
        return {"status": "dry_run", "plist_path": str(target_path), "plist": payload}
    target_dir.mkdir(parents=True, exist_ok=True)
    if target_path.exists() and not force:
        return {"status": "failed", "plist_path": str(target_path), "message": "plist 已存在；使用 --force 覆盖。"}
    target_path.write_bytes(plistlib.dumps(plist))
    domain = f"gui/{_uid()}"
    subprocess.run(["launchctl", "bootout", domain, str(target_path)], check=False, capture_output=True, text=True)
    bootstrap = subprocess.run(["launchctl", "bootstrap", domain, str(target_path)], check=False, capture_output=True, text=True)
    if bootstrap.returncode != 0:
        return {"status": "failed", "plist_path": str(target_path), "message": bootstrap.stderr[:300]}
    subprocess.run(["launchctl", "enable", f"{domain}/{label}"], check=False, capture_output=True, text=True)
    return {"status": "success", "plist_path": str(target_path), "message": "LaunchAgent installed."}


def _uid() -> int:
    try:
        return int(subprocess.check_output(["id", "-u"], text=True).strip())
    except Exception:
        return 501 if getpass.getuser() else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install scheduled daily update LaunchAgent.")
    parser.add_argument("--time", default="18:00")
    parser.add_argument("--label", default=DEFAULT_LABEL)
    parser.add_argument("--python-path", default=str(PROJECT_ROOT / ".venv" / "bin" / "python"))
    parser.add_argument("--project-dir", default=str(PROJECT_ROOT))
    parser.add_argument("--plist-dir", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    result = install_scheduled_daily_update(
        scheduled_time=args.time,
        label=args.label,
        python_path=args.python_path,
        project_dir=args.project_dir,
        plist_dir=args.plist_dir,
        dry_run=args.dry_run,
        force=args.force,
    )
    print("自动更新 LaunchAgent 安装")
    print(f"- 状态: {result.get('status')}")
    print(f"- plist: {result.get('plist_path')}")
    if result.get("plist"):
        print(result["plist"])
    if result.get("message"):
        print(f"- 说明: {result['message']}")
    return 0 if result.get("status") in {"success", "dry_run"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
