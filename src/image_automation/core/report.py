"""报告生成工具。"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

from image_automation.core.models import FileOutcome

HEADER = ["source_path", "output_path", "status", "message", "phash_distance", "ssim"]


def write_csv_report(outcomes: Iterable[FileOutcome], output_dir: Path, filename: str) -> Path:
    """将处理结果写入 CSV 报告。"""

    report_path = output_dir / filename
    with report_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADER)
        for record in outcomes:
            writer.writerow(
                [
                    str(record.source_path),
                    str(record.output_path) if record.output_path else "",
                    record.status,
                    record.message or "",
                    _format_phash(record.phash_distance),
                    _format_ssim(record.ssim),
                ]
            )
    return report_path


def _format_phash(value: float | None) -> str:
    if value is None:
        return ""
    return str(int(round(value)))


def _format_ssim(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.6f}"
