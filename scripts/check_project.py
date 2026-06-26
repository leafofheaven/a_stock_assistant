"""Repository-wide quality checks for local runs and CI."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

TOKEN_PATTERNS = (
    re.compile(r"TUSHARE_TOKEN\s*=\s*[A-Za-z0-9]{20,}"),
    re.compile(r"tushare_token\s*=\s*[\"'][A-Za-z0-9]{20,}[\"']", re.IGNORECASE),
    re.compile(r"ts\.set_token\(\s*[\"'][A-Za-z0-9]{20,}[\"']\s*\)"),
)

REAL_API_TEST_PATTERNS = (
    re.compile(r"^\s*import\s+tushare\b", re.MULTILINE),
    re.compile(r"^\s*from\s+tushare\b", re.MULTILINE),
    re.compile(r"^\s*import\s+akshare\b", re.MULTILINE),
    re.compile(r"^\s*from\s+akshare\b", re.MULTILINE),
    re.compile(r"\bts\.pro_api\s*\("),
    re.compile(r"\bak\.[A-Za-z_][A-Za-z0-9_]*\s*\("),
)


def get_tracked_files(root: Path) -> list[Path]:
    """Return Git-tracked files under root, falling back to all files outside ignored dirs."""
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        ignored_dirs = {".git", ".venv", ".pytest_cache"}
        return sorted(
            path
            for path in root.rglob("*")
            if path.is_file() and not any(part in ignored_dirs for part in path.relative_to(root).parts)
        )

    return [root / line for line in result.stdout.splitlines() if line]


def run_checks(root: Path) -> list[str]:
    """Run repository quality checks and return human-readable failure messages."""
    tracked_files = get_tracked_files(root)
    relative_paths = {path.relative_to(root).as_posix(): path for path in tracked_files}
    failures: list[str] = []

    failures.extend(check_forbidden_files(relative_paths))
    failures.extend(check_required_paths(root))
    failures.extend(check_hardcoded_tushare_tokens(root, tracked_files))
    failures.extend(check_tests_avoid_real_external_apis(root, tracked_files))
    return failures


def check_forbidden_files(relative_paths: dict[str, Path]) -> list[str]:
    """Check that sensitive or generated files are not tracked."""
    failures: list[str] = []

    if ".env" in relative_paths:
        failures.append("Do not commit .env.")

    pycache_paths = [path for path in relative_paths if "__pycache__" in path.split("/")]
    if pycache_paths:
        failures.append(f"Do not commit __pycache__ files: {', '.join(sorted(pycache_paths))}")

    pyc_paths = [path for path in relative_paths if path.endswith(".pyc")]
    if pyc_paths:
        failures.append(f"Do not commit .pyc files: {', '.join(sorted(pyc_paths))}")

    return failures


def check_required_paths(root: Path) -> list[str]:
    """Check that required project files and directories exist."""
    required_paths = ["PROJECT_SPEC.md", "README.md", "app", "core", "tests"]
    return [f"Required path is missing: {path}" for path in required_paths if not (root / path).exists()]


def check_hardcoded_tushare_tokens(root: Path, tracked_files: list[Path]) -> list[str]:
    """Check tracked text files for hardcoded Tushare token-like strings."""
    failures: list[str] = []
    for path in tracked_files:
        if not is_text_candidate(path):
            continue
        text = read_text(path)
        if text is None:
            continue
        for pattern in TOKEN_PATTERNS:
            if pattern.search(text):
                failures.append(
                    f"Possible hardcoded Tushare token in {path.relative_to(root).as_posix()}"
                )
                break
    return failures


def check_tests_avoid_real_external_apis(root: Path, tracked_files: list[Path]) -> list[str]:
    """Check tests do not import or call real Tushare or AKShare APIs."""
    failures: list[str] = []
    for path in tracked_files:
        relative_path = path.relative_to(root).as_posix()
        if not relative_path.startswith("tests/") or not path.suffix == ".py":
            continue
        text = read_text(path)
        if text is None:
            continue
        for pattern in REAL_API_TEST_PATTERNS:
            if pattern.search(text):
                failures.append(f"Test appears to call a real external API: {relative_path}")
                break
    return failures


def is_text_candidate(path: Path) -> bool:
    """Return whether a file should be scanned as text."""
    return path.suffix.lower() in {
        "",
        ".env",
        ".example",
        ".ini",
        ".md",
        ".py",
        ".sql",
        ".toml",
        ".txt",
        ".yml",
        ".yaml",
    }


def read_text(path: Path) -> str | None:
    """Read a text file, returning None for undecodable content."""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None


def main(argv: list[str] | None = None) -> int:
    """Run checks from the command line."""
    parser = argparse.ArgumentParser(description="Run repository quality checks.")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Repository root.")
    args = parser.parse_args(argv)

    failures = run_checks(args.root.resolve())
    if failures:
        print("Project checks failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("Project checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
