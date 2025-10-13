"""文件扫描与筛选逻辑。"""

from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path
from typing import Iterable, Iterator, Sequence

from image_automation.core.config import JobConfig
from image_automation.core.models import SourceImage

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}


def _iter_candidate_files(path: Path, recursive: bool) -> Iterator[Path]:
    """遍历路径下的所有文件。"""

    if path.is_file():
        yield path
        return

    if not path.is_dir():
        return

    iterator = path.rglob("*") if recursive else path.glob("*")
    for candidate in iterator:
        if candidate.is_file():
            yield candidate


def _matches_any(name: str, patterns: Sequence[str]) -> bool:
    lowered = name.lower()
    return any(fnmatch(lowered, pattern.lower()) for pattern in patterns)


def collect_source_images(config: JobConfig) -> list[SourceImage]:
    """根据配置扫描源文件夹，返回匹配的图片列表。"""

    collected: list[SourceImage] = []
    seen_paths: set[Path] = set()

    include_patterns = config.include_patterns or ("*.jpg", "*.jpeg", "*.png")
    exclude_patterns = config.exclude_patterns or ()

    for root in config.sources:
        resolved_root = root.resolve()
        for candidate in _iter_candidate_files(resolved_root, config.allow_recursive):
            if candidate in seen_paths:
                continue
            seen_paths.add(candidate)

            name = candidate.name
            if not _matches_any(name, include_patterns):
                continue
            if exclude_patterns and _matches_any(name, exclude_patterns):
                continue

            if candidate.suffix.lower() not in IMAGE_EXTENSIONS:
                continue

            try:
                relative = candidate.relative_to(resolved_root if resolved_root.is_dir() else resolved_root.parent)
            except ValueError:
                relative = candidate.name

            collected.append(
                SourceImage(
                    source_path=candidate,
                    root=resolved_root if resolved_root.is_dir() else resolved_root.parent,
                    relative_path=Path(relative),
                )
            )

    collected.sort(key=lambda x: str(x.source_path).lower())
    return collected
