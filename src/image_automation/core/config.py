"""处理任务的配置模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence, Tuple

AntiDedupMode = str  # 未来可替换为 Enum，但此阶段使用简单别名。


@dataclass(slots=True)
class WatermarkConfig:
    """微痕水印相关配置。"""

    enabled: bool
    text: str = ""
    count_range: Tuple[int, int] = (3, 5)
    opacity_range: Tuple[float, float] = (0.05, 0.15)
    rotation_range: Tuple[float, float] = (-5.0, 5.0)
    scale_range: Tuple[float, float] = (0.02, 0.05)


@dataclass(slots=True)
class AntiDedupConfig:
    """防重复检测相关配置。"""

    mode: AntiDedupMode = "none"
    allow_mirror: bool = False
    noise_strength: float = 0.01
    color_jitter_strength: float = 0.02
    rotation_range: Tuple[float, float] = (-0.5, 0.5)
    crop_margin: float = 0.01
    watermark: WatermarkConfig = field(default_factory=lambda: WatermarkConfig(enabled=False))


@dataclass(slots=True)
class StylingConfig:
    """风格化与尺寸配置。"""

    aspect_ratio: Tuple[int, int] = (1, 1)
    min_size: Tuple[int, int] = (800, 800)
    mode: str = "contain"  # contain | cover
    background_color: str = "#000000"
    border_image: Optional[Path] = None
    border_color: Optional[str] = None
    border_thickness: int = 0


@dataclass(slots=True)
class OutputConfig:
    """输出目录与冲突策略配置。"""

    output_dir: Path
    conflict_strategy: str = "rename"  # overwrite | skip | rename
    flatten_structure: bool = True


@dataclass(slots=True)
class JobConfig:
    """单次批处理任务的配置集合。"""

    sources: Sequence[Path]
    output: OutputConfig
    styling: StylingConfig
    anti_dedup: AntiDedupConfig
    allow_recursive: bool = True
    include_patterns: Sequence[str] = field(default_factory=lambda: ("*.jpg", "*.jpeg", "*.png"))
    exclude_patterns: Sequence[str] = field(default_factory=tuple)
    max_workers: int = 4
    random_seed: Optional[int] = None
    report_filename: str = "report.csv"
