"""处理流水线：扫描、并发执行风格化、防检测与输出管理。"""

from __future__ import annotations

import logging
import random
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Optional, Set

from image_automation.core.config import JobConfig
from image_automation.core.models import BatchResult, FileOutcome
from image_automation.core.output_manager import OutputManager
from image_automation.core.progress import ProgressUpdate
from image_automation.core.report import write_csv_report
from image_automation.core.scanner import collect_source_images
from image_automation.processing.worker import ProcessingTask, run_task

LOGGER = logging.getLogger(__name__)


ProgressCallback = Optional[Callable[[ProgressUpdate], None]]


def process_batch(config: JobConfig, progress_callback: ProgressCallback = None) -> BatchResult:
    """批量处理入口：扫描、并发执行风格化、防检测与输出。"""

    LOGGER.info("开始扫描输入路径")
    sources = collect_source_images(config)
    total = len(sources)
    LOGGER.info("发现 %d 个候选图片文件", total)

    successes: list[FileOutcome] = []
    skipped: list[FileOutcome] = []
    failed: list[FileOutcome] = []

    if total == 0:
        _emit_progress(progress_callback, completed=0, total=0, message="没有需要处理的图片")
        return BatchResult(succeeded=successes, skipped=skipped, failed=failed)

    output_manager = OutputManager(config.output)
    reserved_paths: Set[Path] = set()
    global_rng = random.Random(config.random_seed)
    tasks: list[ProcessingTask] = []
    completed = 0

    for source in sources:
        decision = output_manager.decide_destination(source, reserved_paths=reserved_paths)
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
            completed += 1
            _emit_progress(progress_callback, completed, total, f"跳过 {source.source_path.name}")
            continue

        assert decision.destination is not None
        task_seed = global_rng.randint(0, 2**32 - 1)
        tasks.append(
            ProcessingTask(
                source_path=source.source_path,
                dest_path=decision.destination,
                decision_action=decision.action,
                decision_note=decision.note,
                styling=config.styling,
                anti_dedup=config.anti_dedup,
                random_seed=task_seed,
            )
        )

    _emit_progress(progress_callback, completed, total, "开始执行处理任务")

    if not tasks:
        # 全部被跳过
        _emit_progress(progress_callback, total, total, "全部文件已跳过")
        result = BatchResult(succeeded=successes, skipped=skipped, failed=failed)
        _write_report(config, output_manager, result)
        return result

    if config.max_workers <= 1:
        for task in tasks:
            outcome = run_task(task)
            _record_outcome(outcome, successes, failed)
            completed += 1
            _emit_progress(progress_callback, completed, total, f"完成 {task.source_path.name}")
    else:
        with ProcessPoolExecutor(max_workers=config.max_workers) as executor:
            future_map = {executor.submit(run_task, task): task for task in tasks}
            for future in as_completed(future_map):
                task = future_map[future]
                try:
                    outcome = future.result()
                except Exception as exc:  # noqa: BLE001
                    LOGGER.exception("任务执行异常：%s", exc)
                    outcome = FileOutcome(
                        source_path=task.source_path,
                        status="error-worker",
                        message=str(exc),
                    )
                _record_outcome(outcome, successes, failed)
                completed += 1
                _emit_progress(progress_callback, completed, total, f"完成 {task.source_path.name}")

    result = BatchResult(succeeded=successes, skipped=skipped, failed=failed)
    _write_report(config, output_manager, result)
    _emit_progress(progress_callback, total, total, "处理完成")
    return result


def _record_outcome(outcome: FileOutcome, successes: list[FileOutcome], failed: list[FileOutcome]) -> None:
    if outcome.status.startswith("processed"):
        successes.append(outcome)
    elif outcome.status == "skip-existing":
        # 理论上不会进入此分支（已在主进程处理），但保留以防未来扩展。
        pass
    else:
        failed.append(outcome)


def _emit_progress(
    callback: ProgressCallback,
    completed: int,
    total: int,
    message: Optional[str] = None,
) -> None:
    if not callback:
        return
    callback(ProgressUpdate(total=total, completed=completed, message=message))


def _write_report(config: JobConfig, output_manager: OutputManager, result: BatchResult) -> None:
    try:
        write_csv_report(result.all_outcomes(), output_manager.output_dir, config.report_filename)
    except OSError as exc:
        LOGGER.error("写入报告失败：%s", exc)
