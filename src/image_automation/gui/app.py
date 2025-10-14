"""Tkinter 图形界面实现。"""

from __future__ import annotations

import os
import queue
import random
import string
import threading
import tkinter as tk
from pathlib import Path, PureWindowsPath
from tkinter import filedialog, messagebox, ttk, font as tkfont
from typing import List, Optional

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
from image_automation.utils.logging import setup_logging


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

    # ---------------------- UI 构建 ---------------------- #

    def _build_ui(self) -> None:
        container = ttk.Frame(self, padding=12)
        container.pack(fill=tk.BOTH, expand=True)

        self._build_source_section(container)
        self._build_output_section(container)
        self._build_options_section(container)
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
        self.antidedup_mode_var = tk.StringVar(value="none")
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
