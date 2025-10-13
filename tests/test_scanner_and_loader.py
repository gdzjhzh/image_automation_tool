"""环节二：测试文件扫描与基础加载逻辑。"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from image_automation.core.config import (
    AntiDedupConfig,
    JobConfig,
    OutputConfig,
    StylingConfig,
)
from image_automation.processing.pipeline import process_batch


def make_basic_config(source: Path, output: Path) -> JobConfig:
    return JobConfig(
        sources=[source],
        output=OutputConfig(output_dir=output),
        styling=StylingConfig(),
        anti_dedup=AntiDedupConfig(),
    )


def test_process_batch_handles_valid_and_invalid_images(tmp_path: Path) -> None:
    source = tmp_path / "input"
    output = tmp_path / "output"
    source.mkdir()
    output.mkdir()

    good_image = Image.new("RGB", (64, 64), "blue")
    good_image.save(source / "valid.png")

    # 非图片文件但扩展名匹配 -> 加载时触发失败。
    (source / "corrupted.png").write_text("not an image")

    # 非图片扩展名 -> 应该被忽略。
    (source / "notes.txt").write_text("hello")

    config = make_basic_config(source, output)
    result = process_batch(config)

    assert len(result.processed) == 1
    assert result.processed[0].payload.mode == "RGB"
    assert result.processed[0].size == (64, 64)

    assert len(result.failed) == 1
    assert result.failed[0].status == "error-load"


def test_exif_orientation_is_corrected(tmp_path: Path) -> None:
    source = tmp_path / "input"
    output = tmp_path / "output"
    source.mkdir()
    output.mkdir()

    image = Image.new("RGB", (80, 40), "red")

    if not hasattr(Image, "Exif"):
        pytest.skip("当前 Pillow 版本不支持写入 EXIF 数据")

    exif = Image.Exif()
    exif[274] = 6  # 旋转 90 度
    image.save(source / "rotated.jpg", exif=exif.tobytes())

    config = make_basic_config(source, output)
    result = process_batch(config)

    assert len(result.processed) == 1
    processed_image = result.processed[0].payload
    assert processed_image.size == (40, 80)


def test_cmyk_image_converts_to_rgb(tmp_path: Path) -> None:
    source = tmp_path / "input"
    output = tmp_path / "output"
    source.mkdir()
    output.mkdir()

    cmyk_image = Image.new("CMYK", (50, 50), (0, 128, 255, 0))
    cmyk_image.save(source / "cmyk.jpg")

    config = make_basic_config(source, output)
    result = process_batch(config)

    assert len(result.processed) == 1
    assert result.processed[0].payload.mode == "RGB"
