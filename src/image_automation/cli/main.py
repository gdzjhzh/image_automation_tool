"""Typer 命令行入口的占位实现。"""

from __future__ import annotations

import typer

app = typer.Typer(help="批量图片风格化与防检测处理工具。")


@app.callback()
def main() -> None:
    """主回调，后续扩展子命令。"""


if __name__ == "__main__":
    app()
