"""环节三：测试文件扫描、风格化与输出管理逻辑。"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from PIL import Image

from image_automation.core.config import (
    AntiDedupConfig,
    JobConfig,
    OutputConfig,
    StylingConfig,
    TextureConfig,
    ValidationConfig,
)
from image_automation.processing.pipeline import process_batch


def make_config(
    source: Path,
    output: Path,
    *,
    styling: StylingConfig | None = None,
    conflict_strategy: str = "rename",
    enable_validation: bool = False,
    texture: TextureConfig | None = None,
) -> JobConfig:
    return JobConfig(
        sources=[source],
        output=OutputConfig(output_dir=output, conflict_strategy=conflict_strategy),
        styling=styling or StylingConfig(),
        anti_dedup=AntiDedupConfig(texture=texture or TextureConfig()),
        validation=ValidationConfig(enabled=enable_validation),
        max_workers=1,
    )


def test_process_batch_handles_valid_and_invalid_images(tmp_path: Path) -> None:
    source = tmp_path / "input"
    output = tmp_path / "output"
    source.mkdir()
    output.mkdir()

    good_image = Image.new("RGB", (64, 64), "blue")
    good_image.save(source / "valid.png")

    (source / "corrupted.png").write_text("not an image")
    (source / "notes.txt").write_text("hello")

    result = process_batch(make_config(source, output))

    assert len(result.succeeded) == 1
    assert len(result.failed) == 1
    assert len(result.skipped) == 0

    output_path = result.succeeded[0].output_path
    assert output_path is not None and output_path.exists()

    with Image.open(output_path) as img:
        assert img.size == (800, 800)
        assert img.mode == "RGB"

    report = output / "report.csv"
    assert report.exists()


def test_exif_orientation_is_corrected(tmp_path: Path) -> None:
    source = tmp_path / "input"
    output = tmp_path / "output"
    source.mkdir()
    output.mkdir()

    if not hasattr(Image, "Exif"):
        pytest.skip("当前 Pillow 版本不支持写入 EXIF 数据")

    image = Image.new("RGB", (80, 40), "red")
    exif = Image.Exif()
    exif[274] = 6  # 顺时针 90 度
    image.save(source / "rotated.jpg", exif=exif.tobytes())

    result = process_batch(make_config(source, output))

    assert len(result.succeeded) == 1
    out_path = result.succeeded[0].output_path
    assert out_path is not None

    with Image.open(out_path) as processed:
        assert processed.size == (800, 800)


def test_cmyk_image_converts_to_rgb(tmp_path: Path) -> None:
    source = tmp_path / "input"
    output = tmp_path / "output"
    source.mkdir()
    output.mkdir()

    cmyk_image = Image.new("CMYK", (50, 50), (0, 128, 255, 0))
    cmyk_image.save(source / "cmyk.jpg")

    result = process_batch(make_config(source, output))

    assert len(result.succeeded) == 1
    out_path = result.succeeded[0].output_path
    assert out_path is not None

    with Image.open(out_path) as processed:
        assert processed.mode == "RGB"


def test_contain_mode_with_background_and_border(tmp_path: Path) -> None:
    source = tmp_path / "input"
    output = tmp_path / "output"
    source.mkdir()
    output.mkdir()

    Image.new("RGB", (40, 80), "white").save(source / "portrait.png")

    styling = StylingConfig(
        aspect_ratio=(1, 1),
        min_size=(100, 100),
        mode="contain",
        background_color="#FF0000",
        border_color="#000000",
        border_thickness=10,
    )

    result = process_batch(make_config(source, output, styling=styling))

    out_path = result.succeeded[0].output_path
    assert out_path is not None

    with Image.open(out_path) as processed:
        assert processed.size == (120, 120)
        # 角落为黑色边框。
        assert processed.getpixel((0, 0)) == (0, 0, 0)
        # 背景区域位于边框内侧、图片外侧。
        bg_x = styling.border_thickness + 5
        bg_y = processed.height // 2
        assert processed.getpixel((bg_x, bg_y)) == (255, 0, 0)


def test_cover_mode_produces_expected_size(tmp_path: Path) -> None:
    source = tmp_path / "input"
    output = tmp_path / "output"
    source.mkdir()
    output.mkdir()

    Image.new("RGB", (400, 200), "green").save(source / "landscape.jpg")

    styling = StylingConfig(
        aspect_ratio=(1, 1),
        min_size=(150, 150),
        mode="cover",
    )

    result = process_batch(make_config(source, output, styling=styling))

    out_path = result.succeeded[0].output_path
    assert out_path is not None

    with Image.open(out_path) as processed:
        assert processed.size == (150, 150)


def test_conflict_rename_strategy(tmp_path: Path) -> None:
    source = tmp_path / "input"
    output = tmp_path / "output"
    source.mkdir()
    output.mkdir()

    Image.new("RGB", (50, 50), "blue").save(source / "dup.png")
    Image.new("RGB", (50, 50), "white").save(output / "dup.png")

    result = process_batch(make_config(source, output, conflict_strategy="rename"))

    assert len(result.succeeded) == 1
    renamed_path = result.succeeded[0].output_path
    assert renamed_path is not None and renamed_path.exists()
    assert renamed_path.name.startswith("dup_")
    assert renamed_path.suffix == ".png"


def test_conflict_skip_strategy(tmp_path: Path) -> None:
    source = tmp_path / "input"
    output = tmp_path / "output"
    source.mkdir()
    output.mkdir()

    Image.new("RGB", (60, 60), "blue").save(source / "dup.png")
    Image.new("RGB", (60, 60), "white").save(output / "dup.png")

    result = process_batch(make_config(source, output, conflict_strategy="skip"))

    assert len(result.succeeded) == 0
    assert len(result.skipped) == 1
    skipped_record = result.skipped[0]
    assert skipped_record.status == "skip-existing"
    assert skipped_record.output_path == output / "dup.png"


def test_texture_overlay_in_pipeline(tmp_path: Path) -> None:
    source = tmp_path / "input"
    output = tmp_path / "output"
    texture_dir = tmp_path / "assets"
    source.mkdir()
    output.mkdir()
    texture_dir.mkdir()

    Image.new("RGB", (80, 80), "red").save(source / "sample.png")
    Image.new("RGB", (40, 40), "blue").save(texture_dir / "texture.png")

    texture_cfg = TextureConfig(enabled=True, image_path=texture_dir / "texture.png", opacity=0.4)

    result = process_batch(make_config(source, output, texture=texture_cfg))

    assert len(result.succeeded) == 1
    note = result.succeeded[0].message
    assert note is not None and "texture" in note


def test_validation_metrics_recorded(tmp_path: Path) -> None:
    source = tmp_path / "input"
    output = tmp_path / "output"
    source.mkdir()
    output.mkdir()

    Image.new("RGB", (120, 120), "red").save(source / "sample.png")

    result = process_batch(make_config(source, output, enable_validation=True))

    assert len(result.succeeded) == 1
    record = result.succeeded[0]
    assert record.phash_distance is not None
    assert 0 <= record.phash_distance <= 64
    assert record.ssim is not None
    assert -1.0 <= record.ssim <= 1.0
    assert record.message is not None and "validation" in record.message

    report_path = output / "report.csv"
    with report_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        row = next(reader)
        assert "phash_distance" in row
        assert "ssim" in row
        assert row["phash_distance"]
        assert row["ssim"]
