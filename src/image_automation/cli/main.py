"""命令行入口。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional, Tuple

import typer
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

from image_automation.core.config import (
    AntiDedupConfig,
    JobConfig,
    OutputConfig,
    StylingConfig,
    TextureConfig,
    ValidationConfig,
    WatermarkConfig,
)
from image_automation.core.progress import ProgressUpdate
from image_automation.processing.pipeline import process_batch
from image_automation.utils.logging import setup_logging

app = typer.Typer(help="批量图片风格化与防检测处理工具。")


def _parse_ratio(value: str) -> Tuple[int, int]:
    parts = value.split(":")
    if len(parts) != 2:
        raise typer.BadParameter("比例必须形如 1:1")
    try:
        w = int(parts[0])
        h = int(parts[1])
    except ValueError as exc:  # noqa: FBT003
        raise typer.BadParameter("比例必须为整数") from exc
    if w <= 0 or h <= 0:
        raise typer.BadParameter("比例必须大于 0")
    return w, h


def _parse_count_range(value: Tuple[int, int]) -> Tuple[int, int]:
    low, high = value
    if low > high:
        low, high = high, low
    return low, high


def _build_progress_callback(progress: Progress):
    task_id: Optional[int] = None

    def callback(update: ProgressUpdate) -> None:
        nonlocal task_id
        if update.total == 0:
            return
        if task_id is None:
            task_id = progress.add_task("处理图片", total=update.total)
        progress.update(task_id, completed=update.completed)
        if update.message:
            progress.log(update.message)

    return callback


@app.command("run")
def run_cli(  # noqa: PLR0913
    source: List[Path] = typer.Argument(..., help="源图片文件或目录，可指定多个"),
    output: Path = typer.Option(..., "--output", "-o", help="输出目录"),
    ratio: str = typer.Option("1:1", "--ratio", help="目标宽高比，形如 1:1"),
    min_width: int = typer.Option(800, "--min-width", help="输出最小宽度"),
    min_height: int = typer.Option(800, "--min-height", help="输出最小高度"),
    mode: str = typer.Option("contain", "--mode", help="尺寸适配模式，contain 或 cover"),
    background_color: str = typer.Option("#000000", "--background-color", help="背景色 (HEX)"),
    border_color: Optional[str] = typer.Option(None, "--border-color", help="纯色边框颜色 (HEX)"),
    border_thickness: int = typer.Option(0, "--border-thickness", help="纯色边框厚度"),
    border_image: Optional[Path] = typer.Option(None, "--border-image", help="PNG 边框模板"),
    antidedup_mode: str = typer.Option("none", "--antidedup-mode", help="防检测模式 none/light/medium/heavy"),
    allow_mirror: bool = typer.Option(False, "--allow-mirror", help="允许随机镜像"),
    noise_strength: float = typer.Option(0.015, "--noise-strength", help="噪点强度"),
    color_jitter: float = typer.Option(0.02, "--color-jitter", help="颜色扰动强度"),
    rotation_min: float = typer.Option(-0.5, "--rotation-min", help="随机旋转最小值"),
    rotation_max: float = typer.Option(0.5, "--rotation-max", help="随机旋转最大值"),
    crop_margin: float = typer.Option(0.01, "--crop-margin", help="旋转后放大裁剪比例"),
    watermark_text: Optional[str] = typer.Option(None, "--watermark-text", help="微痕水印文本"),
    watermark_count: Tuple[int, int] = typer.Option((3, 5), "--watermark-count", help="水印数量范围，默认 3 5"),
    watermark_opacity: Tuple[float, float] = typer.Option(
        (0.05, 0.15), "--watermark-opacity", help="水印透明度范围，默认 0.05 0.15"
    ),
    watermark_scale: Tuple[float, float] = typer.Option(
        (0.02, 0.05), "--watermark-scale", help="水印缩放范围，默认 0.02 0.05"
    ),
    texture_image: Optional[Path] = typer.Option(None, "--texture-image", help="纹理叠加图片"),
    texture_opacity: float = typer.Option(0.1, "--texture-opacity", help="纹理叠加透明度 0.0~1.0"),
    max_workers: int = typer.Option(4, "--workers", "-w", help="并发进程数量"),
    allow_recursive: bool = typer.Option(True, "--recursive/--no-recursive", help="是否递归扫描目录"),
    conflict_strategy: str = typer.Option("rename", "--on-conflict", help="文件名冲突策略"),
    random_seed: Optional[int] = typer.Option(None, "--seed", help="随机种子，便于结果复现"),
    auto_validate: bool = typer.Option(False, "--auto-validate", help="处理后立即对比原图计算相似度指标"),
) -> None:
    """执行批量处理。"""

    setup_logging()
    logging.getLogger(__name__).debug("CLI 参数解析完成")

    sources = [p.expanduser().resolve() for p in source]
    output_dir = output.expanduser().resolve()

    ratio_w, ratio_h = _parse_ratio(ratio)
    wm_count = _parse_count_range(watermark_count)
    wm_opacity = _parse_count_range(watermark_opacity)
    wm_scale = _parse_count_range(watermark_scale)

    styling = StylingConfig(
        aspect_ratio=(ratio_w, ratio_h),
        min_size=(min_width, min_height),
        mode=mode,
        background_color=background_color,
        border_color=border_color,
        border_thickness=border_thickness,
        border_image=border_image.resolve() if border_image else None,
    )

    watermark = WatermarkConfig(
        enabled=antidedup_mode == "heavy",
        text=watermark_text or "",
        count_range=wm_count,
        opacity_range=wm_opacity,
        rotation_range=(-5.0, 5.0),
        scale_range=wm_scale,
    )

    anti_dedup = AntiDedupConfig(
        mode=antidedup_mode,
        allow_mirror=allow_mirror,
        noise_strength=noise_strength,
        color_jitter_strength=color_jitter,
        rotation_range=(rotation_min, rotation_max),
        crop_margin=crop_margin,
        watermark=watermark,
        texture=TextureConfig(
            enabled=texture_image is not None,
            image_path=texture_image.resolve() if texture_image else None,
            opacity=max(0.0, min(texture_opacity, 1.0)),
        ),
    )

    job = JobConfig(
        sources=sources,
        output=OutputConfig(output_dir=output_dir, conflict_strategy=conflict_strategy),
        styling=styling,
        anti_dedup=anti_dedup,
        validation=ValidationConfig(enabled=auto_validate),
        allow_recursive=allow_recursive,
        max_workers=max_workers,
        random_seed=random_seed,
    )

    progress = Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
    )

    with progress:
        result = process_batch(job, progress_callback=_build_progress_callback(progress))

    typer.echo(
        f"处理完成：成功 {len(result.succeeded)} 张，跳过 {len(result.skipped)} 张，失败 {len(result.failed)} 张。"
    )
    typer.echo(f"报告文件：{output_dir / job.report_filename}")


if __name__ == "__main__":
    app()
