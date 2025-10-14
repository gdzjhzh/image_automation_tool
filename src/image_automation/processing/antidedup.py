"""防重复检测处理引擎。"""

from __future__ import annotations

import logging
import random
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps

from image_automation.core.config import AntiDedupConfig, TextureConfig, WatermarkConfig

LOGGER = logging.getLogger(__name__)

MIRROR_PROBABILITY = 0.1


def apply_antidedup(image: Image.Image, config: AntiDedupConfig, rng: random.Random) -> tuple[Image.Image, list[str]]:
    """根据配置对图片执行随机扰动与水印，返回处理后的图片与说明。"""

    mode = (config.mode or "none").lower()
    operations: list[str] = []
    working = image

    if mode != "none":
        if config.allow_mirror and rng.random() < MIRROR_PROBABILITY:
            working = working.transpose(Image.FLIP_LEFT_RIGHT)
            operations.append("mirror")

        if mode in {"light", "medium", "heavy"}:
            working = _apply_color_jitter(working, config, rng, operations)
            working = _apply_noise(working, config, rng, operations)

        if mode in {"medium", "heavy"}:
            working = _apply_rotation_crop(working, config, rng, operations)

    if config.texture.enabled:
        working = _apply_texture(working, config.texture, operations)

    if mode == "heavy":
        working = _apply_watermarks(working, config.watermark, rng, operations)

    return working, operations


def _apply_color_jitter(
    image: Image.Image, config: AntiDedupConfig, rng: random.Random, operations: list[str]
) -> Image.Image:
    """对亮度、对比度、饱和度进行微调。"""

    strength = config.color_jitter_strength
    if strength <= 0:
        return image

    factors = []
    for enhancer_cls, name in (
        (ImageEnhance.Brightness, "brightness"),
        (ImageEnhance.Contrast, "contrast"),
        (ImageEnhance.Color, "saturation"),
    ):
        delta = rng.uniform(-strength, strength)
        factor = 1.0 + delta
        factors.append((name, factor))
        image = enhancer_cls(image).enhance(factor)

    operations.append(
        "color_jitter(" + ", ".join(f"{name}={factor:.3f}" for name, factor in factors) + ")"
    )
    return image


def _apply_noise(
    image: Image.Image, config: AntiDedupConfig, rng: random.Random, operations: list[str]
) -> Image.Image:
    """叠加低强度噪点。"""

    strength = config.noise_strength
    if strength <= 0:
        return image

    array = np.asarray(image).astype(np.float32)
    np_rng = np.random.default_rng(rng.randint(0, 2**32 - 1))
    noise_map = np_rng.uniform(-1.0, 1.0, size=array.shape).astype(np.float32)
    array += noise_map * (strength * 255.0)
    np.clip(array, 0, 255, out=array)

    operations.append(f"noise(strength={strength:.3f})")
    noisy = Image.fromarray(array.astype(np.uint8))
    if noisy.mode != image.mode:
        noisy = noisy.convert(image.mode)
    return noisy


def _apply_rotation_crop(
    image: Image.Image, config: AntiDedupConfig, rng: random.Random, operations: list[str]
) -> Image.Image:
    """应用微小旋转并裁剪回原尺寸。"""

    angle = rng.uniform(*config.rotation_range)
    if abs(angle) < 1e-3:
        return image

    width, height = image.size
    scale = 1.0 + max(config.crop_margin, 0.0)
    enlarged_size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
    enlarged = ImageOps.fit(image, enlarged_size, method=Image.LANCZOS, centering=(0.5, 0.5))

    rotated = enlarged.rotate(angle, resample=Image.BICUBIC, expand=True)
    fitted = ImageOps.fit(rotated, (width, height), method=Image.LANCZOS, centering=(0.5, 0.5))

    operations.append(f"rotate(angle={angle:.3f})")
    return fitted


def _apply_watermarks(
    image: Image.Image, watermark_config: WatermarkConfig, rng: random.Random, operations: list[str]
) -> Image.Image:
    """添加多重微痕水印。"""

    base = image.convert("RGBA")
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    count_min, count_max = watermark_config.count_range
    if count_min > count_max:
        count_min, count_max = count_max, count_min
    count = rng.randint(count_min, count_max)

    try:
        font = ImageFont.load_default()
    except OSError:
        font = None

    text = watermark_config.text or "digital-dust"
    width, height = base.size

    for _ in range(count):
        opacity = rng.uniform(*watermark_config.opacity_range)
        rotation = rng.uniform(*watermark_config.rotation_range)
        scale = rng.uniform(*watermark_config.scale_range)

        text_bounds = draw.textbbox((0, 0), text, font=font)
        text_width = max(1, text_bounds[2] - text_bounds[0])
        text_height = max(1, text_bounds[3] - text_bounds[1])

        base_canvas = Image.new("RGBA", (text_width, text_height), (0, 0, 0, 0))
        canvas_draw = ImageDraw.Draw(base_canvas)
        canvas_draw.text((0, 0), text, fill=(255, 255, 255, int(255 * opacity)), font=font)

        target_w = max(1, int(text_width * (0.5 + scale)))
        target_h = max(1, int(text_height * (0.5 + scale)))
        scaled = ImageOps.contain(base_canvas, (target_w, target_h), method=Image.LANCZOS)

        rotated = scaled.rotate(rotation, expand=True)

        max_x = max(1, width - rotated.width)
        max_y = max(1, height - rotated.height)
        x = rng.randint(0, max_x)
        y = rng.randint(0, max_y)

        overlay.alpha_composite(rotated, dest=(x, y))

    combined = Image.alpha_composite(base, overlay)
    operations.append(f"watermark(count={count})")
    return combined.convert("RGB")


def _apply_texture(image: Image.Image, texture_config: TextureConfig, operations: list[str]) -> Image.Image:
    """按配置叠加纹理图层。"""

    if not texture_config.image_path:
        return image

    opacity = max(0.0, min(texture_config.opacity, 1.0))
    if opacity <= 0:
        return image

    try:
        with Image.open(texture_config.image_path) as texture_img:
            texture = texture_img.convert("RGB")
    except OSError as exc:
        LOGGER.warning("无法加载纹理图片 %s: %s", texture_config.image_path, exc)
        return image

    texture = ImageOps.fit(texture, image.size, Image.LANCZOS)
    if texture.mode != image.mode:
        texture = texture.convert(image.mode)

    blended = Image.blend(image, texture, opacity)
    operations.append(f"texture(opacity={opacity:.3f})")
    return blended
