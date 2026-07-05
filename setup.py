"""Project packaging for local editable installs."""

from __future__ import annotations

from setuptools import find_packages, setup


setup(
    name="a-stock-assistant",
    version="0.1.0",
    description="A local A-share stock selection research assistant.",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    python_requires=">=3.12",
    packages=find_packages(include=["app", "app.*", "core", "core.*", "web", "web.*"]),
    install_requires=[
        "duckdb",
        "baostock>=0.9.2",
        "openpyxl",
        "pandas",
        "pydantic-settings",
        "pytest",
        "python-dotenv",
    ],
    extras_require={
        "app": [
            "akshare",
            "fastapi",
            "numpy",
            "pyarrow",
            "streamlit",
            "tushare",
            "uvicorn",
        ],
        "dev": [
            "ruff",
        ],
    },
)
