"""进度更新的数据模型。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(slots=True)
class ProgressUpdate:
    """批处理过程中的进度信息。"""

    total: int
    completed: int
    message: Optional[str] = None
    status: str = "running"
