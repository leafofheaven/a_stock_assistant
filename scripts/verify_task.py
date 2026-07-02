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
    "task50": [
        [sys.executable, "-m", "pytest"],
        [sys.executable, "scripts/check_project.py"],
        [sys.executable, "scripts/check_task.py", "task50"],
        [sys.executable, "-m", "core.jobs.generate_external_position_template", "--output-dir", "/tmp/a_stock_assistant_task50_templates"],
        [sys.executable, "-m", "core.jobs.diagnose_external_positions"],
        [sys.executable, "-m", "core.jobs.export_external_position_report"],
        [sys.executable, "-m", "core.jobs.run_daily_workflow", "--doctor-before-run", "--skip-update", "--format", "all"],
        [sys.executable, "-m", "core.jobs.clean_generated_reports", "--force"],
    ],
    "task51": [
        [sys.executable, "-m", "pytest"],
        [sys.executable, "scripts/check_project.py"],
        [sys.executable, "scripts/check_task.py", "task51"],
        [sys.executable, "-m", "core.jobs.preflight_data_source", "--skip-network"],
        [sys.executable, "-m", "core.jobs.run_full_batch_update", "--dry-run", "--skip-network-preflight", "--max-symbols", "50", "--batch-size", "20", "--lookback-days", "120", "--max-retries", "1"],
        [sys.executable, "-m", "core.jobs.clean_generated_reports", "--force"],
    ],
    "task52": [
        [sys.executable, "-m", "pytest"],
        [sys.executable, "scripts/check_project.py"],
        [sys.executable, "scripts/check_task.py", "task52"],
        [sys.executable, "-m", "core.jobs.run_elder_review"],
        [sys.executable, "-m", "core.jobs.run_daily_workflow", "--doctor-before-run", "--skip-update", "--format", "all"],
        [sys.executable, "-m", "core.jobs.clean_generated_reports", "--force"],
    ],
    "task53": [
        [sys.executable, "-m", "pytest"],
        [sys.executable, "scripts/check_project.py"],
        [sys.executable, "scripts/check_task.py", "task53"],
        [sys.executable, "-m", "core.jobs.export_daily_research_workbook", "--output", "/tmp/a_stock_assistant_task53/daily_research.xlsx"],
    ],
    "task54": [
        [sys.executable, "-m", "pytest"],
        [sys.executable, "scripts/check_project.py"],
        [sys.executable, "scripts/check_task.py", "task54"],
    ],
    "task55": [
        [sys.executable, "-m", "pytest"],
        [sys.executable, "scripts/check_project.py"],
        [sys.executable, "scripts/check_task.py", "task55"],
    ],
    "task56": [
        [sys.executable, "-m", "pytest"],
        [sys.executable, "scripts/check_project.py"],
        [sys.executable, "scripts/check_task.py", "task56"],
        [sys.executable, "-m", "core.jobs.export_daily_research_workbook", "--output", "/tmp/a_stock_assistant_task56/daily_research.xlsx"],
    ],
    "task57a": [
        [sys.executable, "-m", "pytest"],
        [sys.executable, "scripts/check_project.py"],
        [sys.executable, "scripts/check_task.py", "task57a"],
        [sys.executable, "-m", "core.jobs.diagnose_data_source_network", "--format", "text", "--timeout", "5"],
        [sys.executable, "-m", "core.jobs.diagnose_data_source_network", "--format", "json", "--timeout", "5"],
    ],
    "task57b": [
        [sys.executable, "-m", "pytest"],
        [sys.executable, "scripts/check_project.py"],
        [sys.executable, "scripts/check_task.py", "task57b"],
        [sys.executable, "-m", "core.jobs.run_scheduled_daily_update", "--dry-run", "--update-limit", "50", "--stage-timeout-seconds", "180", "--format", "text", "--status-path", "/tmp/a_stock_assistant_task57b/status.json", "--lock-path", "/tmp/a_stock_assistant_task57b/update.lock"],
        [sys.executable, "-m", "core.jobs.run_scheduled_daily_update", "--dry-run", "--update-limit", "50", "--stage-timeout-seconds", "180", "--format", "json", "--status-path", "/tmp/a_stock_assistant_task57b/status.json", "--lock-path", "/tmp/a_stock_assistant_task57b/update.lock"],
        [sys.executable, "-m", "core.jobs.install_scheduled_daily_update", "--time", "18:00", "--dry-run", "--plist-dir", "/tmp/a_stock_assistant_task57b"],
    ],
    "task58": [
        [sys.executable, "-m", "pytest"],
        [sys.executable, "scripts/check_project.py"],
        [sys.executable, "scripts/check_task.py", "task58"],
        [sys.executable, "-m", "core.jobs.run_lookback_analysis", "--dry-run", "--format", "text", "--status-path", "/tmp/a_stock_assistant_task58/lookback_status.json"],
        [sys.executable, "-m", "core.jobs.run_lookback_analysis", "--dry-run", "--format", "json", "--status-path", "/tmp/a_stock_assistant_task58/lookback_status.json"],
        [sys.executable, "-m", "core.jobs.run_lookback_analysis", "--as-of", "latest", "--horizons", "1,3,5,10,20", "--limit", "300", "--format", "text", "--output", "/tmp/a_stock_assistant_task58/lookback_analysis.xlsx", "--status-path", "/tmp/a_stock_assistant_task58/lookback_status.json"],
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
