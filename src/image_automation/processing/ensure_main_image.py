"""Tools for enforcing the 主图01.jpg size constraints."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Sequence

from PIL import Image, ImageOps

_RESAMPLING = getattr(Image, "Resampling", Image)
_SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png"}

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class AdjustmentStats:
    """Aggregated result of the ensure_main_image_size operation."""

    total_folders: int = 0
    inspected_files: int = 0
    adjusted_files: int = 0
    missing_files: int = 0
    errors: int = 0
    deleted_files: int = 0


def ensure_main_image_size(
    root_dir: Path,
    *,
    target_size: int = 800,
    logger: logging.Logger | None = None,
    forbidden_terms: Sequence[str] | None = None,
    ocr_languages: str = "chi_sim+eng",
) -> AdjustmentStats:
    """Ensure each subfolder under ``root_dir`` contains a compliant 主图01.jpg.

    A compliant image must be square and both wider and taller than or equal to ``target_size``.
    Non-compliant images are resized to ``target_size`` × ``target_size`` using high-quality scaling.
    When ``forbidden_terms`` is provided, any image whose OCR 结果包含指定词语将被删除。
    """

    if logger is None:
        logger = _LOGGER

    stats = AdjustmentStats()
    if not root_dir.exists() or not root_dir.is_dir():
        logger.warning("目录不存在或不是文件夹: %s", root_dir)
        return stats

    subfolders = _iter_subfolders(root_dir)
    for folder in subfolders:
        stats.total_folders += 1
        main_image_path = folder / "主图01.jpg"
        if not main_image_path.exists():
            logger.info("未找到主图: %s", main_image_path)
            stats.missing_files += 1
        else:
            try:
                _process_main_image(
                    main_image_path,
                    target_size,
                    logger=logger,
                    stats=stats,
                    forbidden_terms=forbidden_terms,
                    ocr_languages=ocr_languages,
                )
            except Exception as exc:  # noqa: BLE001
                stats.errors += 1
                logger.error("处理失败: %s -> %s", main_image_path, exc, exc_info=exc)

        if forbidden_terms:
            try:
                for image_path in _iter_supported_images(folder):
                    if image_path == main_image_path:
                        continue
                    _process_additional_image(
                        image_path,
                        logger=logger,
                        stats=stats,
                        forbidden_terms=forbidden_terms,
                        ocr_languages=ocr_languages,
                    )
            except Exception as exc:  # noqa: BLE001
                stats.errors += 1
                logger.error("扫描目录图片失败: %s -> %s", folder, exc, exc_info=exc)

    logger.info(
        "统计: 总目录=%s, 检查图片=%s, 调整=%s, 删除=%s, 未找到=%s, 异常=%s",
        stats.total_folders,
        stats.inspected_files,
        stats.adjusted_files,
        stats.deleted_files,
        stats.missing_files,
        stats.errors,
    )
    return stats


def _iter_subfolders(root_dir: Path) -> Iterator[Path]:
    for child in sorted(root_dir.iterdir()):
        if child.is_dir():
            yield child


def _iter_supported_images(folder: Path) -> Iterator[Path]:
    for child in sorted(folder.iterdir()):
        if child.is_file() and child.suffix.lower() in _SUPPORTED_EXTENSIONS:
            yield child


def _process_main_image(
    target_path: Path,
    target_size: int,
    *,
    logger: logging.Logger,
    stats: AdjustmentStats,
    forbidden_terms: Sequence[str] | None,
    ocr_languages: str,
) -> None:
    delete_after_close = False

    with Image.open(target_path) as image:
        stats.inspected_files += 1
        if forbidden_terms and _should_delete(image, forbidden_terms, ocr_languages, logger):
            delete_after_close = True
        else:
            width, height = image.size
            if width == height and width >= target_size and height >= target_size:
                logger.info("主图尺寸合规，跳过: %s (%sx%s)", target_path, width, height)
                return

            logger.info("调整主图: %s (原尺寸 %sx%s)", target_path, width, height)

            resized = image.resize((target_size, target_size), _RESAMPLING.LANCZOS)
            resized.save(target_path, format=image.format or "JPEG")
            resized.close()
            stats.adjusted_files += 1
            logger.info("完成尺寸调整: %s -> %sx%s", target_path, target_size, target_size)
            return

    if delete_after_close:
        logger.info("主图检测到敏感词，删除: %s", target_path)
        _delete_image(target_path, logger)
        stats.deleted_files += 1


def _process_additional_image(
    target_path: Path,
    *,
    logger: logging.Logger,
    stats: AdjustmentStats,
    forbidden_terms: Sequence[str] | None,
    ocr_languages: str,
) -> None:
    delete_after_close = False
    with Image.open(target_path) as image:
        stats.inspected_files += 1
        if forbidden_terms and _should_delete(image, forbidden_terms, ocr_languages, logger):
            delete_after_close = True

    if delete_after_close:
        logger.info("检测到敏感词，删除: %s", target_path)
        _delete_image(target_path, logger)
        stats.deleted_files += 1
    else:
        logger.debug("敏感词检测通过，保留文件: %s", target_path)


_PYTESSERACT = None
_OCR_AVAILABLE: bool | None = None


def _extract_text(image: Image.Image, languages: str, logger: logging.Logger) -> str | None:
    """Run OCR on the given image and return the extracted text when possible."""

    global _PYTESSERACT, _OCR_AVAILABLE

    if _OCR_AVAILABLE is False:
        return None

    if _PYTESSERACT is None:
        try:
            import pytesseract  # type: ignore[import-not-found]
        except ImportError:
            logger.error("未安装 pytesseract 库，无法执行文字识别。")
            _OCR_AVAILABLE = False
            return None
        _PYTESSERACT = pytesseract
        _OCR_AVAILABLE = True

    assert _PYTESSERACT is not None

    ocr_source, cleanup = _prepare_image_for_ocr(image)
    try:
        text = _PYTESSERACT.image_to_string(ocr_source, lang=languages, config="--psm 6")
        return text
    except Exception as exc:  # noqa: BLE001
        tesseract_not_found_error = getattr(_PYTESSERACT, "TesseractNotFoundError", None)
        if tesseract_not_found_error and isinstance(exc, tesseract_not_found_error):
            _OCR_AVAILABLE = False
            logger.error("未找到 Tesseract 可执行文件: %s", exc)
        else:
            logger.error("OCR 识别失败: %s", exc)
        return None
    finally:
        for temp_image in cleanup:
            if temp_image is not image:
                temp_image.close()


def _prepare_image_for_ocr(image: Image.Image) -> tuple[Image.Image, list[Image.Image]]:
    """Apply light preprocessing to improve OCR accuracy."""

    cleanup: list[Image.Image] = []

    if image.mode in ("RGB", "RGBA", "L"):
        working = image.copy()
    else:
        working = image.convert("RGB")
    cleanup.append(working)

    min_dim = min(working.size)
    if min_dim < 600:
        scale = min(600 / max(min_dim, 1), 2.0)
        if scale > 1.0:
            new_size = (int(working.width * scale), int(working.height * scale))
            resized = working.resize(new_size, _RESAMPLING.LANCZOS)
            cleanup.append(resized)
            working.close()
            working = resized

    gray = working.convert("L")
    cleanup.append(gray)

    contrasted = ImageOps.autocontrast(gray)
    cleanup.append(contrasted)

    return contrasted, cleanup


def _should_delete(
    image: Image.Image,
    forbidden_terms: Sequence[str],
    languages: str,
    logger: logging.Logger,
) -> bool:
    text_content = _extract_text(image, languages, logger)
    if not text_content:
        return False
    return _contains_forbidden_terms(text_content, forbidden_terms)


def _contains_forbidden_terms(text: str, terms: Sequence[str]) -> bool:
    normalized = (
        text.replace(" ", "")
        .replace("\n", "")
        .replace("\r", "")
        .replace("\t", "")
        .replace("\u3000", "")
        .lower()
    )
    for term in terms:
        candidate = term.strip()
        if not candidate:
            continue
        if candidate.lower() in normalized:
            return True
    return False


def _delete_image(target_path: Path, logger: logging.Logger) -> None:
    try:
        target_path.unlink()
    except FileNotFoundError:
        logger.warning("文件已不存在: %s", target_path)
    except Exception as exc:  # noqa: BLE001
        logger.error("删除图片失败: %s -> %s", target_path, exc)
        raise
