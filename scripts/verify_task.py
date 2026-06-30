"""Serial task verification runner for local workflows."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


VERIFY_COMMANDS = {
    "streamlit": [
        [sys.executable, "-m", "pytest"],
        [sys.executable, "scripts/check_project.py"],
        [sys.executable, "-m", "core.jobs.diagnose_streamlit_startup"],
    ],
    "task49": [
        [sys.executable, "-m", "pytest"],
        [sys.executable, "scripts/check_project.py"],
        [sys.executable, "scripts/check_task.py", "task49"],
        [sys.executable, "-m", "core.jobs.calculate_entry_zones"],
        [sys.executable, "-m", "core.jobs.diagnose_entry_zones"],
        [sys.executable, "-m", "core.jobs.export_entry_zone_report"],
        [sys.executable, "-m", "core.jobs.run_daily_workflow", "--doctor-before-run", "--skip-update", "--format", "all"],
    ],
}


def main(argv: list[str] | None = None) -> int:
    """Run verification commands serially."""
    parser = argparse.ArgumentParser(description="Run serial task verification commands.")
    parser.add_argument("target", choices=sorted(VERIFY_COMMANDS), help="Verification target.")
    args = parser.parse_args(argv)

    for command in VERIFY_COMMANDS[args.target]:
        print("$ " + " ".join(command), flush=True)
        result = subprocess.run(command, cwd=ROOT, check=False)
        if result.returncode != 0:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
