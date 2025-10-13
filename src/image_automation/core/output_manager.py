"""输出写入与冲突处理模块。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from itertools import count
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image

from image_automation.core.config import OutputConfig
from image_automation.core.exceptions import ImageAutomationError, InvalidConfigurationError
from image_automation.core.models import SourceImage

LOGGER = logging.getLogger(__name__)

SUPPORTED_FORMATS = {
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".png": "PNG",
}


class ImageWriteError(ImageAutomationError):
    """输出写入失败。"""


@dataclass(slots=True)
class DestinationDecision:
    """封装输出文件决策。"""

    destination: Optional[Path]
    action: str
    note: Optional[str] = None


class OutputManager:
    """负责处理输出目录、冲突策略与图像写入。"""

    def __init__(self, config: OutputConfig) -> None:
        self.config = config
        self.output_dir = config.output_dir.resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def decide_destination(self, source: SourceImage) -> DestinationDecision:
        """根据冲突策略确定输出路径。"""

        if self.config.flatten_structure:
            relative = Path(source.source_path.name)
        else:
            relative = source.relative_path

        destination = self.output_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)

        if not destination.exists():
            return DestinationDecision(destination=destination, action="write")

        strategy = self.config.conflict_strategy
        existing_msg = f"目标已存在: {destination.name}"

        if strategy == "overwrite":
            return DestinationDecision(destination=destination, action="overwrite", note=existing_msg)
        if strategy == "skip":
            return DestinationDecision(destination=destination, action="skip", note=existing_msg)
        if strategy == "rename":
            new_destination = self._generate_renamed_path(destination)
            return DestinationDecision(
                destination=new_destination,
                action="rename",
                note=f"{existing_msg} -> 重命名为 {new_destination.name}",
            )

        raise InvalidConfigurationError(f"未知的冲突策略: {strategy}")

    def save_image(self, image: Image.Image, destination: Path) -> None:
        """将 PIL Image 保存到磁盘。"""

        suffix = destination.suffix.lower()
        image_format = SUPPORTED_FORMATS.get(suffix)
        if not image_format:
            raise ImageWriteError(f"不支持的输出格式: {suffix}")

        save_params = {"optimize": True}
        image_to_save = image
        if image_format == "JPEG":
            save_params.update(quality=95, subsampling=1)
            if image.mode != "RGB":
                image_to_save = image.convert("RGB")
        else:
            if image.mode not in {"RGB", "RGBA"}:
                image_to_save = image.convert("RGB")

        try:
            image_to_save.save(destination, format=image_format, **save_params)
        except OSError as exc:
            raise ImageWriteError(f"写入文件失败: {destination}") from exc

    def _generate_renamed_path(self, destination: Path) -> Path:
        """在 rename 策略下生成新的文件名。"""

        stem = destination.stem
        suffix = destination.suffix

        for idx in count(1):
            candidate = destination.with_name(f"{stem}_{idx}{suffix}")
            if not candidate.exists():
                return candidate

        # 理论上不会执行到此处
        return destination
