"""Generate static JSON artifacts for GitHub Pages frontend."""

from __future__ import annotations

import json
from pathlib import Path

from src.engine.main_engine import run_engine


def generate_daily_outputs(base_dir: Path | None = None) -> Path:
    root = base_dir or Path.cwd()
    report_path = root / "public" / "data" / "daily_report.json"
    return run_engine(output_path=report_path)


if __name__ == "__main__":
    output = generate_daily_outputs()
    print(f"Generated {output}")
