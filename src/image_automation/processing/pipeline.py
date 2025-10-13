"""处理流水线：扫描、基础加载、风格化与输出管理。"""

from __future__ import annotations

import logging
from image_automation.core.config import JobConfig
from image_automation.core.exceptions import InvalidConfigurationError
from image_automation.core.models import BatchResult, FileOutcome
from image_automation.core.output_manager import ImageWriteError, OutputManager
from image_automation.core.report import write_csv_report
from image_automation.core.scanner import collect_source_images
from image_automation.processing.image_loader import ImageLoadingError, load_image
from image_automation.processing.styling import apply_styling

LOGGER = logging.getLogger(__name__)


def process_batch(config: JobConfig) -> BatchResult:
    """批量处理入口（环节三：扫描、加载、风格化 + 输出）。"""

    LOGGER.info("开始扫描输入路径")
    sources = collect_source_images(config)
    LOGGER.info("发现 %d 个候选图片文件", len(sources))

    successes: list[FileOutcome] = []
    skipped: list[FileOutcome] = []
    failed: list[FileOutcome] = []

    output_manager = OutputManager(config.output)

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

        try:
            styled_image = apply_styling(image, config.styling)
        except InvalidConfigurationError as exc:
            LOGGER.error("风格化失败：%s (%s)", source.source_path, exc)
            failed.append(
                FileOutcome(
                    source_path=source.source_path,
                    status="error-style",
                    message=str(exc),
                )
            )
            image.close()
            continue

        decision = output_manager.decide_destination(source)
        if decision.action == "skip":
            LOGGER.info("跳过输出（已存在）：%s", decision.destination)
            skipped.append(
                FileOutcome(
                    source_path=source.source_path,
                    status="skip-existing",
                    output_path=decision.destination,
                    message=decision.note,
                )
            )
            image.close()
            styled_image.close()
            continue

        assert decision.destination is not None
        dest_path = decision.destination

        try:
            output_manager.save_image(styled_image, dest_path)
        except ImageWriteError as exc:
            LOGGER.error("写入失败：%s (%s)", dest_path, exc)
            failed.append(
                FileOutcome(
                    source_path=source.source_path,
                    status="error-write",
                    message=str(exc),
                )
            )
            image.close()
            styled_image.close()
            continue

        status = "processed"
        if decision.action == "overwrite":
            status = "processed-overwrite"
        elif decision.action == "rename":
            status = "processed-rename"

        successes.append(
            FileOutcome(
                source_path=source.source_path,
                status=status,
                output_path=dest_path,
                message=decision.note,
            )
        )

        LOGGER.debug("写入完成：%s -> %s", source.source_path, dest_path)

        image.close()
        styled_image.close()

    result = BatchResult(succeeded=successes, skipped=skipped, failed=failed)

    try:
        write_csv_report(result.all_outcomes(), output_manager.output_dir, config.report_filename)
    except OSError as exc:
        LOGGER.error("写入报告失败：%s", exc)

    return result
