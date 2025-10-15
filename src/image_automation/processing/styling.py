"""风格化处理模块。"""

from __future__ import annotations

import logging
import math
from pathlib import Path

from PIL import Image, ImageOps

from image_automation.core.config import StylingConfig
from image_automation.core.exceptions import InvalidConfigurationError
from image_automation.utils.colors import parse_hex_color

LOGGER = logging.getLogger(__name__)

VALID_MODES = {"contain", "cover"}


def apply_styling(image: Image.Image, config: StylingConfig) -> Image.Image:
    """根据配置对图片执行尺寸规范化与边框合成。"""

    if config.mode not in VALID_MODES:
        raise InvalidConfigurationError(f"未知的尺寸模式: {config.mode}")

    should_resize = _should_resize(image.size, config)
    if should_resize:
        target_size = _compute_target_size(config)
        if config.mode == "contain":
            styled = _apply_contain(image, target_size, config.background_color)
        else:
            styled = ImageOps.fit(image, target_size, Image.LANCZOS, centering=(0.5, 0.5))
    else:
        styled = image.copy()

    if config.border_thickness and config.border_thickness > 0 and config.border_color:
        border_color = parse_hex_color(config.border_color)
        styled = ImageOps.expand(styled, border=config.border_thickness, fill=border_color)

    if config.border_image:
        styled = _overlay_border(styled, config.border_image)

    return styled


def _apply_contain(image: Image.Image, target_size: tuple[int, int], background: str) -> Image.Image:
    """使用 contain 模式适配尺寸。"""

    background_color = parse_hex_color(background)
    canvas = Image.new("RGB", target_size, background_color)

    resized = ImageOps.contain(image, target_size, Image.LANCZOS)
    offset = (
        (target_size[0] - resized.width) // 2,
        (target_size[1] - resized.height) // 2,
    )
    canvas.paste(resized, offset)
    return canvas


def _overlay_border(styled: Image.Image, border_path: Path) -> Image.Image:
    """将提供的 PNG 边框叠加到结果图像上。"""

    try:
        with Image.open(border_path) as border_img:
            border_rgba = border_img.convert("RGBA")
    except OSError as exc:
        LOGGER.warning("无法加载边框图片 %s: %s", border_path, exc)
        return styled

    border_rgba = border_rgba.resize(styled.size, Image.LANCZOS)
    base = styled.convert("RGBA")
    combined = Image.alpha_composite(base, border_rgba)
    return combined.convert("RGB")


def _compute_target_size(config: StylingConfig) -> tuple[int, int]:
    """根据比例与最小尺寸计算目标宽高。"""

    ratio_w, ratio_h = config.aspect_ratio
    if ratio_w <= 0 or ratio_h <= 0:
        raise InvalidConfigurationError("aspect_ratio 必须为正整数")

    min_w, min_h = config.min_size
    if min_w <= 0 or min_h <= 0:
        raise InvalidConfigurationError("min_size 必须大于 0")

    scale = max(min_w / ratio_w, min_h / ratio_h)
    target_w = int(math.ceil(ratio_w * scale))
    target_h = int(math.ceil(ratio_h * scale))
    return target_w, target_h


def _should_resize(size: tuple[int, int], config: StylingConfig) -> bool:
    """Determine whether resizing/cropping is required."""

    width, height = size
    ratio_w, ratio_h = config.aspect_ratio
    min_w, min_h = config.min_size

    meets_min = width >= min_w and height >= min_h
    ratio_matches = _ratio_matches(width, height, ratio_w, ratio_h)
    return not (meets_min and ratio_matches)


def _ratio_matches(width: int, height: int, ratio_w: int, ratio_h: int, *, tolerance: float = 0.01) -> bool:
    """Check whether width/height comply with the desired aspect ratio within tolerance."""

    if width == 0 or height == 0 or ratio_w == 0 or ratio_h == 0:
        return False

    expected = ratio_w / ratio_h
    actual = width / height
    return abs(actual - expected) <= tolerance
