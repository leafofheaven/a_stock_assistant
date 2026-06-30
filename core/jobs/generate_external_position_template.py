"""Generate external simulated trade and position import templates."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from core.external_positions.importer import position_template_frame, trade_template_frame


def generate_external_position_template(*, output_dir: Path | str = "reports/templates", quiet: bool = False) -> dict[str, Any]:
    """Generate CSV templates for external simulated trades and positions."""
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    trades_path = directory / "external_trades_template.csv"
    positions_path = directory / "external_position_snapshots_template.csv"
    trade_template_frame().to_csv(trades_path, index=False, encoding="utf-8-sig")
    position_template_frame().to_csv(positions_path, index=False, encoding="utf-8-sig")
    result = {"status": "success", "generated_files": {"trades": str(trades_path), "positions": str(positions_path)}}
    if not quiet:
        print("外部模拟持仓模板生成摘要")
        print(f"- 交易记录模板: {trades_path}")
        print(f"- 持仓快照模板: {positions_path}")
    return result


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Generate external simulated import templates.")
    parser.add_argument("--output-dir", default="reports/templates")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    generate_external_position_template(output_dir=args.output_dir, quiet=args.quiet)


if __name__ == "__main__":
    main()

