"""图片加载与基础预处理实现。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PIL import Image, ImageOps, UnidentifiedImageError

from image_automation.core.exceptions import ImageAutomationError

LOGGER = logging.getLogger(__name__)


class ImageLoadingError(ImageAutomationError):
    """图片加载失败。"""


def load_image(path: Path) -> Image.Image:
    """加载单张图片并执行 EXIF 旋转与模式归一化。

    返回值为新的 Image 对象，调用者负责关闭。
    """

    try:
        with Image.open(path) as img:
            img.load()

            # EXIF Orientation 校正
            img = ImageOps.exif_transpose(img)

            # 统一转换到 RGB
            if img.mode != "RGB":
                img = _convert_to_rgb(img)

            return img.copy()
    except (UnidentifiedImageError, OSError) as exc:
        LOGGER.debug("无法识别图像文件 %s: %s", path, exc)
        raise ImageLoadingError(f"无法加载图像: {path}") from exc


def _convert_to_rgb(img: Image.Image) -> Image.Image:
    """将任意模式图像转换为 RGB。"""

    if img.mode in {"RGBA", "LA"}:
        # 保留 Alpha 信息，通过白色背景混合生成 RGB。
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img.convert("RGBA"), mask=img.split()[-1])
        return background

    if img.mode == "P":
        return img.convert("RGB")

    if img.mode == "CMYK":
        return img.convert("RGB")

    # 其他模式直接转换
    return img.convert("RGB")
