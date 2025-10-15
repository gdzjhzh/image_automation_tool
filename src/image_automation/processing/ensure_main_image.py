"""Tools for enforcing the 主图01.jpg size constraints."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from PIL import Image

_RESAMPLING = getattr(Image, "Resampling", Image)

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class AdjustmentStats:
    """Aggregated result of the ensure_main_image_size operation."""

    total_folders: int = 0
    inspected_files: int = 0
    adjusted_files: int = 0
    missing_files: int = 0
    errors: int = 0


def ensure_main_image_size(
    root_dir: Path,
    *,
    target_size: int = 800,
    logger: logging.Logger | None = None,
) -> AdjustmentStats:
    """Ensure each subfolder under ``root_dir`` contains a compliant 主图01.jpg.

    A compliant image must be square and both wider and taller than or equal to ``target_size``.
    Non-compliant images are resized to ``target_size`` × ``target_size`` using high-quality scaling.
    """

    if logger is None:
        logger = _LOGGER

    stats = AdjustmentStats()
    if not root_dir.exists() or not root_dir.is_dir():
        logger.warning("目录不存在或不是文件夹: %s", root_dir)
        return stats

    subfolders = _iter_subfolders(root_dir)
    for folder in subfolders:
        stats.total_folders += 1
        target_path = folder / "主图01.jpg"
        if not target_path.exists():
            logger.info("未找到主图: %s", target_path)
            stats.missing_files += 1
            continue

        stats.inspected_files += 1
        try:
            _process_image(target_path, target_size, logger=logger, stats=stats)
        except Exception as exc:  # noqa: BLE001
            stats.errors += 1
            logger.error("处理失败: %s -> %s", target_path, exc, exc_info=exc)

    logger.info(
        "统计: 总目录=%s, 检查图片=%s, 调整=%s, 未找到=%s, 异常=%s",
        stats.total_folders,
        stats.inspected_files,
        stats.adjusted_files,
        stats.missing_files,
        stats.errors,
    )
    return stats


def _iter_subfolders(root_dir: Path) -> Iterator[Path]:
    for child in sorted(root_dir.iterdir()):
        if child.is_dir():
            yield child


def _process_image(target_path: Path, target_size: int, *, logger: logging.Logger, stats: AdjustmentStats) -> None:
    with Image.open(target_path) as image:
        width, height = image.size
        if width == height and width >= target_size and height >= target_size:
            logger.info("图片合规，跳过: %s (%sx%s)", target_path, width, height)
            return

        logger.info("调整图片: %s (原尺寸 %sx%s)", target_path, width, height)

        resized = image.resize((target_size, target_size), _RESAMPLING.LANCZOS)
        resized.save(target_path, format=image.format or "JPEG")
        resized.close()
        stats.adjusted_files += 1
        logger.info("完成调整: %s -> %sx%s", target_path, target_size, target_size)
