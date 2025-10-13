"""处理流水线：当前阶段只负责扫描与基础加载。"""

from __future__ import annotations

import logging
from typing import List

from image_automation.core.config import JobConfig
from image_automation.core.models import BatchResult, FileOutcome, ProcessedAsset
from image_automation.core.scanner import collect_source_images
from image_automation.processing.image_loader import ImageLoadingError, load_image

LOGGER = logging.getLogger(__name__)


def process_batch(config: JobConfig) -> BatchResult:
    """批量处理入口（环节二：扫描与基础加载）。"""

    LOGGER.info("开始扫描输入路径")
    sources = collect_source_images(config)
    LOGGER.info("发现 %d 个候选图片文件", len(sources))

    processed: list[ProcessedAsset] = []
    skipped: list[FileOutcome] = []
    failed: list[FileOutcome] = []

    for source in sources:
        try:
            image = load_image(source.source_path)
        except ImageLoadingError as exc:
            LOGGER.warning("加载失败：%s (%s)", source.source_path, exc)
            failed.append(
                FileOutcome(
                    source_path=source.source_path,
                    status="error-load",
                    message=str(exc),
                )
            )
            continue

        processed.append(
            ProcessedAsset(
                source=source,
                image_mode=image.mode,
                size=image.size,
                payload=image,
            )
        )

    return BatchResult(processed=processed, skipped=skipped, failed=failed)
