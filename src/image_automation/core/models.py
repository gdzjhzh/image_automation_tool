"""核心数据模型定义。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(slots=True)
class SourceImage:
    """扫描阶段得到的源图片信息。"""

    source_path: Path
    root: Path
    relative_path: Path


@dataclass(slots=True)
class FileOutcome:
    """记录单个文件的处理结果（用于报告/日志）。"""

    source_path: Path
    status: str
    output_path: Optional[Path] = None
    message: Optional[str] = None


@dataclass(slots=True)
class ProcessedAsset:
    """成功加载的图片资产。"""

    source: SourceImage
    image_mode: str
    size: tuple[int, int]
    payload: "Image.Image"


@dataclass(slots=True)
class BatchResult:
    """批处理阶段性的产出。"""

    succeeded: list[FileOutcome]
    skipped: list[FileOutcome]
    failed: list[FileOutcome]

    def all_outcomes(self) -> list[FileOutcome]:
        """返回所有结果记录，方便生成报告。"""

        return [*self.succeeded, *self.skipped, *self.failed]
