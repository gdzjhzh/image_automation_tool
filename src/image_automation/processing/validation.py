"""图像验证指标计算工具。"""

from __future__ import annotations

from typing import Tuple

import cv2
import numpy as np
from PIL import Image


def compute_phash_distance(original: Image.Image, processed: Image.Image) -> float:
    """计算两张图片的感知哈希距离（pHash）。"""

    hash_a = _phash(original)
    hash_b = _phash(processed)
    # Hamming distance
    distance = np.count_nonzero(hash_a != hash_b)
    return float(distance)


def compute_ssim(original: Image.Image, processed: Image.Image) -> float:
    """计算两张图片的结构相似度（SSIM）。"""

    size = processed.size
    if size[0] <= 0 or size[1] <= 0:
        return 0.0

    img_a = _to_gray_array(original, size)
    img_b = _to_gray_array(processed, size)

    mu_a = img_a.mean()
    mu_b = img_b.mean()
    sigma_a_sq = ((img_a - mu_a) ** 2).mean()
    sigma_b_sq = ((img_b - mu_b) ** 2).mean()
    sigma_ab = ((img_a - mu_a) * (img_b - mu_b)).mean()

    c1 = (0.01 * 255) ** 2
    c2 = (0.03 * 255) ** 2

    numerator = (2 * mu_a * mu_b + c1) * (2 * sigma_ab + c2)
    denominator = (mu_a**2 + mu_b**2 + c1) * (sigma_a_sq + sigma_b_sq + c2)
    if denominator == 0:
        return 0.0

    value = numerator / denominator
    # Clamp to [-1, 1] to avoid slight numeric drift.
    return float(max(min(value, 1.0), -1.0))


def _phash(image: Image.Image) -> np.ndarray:
    """计算图片的 pHash 位阵列。"""

    resized = image.convert("L").resize((32, 32), Image.LANCZOS)
    array = np.asarray(resized, dtype=np.float32)
    dct = cv2.dct(array)
    low_freq = dct[:8, :8]
    median = np.median(low_freq[1:, 1:])
    return low_freq > median


def _to_gray_array(image: Image.Image, size: Tuple[int, int]) -> np.ndarray:
    """转换图片为指定尺寸的灰度数组。"""

    resized = image.convert("L").resize(size, Image.LANCZOS)
    return np.asarray(resized, dtype=np.float32)
