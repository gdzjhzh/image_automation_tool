"""Tkinter 图形界面实现。"""

from __future__ import annotations

import logging
import os
import queue
import random
import string
import threading
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from tkinter import filedialog, messagebox, ttk, font as tkfont
from typing import Callable, Dict, List, Optional

from image_automation.core.config import (
    AntiDedupConfig,
    JobConfig,
    OutputConfig,
    StylingConfig,
    TextureConfig,
    ValidationConfig,
    WatermarkConfig,
)
from image_automation.core.models import BatchResult
from image_automation.core.progress import ProgressUpdate
from image_automation.processing.pipeline import process_batch
from image_automation.processing.ensure_main_image import ensure_main_image_size
from image_automation.utils.logging import setup_logging


class TextWidgetHandler(logging.Handler):
    """Logging handler that writes records into a Tk Text widget."""

    def __init__(self, widget: tk.Text) -> None:
        super().__init__()
        self._widget = widget

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D401 - standard logging handler signature
        message = self.format(record)
        # Schedule UI update on main thread
        self._widget.after(0, self._write, message)

    def _write(self, message: str) -> None:
        if not self._widget.winfo_exists():
            return
        self._widget.configure(state=tk.NORMAL)
        self._widget.insert(tk.END, message + "\n")
        self._widget.configure(state=tk.DISABLED)
        self._widget.see(tk.END)


class AuxToolWindow(tk.Toplevel):
    """Base window for auxiliary tools."""

    def __init__(self, parent: "ImageAutomationApp", *, tool_id: str, title: str) -> None:
        super().__init__(parent)
        self._parent_app = parent
        self._tool_id = tool_id
        self.title(title)
        self.transient(parent)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._handle_close)

    def _handle_close(self) -> None:
        if not self.can_close():
            return
        try:
            self._cleanup()
        finally:
            self._parent_app._handle_tool_window_closed(self._tool_id)
            self.destroy()

    def can_close(self) -> bool:
        """Return False to keep the window open (e.g. task running)."""

        return True

    def _cleanup(self) -> None:
        """Allow subclasses to release resources before closing."""

        return


@dataclass(frozen=True)
class AuxToolDescriptor:
    """Descriptor of an auxiliary tool for dynamic registration."""

    tool_id: str
    label: str
    description: str
    factory: Callable[["ImageAutomationApp"], AuxToolWindow]


class MainImageToolWindow(AuxToolWindow):
    """Window dedicated to enforcing 主图01.jpg constraints."""

    def __init__(self, parent: "ImageAutomationApp") -> None:
        super().__init__(parent, tool_id="main_image_adjust", title="主图尺寸修正")
        self._parent_app = parent
        self._worker_thread: Optional[threading.Thread] = None
        self._task_running = False

        self.directory_var = tk.StringVar(value=str(parent.default_dir))
        self.status_var = tk.StringVar(value="待命")
        self.forbidden_terms_var = tk.StringVar(value="咸鱼,闲鱼,免责声明,价格说明")
        self.enable_forbidden_scan_var = tk.BooleanVar(value=False)

        self._build_widgets()

        self._logger = logging.getLogger(f"image_automation.gui.main_image_tool.{id(self)}")
        self._logger.setLevel(logging.INFO)
        self._logger.propagate = False
        self._log_handler = TextWidgetHandler(self.log_text)
        formatter = logging.Formatter("%(asctime)s %(levelname)s: %(message)s")
        self._log_handler.setFormatter(formatter)
        self._logger.addHandler(self._log_handler)

    def _build_widgets(self) -> None:
        container = ttk.Frame(self, padding=12)
        container.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            container,
            text="遍历所选目录的子文件夹，检查并修正每个“主图01.jpg”为 800x800。",
        ).pack(anchor=tk.W)

        path_frame = ttk.Frame(container)
        path_frame.pack(fill=tk.X, pady=(8, 4))

        ttk.Label(path_frame, text="主目录:").pack(side=tk.LEFT)
        ttk.Entry(path_frame, textvariable=self.directory_var, width=50).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 4))
        self.select_button = ttk.Button(path_frame, text="选择目录", command=self._select_directory)
        self.select_button.pack(side=tk.LEFT)

        terms_frame = ttk.Frame(container)
        terms_frame.pack(fill=tk.X, pady=(0, 8))
        ttk.Checkbutton(terms_frame, text="启用敏感词删除", variable=self.enable_forbidden_scan_var).pack(side=tk.LEFT)
        ttk.Label(terms_frame, text="敏感词(逗号分隔):").pack(side=tk.LEFT, padx=(8, 0))
        ttk.Entry(terms_frame, textvariable=self.forbidden_terms_var, width=40).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 4))

        status_frame = ttk.Frame(container)
        status_frame.pack(fill=tk.X, pady=(4, 8))
        ttk.Label(status_frame, text="状态:").pack(side=tk.LEFT)
        ttk.Label(status_frame, textvariable=self.status_var).pack(side=tk.LEFT, padx=(4, 0))

        button_frame = ttk.Frame(container)
        button_frame.pack(fill=tk.X, pady=(0, 8))
        self.run_button = ttk.Button(button_frame, text="开始执行", command=self._start_processing)
        self.run_button.pack(side=tk.LEFT)
        ttk.Button(button_frame, text="清空日志", command=self._clear_logs).pack(side=tk.LEFT, padx=(8, 0))

        log_frame = ttk.LabelFrame(container, text="日志", padding=6)
        log_frame.pack(fill=tk.BOTH, expand=True)
        self.log_text = tk.Text(log_frame, height=14, state=tk.DISABLED)
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def _select_directory(self) -> None:
        path = filedialog.askdirectory(title="选择主目录", initialdir=self.directory_var.get() or str(self._parent_app.default_dir))
        if not path:
            return
        try:
            resolved = self._parent_app._normalize_path(path)
        except ValueError as exc:
            messagebox.showerror("路径错误", str(exc))
            return
        self.directory_var.set(str(resolved))
        if resolved.is_dir():
            self._parent_app.default_dir = resolved

    def _parse_forbidden_terms(self) -> list[str]:
        raw = self.forbidden_terms_var.get().strip()
        if not raw:
            return []
        normalized = raw.replace("，", ",")
        return [item.strip() for item in normalized.split(",") if item.strip()]

    def _clear_logs(self) -> None:
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _start_processing(self) -> None:
        if self._task_running:
            messagebox.showinfo("提示", "任务正在执行中，请稍候。")
            return

        directory_value = self.directory_var.get().strip()
        if not directory_value:
            messagebox.showwarning("提示", "请先选择主目录。")
            return

        try:
            directory = self._parent_app._normalize_path(directory_value)
        except ValueError as exc:
            messagebox.showerror("路径错误", str(exc))
            return

        if not directory.exists() or not directory.is_dir():
            messagebox.showerror("路径错误", "所选路径不存在或不是文件夹。")
            return

        self._set_running(True)
        self._logger.info("开始处理目录: %s", directory)
        forbidden_terms = self._parse_forbidden_terms()
        forbidden_enabled = self.enable_forbidden_scan_var.get() and bool(forbidden_terms)
        if forbidden_enabled:
            self._logger.info("敏感词列表: %s", ", ".join(forbidden_terms))
        elif self.enable_forbidden_scan_var.get():
            self._logger.info("敏感词检测已开启但未填写列表，跳过删除。")
        else:
            self._logger.info("敏感词检测已关闭，将仅执行尺寸检查。")

        self._worker_thread = threading.Thread(
            target=self._run_task,
            args=(directory, forbidden_terms if forbidden_enabled else []),
            daemon=True,
        )
        self._worker_thread.start()

    def _run_task(self, directory: Path, forbidden_terms: list[str]) -> None:
        try:
            stats = ensure_main_image_size(
                directory,
                logger=self._logger,
                forbidden_terms=forbidden_terms or None,
            )
            summary = (
                f"完成: 共{stats.total_folders}个子目录，检查{stats.inspected_files}张，"
                f"调整{stats.adjusted_files}张，删除{stats.deleted_files}张，"
                f"缺失{stats.missing_files}张，异常{stats.errors}个。"
            )
            self._logger.info(summary)
            self.after(0, self._notify_success, summary)
        except Exception as exc:  # noqa: BLE001
            self._logger.error("执行过程中发生异常: %s", exc, exc_info=exc)
            self.after(0, self._notify_failure, str(exc))

    def _notify_success(self, summary: str) -> None:
        self._set_running(False)
        self._worker_thread = None
        self.status_var.set("完成")
        messagebox.showinfo("完成", summary, parent=self)

    def _notify_failure(self, reason: str) -> None:
        self._set_running(False)
        self._worker_thread = None
        self.status_var.set("失败")
        messagebox.showerror("错误", f"任务执行失败: {reason}", parent=self)

    def _set_running(self, running: bool) -> None:
        self._task_running = running
        state = tk.DISABLED if running else tk.NORMAL
        self.run_button.configure(state=state)
        self.select_button.configure(state=state)
        self.status_var.set("处理中..." if running else "待命")

    def can_close(self) -> bool:
        if self._task_running:
            messagebox.showwarning("提示", "任务执行中，请稍候完成后再关闭。", parent=self)
            return False
        return True

    def _cleanup(self) -> None:
        if self._worker_thread and self._worker_thread.is_alive():
            # Should not happen because can_close prevents it, but guard anyway.
            return
        self._worker_thread = None
        self._logger.removeHandler(self._log_handler)
        self._log_handler.close()


class ImageAutomationApp(tk.Tk):
    """Tkinter 主窗口。"""

    def __init__(self) -> None:
        super().__init__()
        self.title("Image Automation Tool")
        self.geometry("900x600")
        self._configure_fonts()
        setup_logging()
        self.default_dir = self._determine_default_dir()
        self.default_dir.mkdir(parents=True, exist_ok=True)

        self.sources: List[Path] = []
        self.output_dir: Optional[Path] = self.default_dir
        self._worker_thread: Optional[threading.Thread] = None
        self._event_queue: queue.Queue = queue.Queue()
        self._progress_total = 0
        self._auxiliary_tools: Dict[str, AuxToolDescriptor] = {}
        self._aux_tool_order: List[str] = []
        self._aux_tool_label_map: Dict[str, str] = {}
        self._aux_tool_selector_var: Optional[tk.StringVar] = None
        self._open_tool_windows: Dict[str, AuxToolWindow] = {}
        self._register_auxiliary_tools()

        self._build_ui()
        self.after(200, self._poll_queue)

    def _configure_fonts(self) -> None:
        """设置全局字体以支持中文。"""
        # 定义我们刚刚在WSL中安装的字体名称
        font_family = "WenQuanYi Micro Hei"
        font_size = 10

        # 获取样式对象
        style = ttk.Style(self)

        # 为常见的控件类型配置默认字体
        # 您可以根据需要添加更多控件，如 "TNotebook.Tab" 等
        style.configure("TButton", font=(font_family, font_size))
        style.configure("TLabel", font=(font_family, font_size))
        style.configure("TEntry", font=(font_family, font_size))
        style.configure("TLabelFrame", font=(font_family, font_size))
        style.configure("TLabelFrame.Label", font=(font_family, font_size, "bold")) # 标题加粗
        style.configure("TCombobox", font=(font_family, font_size))
        style.configure("TCheckbutton", font=(font_family, font_size))

        # 对于非ttk的经典控件，可能需要单独设置
        # 比如您的 tk.Listbox 和 tk.Text
        # 可以在创建它们时直接指定字体
        self.option_add("*Font", (font_family, font_size))

    def _determine_default_dir(self) -> Path:
        """根据运行平台计算默认目录。"""

        if os.name == "nt":
            return Path(r"C:\Users\hewqb\Desktop")
        return Path("/mnt/c/Users/hewqb/Desktop")

    def _normalize_path(self, raw: str) -> Path:
        """将任意平台返回的路径字符串规范化为当前系统可用的 Path。"""

        candidate = raw.strip()
        if not candidate:
            raise ValueError("路径不能为空")

        if os.name == "nt":
            return Path(candidate).expanduser().resolve()

        if len(candidate) >= 2 and candidate[1] == ":":
            win_path = PureWindowsPath(candidate)
            drive = win_path.drive.rstrip(":").lower()
            # PureWindowsPath.parts 包含 drive，自第二个元素起为层级路径
            converted = Path("/mnt", drive, *win_path.parts[1:])
            return converted.expanduser().resolve()

        return Path(candidate).expanduser().resolve()

    # ---------------------- 辅助工具管理 ---------------------- #

    def _register_auxiliary_tools(self) -> None:
        self._auxiliary_tools.clear()
        self._aux_tool_order.clear()
        self._aux_tool_label_map.clear()
        self._open_tool_windows.clear()
        self._add_aux_tool(
            AuxToolDescriptor(
                tool_id="main_image_adjust",
                label="主图尺寸修正",
                description="检查并放大每个子目录的“主图01.jpg”为 800x800。",
                factory=lambda app: MainImageToolWindow(app),
            )
        )

    def _add_aux_tool(self, descriptor: AuxToolDescriptor) -> None:
        self._auxiliary_tools[descriptor.tool_id] = descriptor
        self._aux_tool_order.append(descriptor.tool_id)

    def _handle_tool_window_closed(self, tool_id: str) -> None:
        self._open_tool_windows.pop(tool_id, None)

    def _open_tool_window(self, tool_id: str) -> None:
        if tool_id in self._open_tool_windows:
            window = self._open_tool_windows[tool_id]
            if window.winfo_exists():
                window.deiconify()
                window.lift()
                window.focus_force()
            else:
                self._open_tool_windows.pop(tool_id, None)
            return

        descriptor = self._auxiliary_tools.get(tool_id)
        if descriptor is None:
            return
        window = descriptor.factory(self)
        self._open_tool_windows[tool_id] = window

    def _open_selected_tool(self) -> None:
        if not self._aux_tool_selector_var:
            return
        label = self._aux_tool_selector_var.get()
        tool_id = self._aux_tool_label_map.get(label)
        if tool_id:
            self._open_tool_window(tool_id)

    # ---------------------- UI 构建 ---------------------- #

    def _build_ui(self) -> None:
        container = ttk.Frame(self, padding=12)
        container.pack(fill=tk.BOTH, expand=True)

        self._build_source_section(container)
        self._build_output_section(container)
        self._build_options_section(container)
        self._build_aux_tools_section(container)
        self._build_progress_section(container)

    def _build_source_section(self, parent: tk.Widget) -> None:
        frame = ttk.LabelFrame(parent, text="源目录", padding=8)
        frame.pack(fill=tk.X, expand=False)

        self.source_listbox = tk.Listbox(frame, height=4)
        self.source_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 8))

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(side=tk.RIGHT, fill=tk.Y)

        ttk.Button(btn_frame, text="添加目录", command=self._add_source).pack(fill=tk.X, pady=2)
        ttk.Button(btn_frame, text="移除选中", command=self._remove_selected_source).pack(fill=tk.X, pady=2)

    def _build_output_section(self, parent: tk.Widget) -> None:
        frame = ttk.LabelFrame(parent, text="输出配置", padding=8)
        frame.pack(fill=tk.X, pady=8)

        ttk.Label(frame, text="输出目录:").grid(row=0, column=0, sticky=tk.W)
        self.output_var = tk.StringVar(value=str(self.default_dir))
        ttk.Entry(frame, textvariable=self.output_var, width=60).grid(row=0, column=1, sticky=tk.EW, padx=4)
        ttk.Button(frame, text="选择", command=self._select_output).grid(row=0, column=2, padx=4)

        ttk.Label(frame, text="冲突策略:").grid(row=1, column=0, sticky=tk.W, pady=4)
        self.conflict_var = tk.StringVar(value="rename")
        conflict_combo = ttk.Combobox(frame, textvariable=self.conflict_var, values=("rename", "overwrite", "skip"))
        conflict_combo.grid(row=1, column=1, sticky=tk.W)

        self.recursive_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(frame, text="递归扫描子目录", variable=self.recursive_var).grid(row=1, column=2, sticky=tk.W)

        frame.columnconfigure(1, weight=1)

    def _build_options_section(self, parent: tk.Widget) -> None:
        frame = ttk.LabelFrame(parent, text="处理选项", padding=8)
        frame.pack(fill=tk.BOTH, expand=False)

        # Styling
        ttk.Label(frame, text="比例 (W:H):").grid(row=0, column=0, sticky=tk.W)
        self.ratio_var = tk.StringVar(value="1:1")
        ttk.Entry(frame, textvariable=self.ratio_var, width=8).grid(row=0, column=1, sticky=tk.W)

        ttk.Label(frame, text="最小尺寸:").grid(row=0, column=2, sticky=tk.W)
        self.min_width_var = tk.IntVar(value=800)
        self.min_height_var = tk.IntVar(value=800)
        ttk.Entry(frame, textvariable=self.min_width_var, width=6).grid(row=0, column=3, sticky=tk.W)
        ttk.Entry(frame, textvariable=self.min_height_var, width=6).grid(row=0, column=4, sticky=tk.W, padx=(4, 0))

        ttk.Label(frame, text="适配模式:").grid(row=0, column=5, sticky=tk.W)
        self.mode_var = tk.StringVar(value="contain")
        ttk.Combobox(frame, textvariable=self.mode_var, values=("contain", "cover"), width=10).grid(
            row=0, column=6, sticky=tk.W
        )

        ttk.Label(frame, text="背景色:").grid(row=1, column=0, sticky=tk.W, pady=4)
        self.bg_color_var = tk.StringVar(value="#000000")
        ttk.Entry(frame, textvariable=self.bg_color_var, width=10).grid(row=1, column=1, sticky=tk.W)

        ttk.Label(frame, text="边框颜色:").grid(row=1, column=2, sticky=tk.W)
        self.border_color_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.border_color_var, width=10).grid(row=1, column=3, sticky=tk.W)

        ttk.Label(frame, text="边框厚度:").grid(row=1, column=4, sticky=tk.W)
        self.border_thickness_var = tk.IntVar(value=0)
        ttk.Entry(frame, textvariable=self.border_thickness_var, width=6).grid(row=1, column=5, sticky=tk.W)

        ttk.Label(frame, text="边框模板:").grid(row=1, column=6, sticky=tk.W)
        self.border_image_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.border_image_var, width=18).grid(row=1, column=7, sticky=tk.W)
        ttk.Button(frame, text="选择", command=self._select_border_image).grid(row=1, column=8, padx=4)
        ttk.Button(frame, text="清除", command=self._clear_border_image).grid(row=1, column=9, padx=4)

        # Anti dedup
        ttk.Label(frame, text="防检测模式:").grid(row=2, column=0, sticky=tk.W, pady=4)
        self.antidedup_mode_var = tk.StringVar(value="heavy")
        ttk.Combobox(
            frame, textvariable=self.antidedup_mode_var, values=("none", "light", "medium", "heavy"), width=10
        ).grid(row=2, column=1, sticky=tk.W)

        self.allow_mirror_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame, text="允许随机镜像", variable=self.allow_mirror_var).grid(row=2, column=2, sticky=tk.W)

        ttk.Label(frame, text="噪点强度:").grid(row=2, column=3, sticky=tk.W)
        self.noise_var = tk.DoubleVar(value=0.025)
        ttk.Entry(frame, textvariable=self.noise_var, width=6).grid(row=2, column=4, sticky=tk.W)

        ttk.Label(frame, text="颜色扰动:").grid(row=2, column=5, sticky=tk.W)
        self.color_var = tk.DoubleVar(value=0.08)
        ttk.Entry(frame, textvariable=self.color_var, width=6).grid(row=2, column=6, sticky=tk.W)

        ttk.Label(frame, text="旋转范围:").grid(row=3, column=0, sticky=tk.W)
        self.rot_min_var = tk.DoubleVar(value=-0.5)
        self.rot_max_var = tk.DoubleVar(value=0.5)
        ttk.Entry(frame, textvariable=self.rot_min_var, width=6).grid(row=3, column=1, sticky=tk.W)
        ttk.Entry(frame, textvariable=self.rot_max_var, width=6).grid(row=3, column=2, sticky=tk.W)

        ttk.Label(frame, text="裁剪余量:").grid(row=3, column=3, sticky=tk.W)
        self.crop_var = tk.DoubleVar(value=0.05)
        ttk.Entry(frame, textvariable=self.crop_var, width=6).grid(row=3, column=4, sticky=tk.W)

        ttk.Label(frame, text="水印文本:").grid(row=3, column=5, sticky=tk.W)
        self.watermark_text_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.watermark_text_var, width=15).grid(row=3, column=6, sticky=tk.W)
        self.random_watermark_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame, text="自动随机", variable=self.random_watermark_var).grid(
            row=3, column=7, sticky=tk.W, padx=(4, 0)
        )

        ttk.Label(frame, text="水印数量:").grid(row=4, column=0, sticky=tk.W)
        self.watermark_min_var = tk.IntVar(value=15)
        self.watermark_max_var = tk.IntVar(value=25)
        ttk.Entry(frame, textvariable=self.watermark_min_var, width=6).grid(row=4, column=1, sticky=tk.W)
        ttk.Entry(frame, textvariable=self.watermark_max_var, width=6).grid(row=4, column=2, sticky=tk.W)

        ttk.Label(frame, text="水印透明度:").grid(row=4, column=3, sticky=tk.W)
        self.watermark_opacity_min_var = tk.DoubleVar(value=0.05)
        self.watermark_opacity_max_var = tk.DoubleVar(value=0.10)
        ttk.Entry(frame, textvariable=self.watermark_opacity_min_var, width=6).grid(row=4, column=4, sticky=tk.W)
        ttk.Entry(frame, textvariable=self.watermark_opacity_max_var, width=6).grid(row=4, column=5, sticky=tk.W)

        ttk.Label(frame, text="水印缩放:").grid(row=5, column=0, sticky=tk.W)
        self.watermark_scale_min_var = tk.DoubleVar(value=0.02)
        self.watermark_scale_max_var = tk.DoubleVar(value=0.05)
        ttk.Entry(frame, textvariable=self.watermark_scale_min_var, width=6).grid(row=5, column=1, sticky=tk.W)
        ttk.Entry(frame, textvariable=self.watermark_scale_max_var, width=6).grid(row=5, column=2, sticky=tk.W)

        ttk.Label(frame, text="进程数:").grid(row=4, column=6, sticky=tk.W)
        self.worker_var = tk.IntVar(value=8)
        ttk.Entry(frame, textvariable=self.worker_var, width=6).grid(row=4, column=7, sticky=tk.W)

        ttk.Label(frame, text="随机种子:").grid(row=4, column=8, sticky=tk.W, padx=(8, 0))
        self.seed_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.seed_var, width=10).grid(row=4, column=9, sticky=tk.W)

        ttk.Label(frame, text="纹理叠加:").grid(row=5, column=3, sticky=tk.W)
        self.texture_enabled_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame, text="启用", variable=self.texture_enabled_var).grid(row=5, column=4, sticky=tk.W)
        self.texture_path_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.texture_path_var, width=18).grid(row=5, column=5, sticky=tk.W)
        ttk.Button(frame, text="选择", command=self._select_texture_image).grid(row=5, column=6, padx=4)
        ttk.Button(frame, text="清除", command=self._clear_texture_image).grid(row=5, column=7, padx=4)
        ttk.Label(frame, text="透明度:").grid(row=5, column=8, sticky=tk.W)
        self.texture_opacity_var = tk.DoubleVar(value=0.1)
        ttk.Entry(frame, textvariable=self.texture_opacity_var, width=6).grid(row=5, column=9, sticky=tk.W)

        self.validation_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame, text="启用自动验证", variable=self.validation_var).grid(
            row=6, column=3, sticky=tk.W, padx=(12, 0)
        )

        ttk.Button(frame, text="启动处理", command=self._start_processing).grid(
            row=7, column=0, columnspan=3, sticky=tk.W, pady=(12, 0)
        )

        frame.columnconfigure(7, weight=1)

    def _build_aux_tools_section(self, parent: tk.Widget) -> None:
        if not self._aux_tool_order:
            return

        frame = ttk.LabelFrame(parent, text="辅助工具", padding=8)
        frame.pack(fill=tk.X, expand=False, pady=8)

        self._aux_tool_label_map = {self._auxiliary_tools[tid].label: tid for tid in self._aux_tool_order}

        if len(self._aux_tool_order) == 1:
            descriptor = self._auxiliary_tools[self._aux_tool_order[0]]
            self._aux_tool_selector_var = None
            ttk.Button(
                frame,
                text=f"{descriptor.label}...",
                command=lambda: self._open_tool_window(descriptor.tool_id),
            ).pack(side=tk.LEFT)
        else:
            ttk.Label(frame, text="选择工具:").pack(side=tk.LEFT)
            labels = list(self._aux_tool_label_map.keys())
            self._aux_tool_selector_var = tk.StringVar(value=labels[0])
            selector = ttk.Combobox(
                frame,
                textvariable=self._aux_tool_selector_var,
                state="readonly",
                values=labels,
                width=24,
            )
            selector.pack(side=tk.LEFT, padx=(4, 4))
            ttk.Button(frame, text="打开", command=self._open_selected_tool).pack(side=tk.LEFT)

    def _build_progress_section(self, parent: tk.Widget) -> None:
        frame = ttk.LabelFrame(parent, text="执行进度", padding=8)
        frame.pack(fill=tk.BOTH, expand=True, pady=(8, 0))

        self.progress_var = tk.DoubleVar(value=0.0)
        self.progress_bar = ttk.Progressbar(frame, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill=tk.X, padx=4, pady=4)

        self.log_text = tk.Text(frame, height=12, state=tk.DISABLED)
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=4)

    # ---------------------- 事件处理 ---------------------- #

    def _add_source(self) -> None:
        path = filedialog.askdirectory(title="选择源目录", initialdir=str(self.default_dir))
        if not path:
            return
        try:
            resolved = self._normalize_path(path)
        except ValueError:
            return
        if resolved in self.sources:
            return
        self.sources.append(resolved)
        self.source_listbox.insert(tk.END, str(resolved))
        if resolved.is_dir():
            self.default_dir = resolved

    def _remove_selected_source(self) -> None:
        selection = list(self.source_listbox.curselection())
        selection.reverse()
        for idx in selection:
            self.source_listbox.delete(idx)
            self.sources.pop(idx)

    def _select_output(self) -> None:
        path = filedialog.askdirectory(title="选择输出目录", initialdir=str(self.default_dir))
        if not path:
            return
        try:
            resolved = self._normalize_path(path)
        except ValueError:
            return
        self.output_dir = resolved
        self.output_var.set(str(resolved))
        if resolved.is_dir():
            self.default_dir = resolved

    def _select_border_image(self) -> None:
        filename = filedialog.askopenfilename(
            title="选择边框 PNG", filetypes=[("PNG 文件", "*.png")], initialdir=str(self.default_dir)
        )
        if not filename:
            return
        try:
            resolved = self._normalize_path(filename)
        except ValueError:
            return
        self.border_image_var.set(str(resolved))
        parent = resolved.parent
        if parent.exists():
            self.default_dir = parent

    def _clear_border_image(self) -> None:
        self.border_image_var.set("")

    def _select_texture_image(self) -> None:
        filename = filedialog.askopenfilename(
            title="选择纹理图片", filetypes=[("图像文件", "*.png *.jpg *.jpeg")], initialdir=str(self.default_dir)
        )
        if not filename:
            return
        try:
            resolved = self._normalize_path(filename)
        except ValueError:
            return
        self.texture_enabled_var.set(True)
        self.texture_path_var.set(str(resolved))
        parent = resolved.parent
        if parent.exists():
            self.default_dir = parent

    def _clear_texture_image(self) -> None:
        self.texture_path_var.set("")

    def _start_processing(self) -> None:
        if self._worker_thread and self._worker_thread.is_alive():
            messagebox.showinfo("提示", "任务正在执行中，请稍候。")
            return

        if not self.sources:
            messagebox.showwarning("提示", "请先添加至少一个源目录。")
            return

        if not self.output_dir and not self.output_var.get():
            messagebox.showwarning("提示", "请先选择输出目录。")
            return

        try:
            self.output_dir = self._normalize_path(self.output_var.get())
        except ValueError as exc:
            messagebox.showerror("配置错误", str(exc))
            return

        try:
            job = self._build_config()
        except ValueError as exc:
            messagebox.showerror("配置错误", str(exc))
            return

        self._append_log("开始执行任务...")
        self.progress_var.set(0)
        self._progress_total = 0

        self._worker_thread = threading.Thread(
            target=self._run_pipeline_thread, args=(job,), daemon=True
        )
        self._worker_thread.start()

    def _build_config(self) -> JobConfig:
        ratio_parts = self.ratio_var.get().split(":")
        if len(ratio_parts) != 2:
            raise ValueError("比例必须形如 1:1")
        ratio_w, ratio_h = int(ratio_parts[0]), int(ratio_parts[1])

        border_image = (
            self._normalize_path(self.border_image_var.get())
            if self.border_image_var.get().strip()
            else None
        )
        if border_image and not border_image.is_file():
            border_image = None

        styling = StylingConfig(
            aspect_ratio=(ratio_w, ratio_h),
            min_size=(self.min_width_var.get(), self.min_height_var.get()),
            mode=self.mode_var.get(),
            background_color=self.bg_color_var.get(),
            border_color=self.border_color_var.get() or None,
            border_thickness=max(0, self.border_thickness_var.get()),
            border_image=border_image,
        )

        watermark = WatermarkConfig(
            enabled=self.antidedup_mode_var.get() == "heavy",
            text=self._resolve_watermark_text(),
            count_range=(
                min(self.watermark_min_var.get(), self.watermark_max_var.get()),
                max(self.watermark_min_var.get(), self.watermark_max_var.get()),
            ),
            opacity_range=(
                min(self.watermark_opacity_min_var.get(), self.watermark_opacity_max_var.get()),
                max(self.watermark_opacity_min_var.get(), self.watermark_opacity_max_var.get()),
            ),
            scale_range=(
                min(self.watermark_scale_min_var.get(), self.watermark_scale_max_var.get()),
                max(self.watermark_scale_min_var.get(), self.watermark_scale_max_var.get()),
            ),
        )

        texture_path = None
        texture_value = self.texture_path_var.get().strip()
        if texture_value:
            texture_path = self._normalize_path(texture_value)
            if not texture_path.is_file():
                raise ValueError("纹理图片文件不存在")

        texture = TextureConfig(
            enabled=self.texture_enabled_var.get() and texture_path is not None,
            image_path=texture_path,
            opacity=self._clamp_opacity(self.texture_opacity_var.get()),
        )

        anti_dedup = AntiDedupConfig(
            mode=self.antidedup_mode_var.get(),
            allow_mirror=self.allow_mirror_var.get(),
            noise_strength=self.noise_var.get(),
            color_jitter_strength=self.color_var.get(),
            rotation_range=(self.rot_min_var.get(), self.rot_max_var.get()),
            crop_margin=self.crop_var.get(),
            watermark=watermark,
            texture=texture,
        )

        seed_value = self.seed_var.get().strip()
        random_seed = int(seed_value) if seed_value else None

        return JobConfig(
            sources=self.sources.copy(),
            output=OutputConfig(output_dir=self.output_dir, conflict_strategy=self.conflict_var.get()),
            styling=styling,
            anti_dedup=anti_dedup,
            validation=ValidationConfig(enabled=self.validation_var.get()),
            allow_recursive=self.recursive_var.get(),
            max_workers=max(1, self.worker_var.get()),
            random_seed=random_seed,
        )

    def _resolve_watermark_text(self) -> str:
        text = self.watermark_text_var.get().strip()
        if self.random_watermark_var.get() and not text:
            text = self._generate_random_watermark_text()
            self.watermark_text_var.set(text)
        return text

    def _generate_random_watermark_text(self) -> str:
        letters = string.ascii_uppercase
        return random.choice(letters)

    @staticmethod
    def _clamp_opacity(value: float) -> float:
        return max(0.0, min(float(value), 1.0))

    def _run_pipeline_thread(self, job: JobConfig) -> None:
        def progress_callback(update: ProgressUpdate) -> None:
            self._event_queue.put(("progress", update))

        try:
            result = process_batch(job, progress_callback=progress_callback)
            self._event_queue.put(("done", result))
        except Exception as exc:  # noqa: BLE001
            self._event_queue.put(("error", str(exc)))

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self._event_queue.get_nowait()
                if kind == "progress":
                    self._handle_progress(payload)
                elif kind == "done":
                    self._handle_done(payload)
                elif kind == "error":
                    self._handle_error(payload)
        except queue.Empty:
            pass
        finally:
            self.after(200, self._poll_queue)

    def _handle_progress(self, update: ProgressUpdate) -> None:
        if update.total:
            self._progress_total = update.total
            percent = (update.completed / update.total) * 100
            self.progress_var.set(percent)
        if update.message:
            self._append_log(update.message)

    def _handle_done(self, result: BatchResult) -> None:
        self._append_log("任务完成。")
        summary = (
            f"成功 {len(result.succeeded)} 张，跳过 {len(result.skipped)} 张，失败 {len(result.failed)} 张。\n"
            f"报告文件保存在 {self.output_dir / 'report.csv'}。"
        )
        self._append_log(summary)
        messagebox.showinfo("完成", summary)

    def _handle_error(self, message: str) -> None:
        self._append_log(f"任务异常：{message}")
        messagebox.showerror("错误", message)

    def _append_log(self, text: str) -> None:
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, text + "\n")
        self.log_text.configure(state=tk.DISABLED)
        self.log_text.see(tk.END)


def run_gui() -> None:
    """启动 GUI 应用。"""

    app = ImageAutomationApp()
    app.mainloop()

if __name__ == "__main__":
    run_gui()
