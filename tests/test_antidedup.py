"""环节四：防检测处理引擎单元测试。"""

from __future__ import annotations

import random
from pathlib import Path

from PIL import Image

from image_automation.core.config import AntiDedupConfig, JobConfig, OutputConfig, StylingConfig, WatermarkConfig
from image_automation.processing.antidedup import apply_antidedup
from image_automation.processing.pipeline import process_batch


def _make_image(color: str = "gray") -> Image.Image:
    return Image.new("RGB", (64, 64), color)


def test_antidedup_none_returns_same_image() -> None:
    image = _make_image("blue")
    config = AntiDedupConfig(mode="none")
    rng = random.Random(123)

    processed, operations = apply_antidedup(image, config, rng)

    assert operations == []
    assert list(processed.getdata()) == list(image.getdata())


def test_antidedup_light_applies_jitter_and_noise() -> None:
    image = _make_image("green")
    config = AntiDedupConfig(mode="light", color_jitter_strength=0.05, noise_strength=0.02)
    rng = random.Random(99)

    processed, operations = apply_antidedup(image, config, rng)

    assert any(op.startswith("color_jitter") for op in operations)
    assert any(op.startswith("noise") for op in operations)
    # Light扰动应保证尺寸不变且图像内容发生变化。
    assert processed.size == image.size
    assert list(processed.getdata()) != list(image.getdata())


def test_antidedup_medium_applies_rotation() -> None:
    image = _make_image("purple")
    config = AntiDedupConfig(
        mode="medium",
        rotation_range=(0.3, 0.3),  # 固定角度以保证旋转执行
        crop_margin=0.02,
    )
    rng = random.Random(7)

    processed, operations = apply_antidedup(image, config, rng)

    assert any("rotate" in op for op in operations)
    assert processed.size == image.size


def test_antidedup_heavy_applies_watermarks() -> None:
    image = _make_image("white")
    config = AntiDedupConfig(
        mode="heavy",
        watermark=WatermarkConfig(
            enabled=True,
            text="tester",
            count_range=(2, 2),
            opacity_range=(0.1, 0.1),
            rotation_range=(-2, 2),
            scale_range=(0.05, 0.05),
        ),
    )
    rng = random.Random(2024)

    processed, operations = apply_antidedup(image, config, rng)

    assert any(op.startswith("watermark") for op in operations)
    assert processed.size == image.size
    assert list(processed.getdata()) != list(image.getdata())


def test_pipeline_records_antidedup_notes(tmp_path: Path) -> None:
    source_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    source_dir.mkdir()
    output_dir.mkdir()

    _make_image("orange").save(source_dir / "sample.png")

    job = JobConfig(
        sources=[source_dir],
        output=OutputConfig(output_dir=output_dir),
        styling=StylingConfig(),
        anti_dedup=AntiDedupConfig(
            mode="light",
            noise_strength=0.02,
            color_jitter_strength=0.03,
        ),
        random_seed=42,
    )

    result = process_batch(job)

    assert len(result.succeeded) == 1
    note = result.succeeded[0].message
    assert note is not None and "antidedup" in note
