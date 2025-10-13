"""Tkinter GUI 入口占位实现。"""

from __future__ import annotations

import tkinter as tk


class ImageAutomationApp(tk.Tk):
    """后续构建 GUI 主窗口。"""

    def __init__(self) -> None:
        super().__init__()
        self.title("Image Automation Tool")
        self.geometry("800x600")


def run_gui() -> None:
    """启动 GUI 应用。"""

    app = ImageAutomationApp()
    app.mainloop()
