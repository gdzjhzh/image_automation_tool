"""并发处理的工作单元。"""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PIL import Image

from image_automation.core.config import AntiDedupConfig, StylingConfig
from image_automation.core.exceptions import InvalidConfigurationError
from image_automation.core.models import FileOutcome
from image_automation.core.output_manager import ImageWriteError, save_image_file
from image_automation.processing.antidedup import apply_antidedup
from image_automation.processing.image_loader import ImageLoadingError, load_image
from image_automation.processing.styling import apply_styling


@dataclass(slots=True)
class ProcessingTask:
    """描述单个图片处理任务。"""

    source_path: Path
    dest_path: Path
    decision_action: str
    decision_note: Optional[str]
    styling: StylingConfig
    anti_dedup: AntiDedupConfig
    random_seed: int


def run_task(task: ProcessingTask) -> FileOutcome:
    """在工作进程中执行完整的处理流程。"""

    rng = random.Random(task.random_seed)
    image: Optional[Image.Image] = None
    styled_image: Optional[Image.Image] = None
    processed_image: Optional[Image.Image] = None

    try:
        image = load_image(task.source_path)
    except ImageLoadingError as exc:
        return FileOutcome(
            source_path=task.source_path,
            status="error-load",
            message=str(exc),
        )

    try:
        styled_image = apply_styling(image, task.styling)
    except InvalidConfigurationError as exc:
        _close_if_needed(image)
        return FileOutcome(
            source_path=task.source_path,
            status="error-style",
            message=str(exc),
        )

    try:
        processed_image, operations = apply_antidedup(styled_image, task.anti_dedup, rng)
    except Exception as exc:  # noqa: BLE001
        _close_if_needed(image, styled_image)
        return FileOutcome(
            source_path=task.source_path,
            status="error-antidedup",
            message=str(exc),
        )

    status = "processed"
    if task.decision_action == "overwrite":
        status = "processed-overwrite"
    elif task.decision_action == "rename":
        status = "processed-rename"

    try:
        save_image_file(processed_image, task.dest_path)
    except ImageWriteError as exc:
        _close_if_needed(image, styled_image, processed_image)
        return FileOutcome(
            source_path=task.source_path,
            status="error-write",
            message=str(exc),
        )

    note = _compose_note(task.decision_note, operations)
    _close_if_needed(image, styled_image, processed_image)

    return FileOutcome(
        source_path=task.source_path,
        status=status,
        output_path=task.dest_path,
        message=note,
    )


def _compose_note(decision_note: Optional[str], operations: list[str]) -> Optional[str]:
    parts: list[str] = []
    if decision_note:
        parts.append(decision_note)
    if operations:
        parts.append("antidedup: " + ", ".join(operations))
    if not parts:
        return None
    return "; ".join(parts)


def _close_if_needed(*images: Optional[Image.Image]) -> None:
    for img in images:
        if img is not None:
            img.close()
