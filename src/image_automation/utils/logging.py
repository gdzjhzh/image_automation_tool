"""日志工具占位实现。"""

from __future__ import annotations

import logging


def setup_logging(level: int = logging.INFO) -> None:
    """初始化项目日志配置。"""

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(processName)s] %(levelname)s %(name)s: %(message)s",
    )
