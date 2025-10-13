"""处理流水线的占位实现。"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, List

from image_automation.core.config import JobConfig


def process_batch(config: JobConfig) -> List[Path]:
    """批量处理入口，占位实现返回空列表。

    后续会串联文件扫描、风格化、防检测以及报告写入。
    """

    _ = config
    return []
