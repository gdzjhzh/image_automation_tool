"""颜色工具函数。"""

from __future__ import annotations

import re
from typing import Tuple

from image_automation.core.exceptions import InvalidConfigurationError

HEX_COLOR_RE = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def parse_hex_color(value: str) -> Tuple[int, int, int]:
    """将 HEX 字符串解析为 RGB 三元组。"""

    if not value:
        raise InvalidConfigurationError("颜色值不能为空")

    match = HEX_COLOR_RE.match(value.strip())
    if not match:
        raise InvalidConfigurationError(f"无法解析颜色值: {value}")

    hex_value = match.group(1)
    if len(hex_value) == 3:
        hex_value = "".join(ch * 2 for ch in hex_value)

    r = int(hex_value[0:2], 16)
    g = int(hex_value[2:4], 16)
    b = int(hex_value[4:6], 16)
    return r, g, b
