"""Uninstall the scheduled daily update LaunchAgent."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from core.jobs.install_scheduled_daily_update import DEFAULT_LABEL, _uid


def uninstall_scheduled_daily_update(
    *,
    label: str = DEFAULT_LABEL,
    plist_dir: str | Path | None = None,
    dry_run: bool = False,
) -> dict[str, str]:
    """Unload and remove the user LaunchAgent plist."""
    target_dir = Path(plist_dir) if plist_dir else Path.home() / "Library" / "LaunchAgents"
    target_path = target_dir / f"{label}.plist"
    if dry_run:
        return {"status": "dry_run", "plist_path": str(target_path), "message": "dry-run 不修改系统。"}
    domain = f"gui/{_uid()}"
    subprocess.run(["launchctl", "bootout", domain, str(target_path)], check=False, capture_output=True, text=True)
    if target_path.exists():
        target_path.unlink()
    return {"status": "success", "plist_path": str(target_path), "message": "LaunchAgent removed."}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Uninstall scheduled daily update LaunchAgent.")
    parser.add_argument("--label", default=DEFAULT_LABEL)
    parser.add_argument("--plist-dir", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    result = uninstall_scheduled_daily_update(label=args.label, plist_dir=args.plist_dir, dry_run=args.dry_run)
    print("自动更新 LaunchAgent 卸载")
    print(f"- 状态: {result.get('status')}")
    print(f"- plist: {result.get('plist_path')}")
    print(f"- 说明: {result.get('message')}")
    return 0 if result.get("status") in {"success", "dry_run"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
