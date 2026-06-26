"""Minimal PEP 517/660 backend for offline editable installs."""

from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

NAME = "a-stock-assistant"
NORMALIZED_NAME = "a_stock_assistant"
VERSION = "0.1.0"
DIST_INFO = f"{NORMALIZED_NAME}-{VERSION}.dist-info"


def get_requires_for_build_wheel(config_settings: dict[str, object] | None = None) -> list[str]:
    """Return build dependencies for wheel creation."""
    return []


def get_requires_for_build_editable(config_settings: dict[str, object] | None = None) -> list[str]:
    """Return build dependencies for editable wheel creation."""
    return []


def prepare_metadata_for_build_wheel(
    metadata_directory: str,
    config_settings: dict[str, object] | None = None,
) -> str:
    """Create package metadata for wheel builds."""
    return _write_metadata(Path(metadata_directory))


def prepare_metadata_for_build_editable(
    metadata_directory: str,
    config_settings: dict[str, object] | None = None,
) -> str:
    """Create package metadata for editable wheel builds."""
    return _write_metadata(Path(metadata_directory))


def build_wheel(
    wheel_directory: str,
    config_settings: dict[str, object] | None = None,
    metadata_directory: str | None = None,
) -> str:
    """Build a lightweight wheel containing source files."""
    wheel_path = Path(wheel_directory) / _wheel_name()
    project_root = Path(__file__).resolve().parent
    entries: dict[str, bytes] = {}

    for package_dir in ("app", "core"):
        for path in (project_root / package_dir).rglob("*.py"):
            entries[path.relative_to(project_root).as_posix()] = path.read_bytes()

    _add_dist_info(entries)
    _write_wheel(wheel_path, entries)
    return wheel_path.name


def build_editable(
    wheel_directory: str,
    config_settings: dict[str, object] | None = None,
    metadata_directory: str | None = None,
) -> str:
    """Build an editable wheel that adds the project root to Python path."""
    wheel_path = Path(wheel_directory) / _wheel_name()
    project_root = Path(__file__).resolve().parent
    entries = {
        f"{NORMALIZED_NAME}.pth": f"{project_root}{os.linesep}".encode(),
    }
    _add_dist_info(entries)
    _write_wheel(wheel_path, entries)
    return wheel_path.name


def _write_metadata(metadata_directory: Path) -> str:
    dist_info_dir = metadata_directory / DIST_INFO
    dist_info_dir.mkdir(parents=True, exist_ok=True)
    (dist_info_dir / "METADATA").write_text(_metadata(), encoding="utf-8")
    (dist_info_dir / "WHEEL").write_text(_wheel_metadata(), encoding="utf-8")
    return DIST_INFO


def _add_dist_info(entries: dict[str, bytes]) -> None:
    entries[f"{DIST_INFO}/METADATA"] = _metadata().encode()
    entries[f"{DIST_INFO}/WHEEL"] = _wheel_metadata().encode()


def _metadata() -> str:
    return "\n".join(
        [
            "Metadata-Version: 2.2",
            f"Name: {NAME}",
            f"Version: {VERSION}",
            "Summary: A local A-share stock selection research assistant.",
            "Requires-Python: >=3.12",
            "Requires-Dist: duckdb",
            "Requires-Dist: pandas",
            "Requires-Dist: pydantic-settings",
            "Requires-Dist: python-dotenv",
            "Provides-Extra: app",
            "Requires-Dist: akshare; extra == 'app'",
            "Requires-Dist: fastapi; extra == 'app'",
            "Requires-Dist: numpy; extra == 'app'",
            "Requires-Dist: pyarrow; extra == 'app'",
            "Requires-Dist: streamlit; extra == 'app'",
            "Requires-Dist: tushare; extra == 'app'",
            "Requires-Dist: uvicorn; extra == 'app'",
            "Provides-Extra: dev",
            "Requires-Dist: pytest; extra == 'dev'",
            "Requires-Dist: ruff; extra == 'dev'",
            "",
        ]
    )


def _wheel_metadata() -> str:
    return "\n".join(
        [
            "Wheel-Version: 1.0",
            "Generator: a-stock-assistant-build-backend",
            "Root-Is-Purelib: true",
            "Tag: py3-none-any",
            "",
        ]
    )


def _wheel_name() -> str:
    return f"{NORMALIZED_NAME}-{VERSION}-py3-none-any.whl"


def _write_wheel(wheel_path: Path, entries: dict[str, bytes]) -> None:
    records: list[str] = []
    with ZipFile(wheel_path, "w", ZIP_DEFLATED) as wheel:
        for name, content in sorted(entries.items()):
            wheel.writestr(name, content)
            records.append(f"{name},sha256={_digest(content)},{len(content)}")

        record_name = f"{DIST_INFO}/RECORD"
        records.append(f"{record_name},,")
        wheel.writestr(record_name, "\n".join(records) + "\n")


def _digest(content: bytes) -> str:
    digest = hashlib.sha256(content).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
