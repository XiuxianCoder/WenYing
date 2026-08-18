from __future__ import annotations

import ctypes
import copy
import html
import random
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk

from bs4 import BeautifulSoup

from .docx_parser import parse_docx
from .image_placement import add_external_images, apply_ai_placements, place_images_evenly
from .learning_v2 import choose_image_positions, generate_original_template, learn_template, optimize_document_text, plan_document_layout, ORIGINAL_STYLE_PRESETS
from .model_client import ModelError
from .models import DEFAULT_TEMPLATE, DocumentContent
from .renderer_v3 import render_html
from .template_store import list_templates, load_template, save_template
from .wechat_adapter import TARGETS, adapt_html
from .wechat_publisher import WeChatPublisher, WeChatPublishError
from .research_writer import write_article

ROOT = Path(__file__).resolve().parent.parent
DATA, OUTPUT = ROOT / "data", ROOT / "output"
TEMPLATES, ASSETS, SETTINGS = DATA / "templates", OUTPUT / "assets", DATA / "settings.json"
BROWSER_CAPTURE = DATA / "template_browser_capture.json"
for folder in (DATA, TEMPLATES, OUTPUT, ASSETS):
    folder.mkdir(parents=True, exist_ok=True)


class WenYingApp(tk.Tk):
    PAPER, INK, JADE, MIST = "#f5f1e8", "#242b28", "#365b52", "#dedbd1"
    FONT, BRUSH = "华文行楷", "华文行楷"

    def __init__(self) -> None:
        super().__init__()
        try:
            self.iconbitmap(default=str(DATA / "wenying.ico"))
        except Exception:
            pass
        self.tk.call("tk", "scaling", self.winfo_fpixels("1i") / 72.0)
        self.title("文映 WenYing · 公众号排版")
        self.geometry("1440x900")
        self.minsize(1280, 800)
        self.configure(bg=self.PAPER)
        self.document: DocumentContent | None = None
        self.template = dict(DEFAULT_TEMPLATE)
        self.template_images: list[str] = []
        self.unmatched_images: list[str] = []
        self.output_html = ""
        self.template_ready = False
        self.ai_generating = False
        self.wechat_publishing = False
        self.research_writing = False
        self.research_started_at = 0.0
        self.research_results: queue.Queue[tuple[str, object]] = queue.Queue()
        self.publish_results: queue.Queue[tuple[str, object]] = queue.Queue()
        self.original_mode_requested = False
        self.ai_progress_step = 0
        self.ai_started_at = 0.0
        self.current_output_target = TARGETS[0]
        self.current_original_style = ""
        self.current_original_seed = 0
        self.current_optimize_text = False
        self.saved_templates: dict[str, Path] = {}
        self.settings = self._load_settings()
        self.FONT = str(self.settings.get("ui_font", self.FONT) or self.FONT)
        self.BRUSH = self.FONT
        self._last_window_state = "normal"
        self._style()
        self._build()
        self._reload_templates()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(100, self._show_main)
        self.after(300, self._watch_window_restore)

    def report_callback_exception(self, exc_type: type[BaseException], exc_value: BaseException, exc_tb: object) -> None:
        details = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        try:
            with (DATA / "wenying_error.log").open("a", encoding="utf-8") as handle:
                handle.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] Tk callback error\n{details}\n")
        except OSError:
            pass
        try:
            messagebox.showerror("程序运行异常", f"操作发生异常，但应用会继续运行。\n\n{exc_value}", parent=self)
        except tk.TclError:
            pass

    def _load_settings(self) -> dict:
        defaults = {
            "endpoint": "https://api.openai.com/v1", "model": "gpt-4.1-mini",
            "api_key": os.getenv("OPENAI_API_KEY", ""), "wechat_appid": "",
            "wechat_secret": "", "wechat_author": "",
            "output_dir": str(OUTPUT), "ui_font": "华文行楷",
        }
        try:
            defaults.update(json.loads(SETTINGS.read_text(encoding="utf-8")))
        except Exception:
            pass
        return defaults

    def _output_dir(self) -> Path:
        raw = str(self.settings.get("output_dir", "")).strip()
        folder = Path(raw).expanduser() if raw else OUTPUT
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _safe_html_filename(self, title: str, suffix: str = "") -> str:
        value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", str(title or "").strip())
        value = re.sub(r"\s+", " ", value).strip(" .-")
        if not value:
            value = "文映文章"
        if value.upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
            value = "文章-" + value
        value = value[:100].rstrip(" .-")
        return f"{value}{suffix}.html"

    def _preview_path(self, filename: str | None = None) -> Path:
        if filename is None:
            title = self.document.title if self.document else "文映文章"
            filename = self._safe_html_filename(title, "_预览")
        return self._output_dir() / filename

    def _write_preview(self, filename: str | None = None, content: str | None = None) -> Path:
        path = self._preview_path(filename)
        path.write_text(self.output_html if content is None else content, encoding="utf-8")
        return path

    def _open_preview(self, filename: str | None = None) -> None:
        webbrowser.open(self._preview_path(filename).resolve().as_uri())

    def _style(self) -> None:
        s = ttk.Style(self); s.theme_use("clam")
        combo_font = f"{{{self.FONT}}} 11"
        self.option_add("*TCombobox*Listbox.font", combo_font)
        self.option_add("*TCombobox*Listbox.background", "#fffdf8")
        self.option_add("*TCombobox*Listbox.foreground", self.INK)
        self.option_add("*TCombobox*Listbox.selectBackground", self.JADE)
        self.option_add("*TCombobox*Listbox.selectForeground", "white")
        s.configure("TFrame", background=self.PAPER)
        s.configure("Card.TFrame", background="#fbf9f3")
        s.configure("TLabel", background=self.PAPER, foreground=self.INK, font=(self.FONT, 12))
        s.configure("Title.TLabel", font=(self.BRUSH, 30), foreground=self.JADE)
        s.configure("Sub.TLabel", foreground="#716f68", font=(self.FONT, 11))
        s.configure("Section.TLabel", background="#fbf9f3", foreground=self.JADE, font=(self.BRUSH, 17))
        s.configure("TEntry", fieldbackground="#fffdf8", foreground=self.INK, bordercolor="#cbc7bc", padding=9, font=(self.FONT, 12))
        s.configure("TCombobox", fieldbackground="#fffdf8", foreground=self.INK, padding=8, font=(self.FONT, 11))
        s.configure("Ink.TButton", background=self.JADE, foreground="white", borderwidth=0, padding=(15, 9), font=(self.FONT, 11))
        s.map("Ink.TButton", background=[("active", "#28483f")])
        s.configure("Quiet.TButton", background="#ebe7dc", foreground=self.INK, borderwidth=0, padding=(13, 8), font=(self.FONT, 11))
        s.configure("Danger.TButton", background="#8f4a42", foreground="white", borderwidth=0, padding=(14, 9), font=(self.FONT, 11))
        s.map("Danger.TButton", background=[("active", "#753a34")], foreground=[("active", "white")])
        s.configure("TCheckbutton", background=self.PAPER, foreground=self.INK, font=(self.FONT, 11))
        s.configure("WenYing.TNotebook", background="#fbf9f3", borderwidth=0, tabmargins=0)
        s.configure("WenYing.TNotebook.Tab", background="#ebe7dc", foreground=self.INK, padding=(18, 9), font=(self.FONT, 11))
        s.map("WenYing.TNotebook.Tab", background=[("selected", self.JADE)], foreground=[("selected", "white")])

    def _apply_ui_font(self, font_name: str) -> None:
        """Apply a new Chinese UI font immediately without rebuilding the window."""
        selected = font_name.strip() or "华文行楷"
        self.FONT = selected
        self.BRUSH = selected
        self._style()

        def replace_font(widget: tk.Misc) -> None:
            try:
                if isinstance(widget, ttk.Combobox):
                    current = tkfont.Font(font=widget.cget("font"))
                    widget.configure(font=(selected, abs(int(current.actual("size") or 11))))
                elif isinstance(widget, (tk.Label, tk.Text, tk.Entry, tk.Button, tk.Checkbutton)):
                    current = tkfont.Font(font=widget.cget("font"))
                    size = abs(int(current.actual("size") or 11))
                    weight = str(current.actual("weight") or "normal")
                    slant = str(current.actual("slant") or "roman")
                    extras: list[str] = []
                    if current.actual("underline"):
                        extras.append("underline")
                    if current.actual("overstrike"):
                        extras.append("overstrike")
                    widget.configure(font=(selected, size, weight, slant, *extras))
            except (tk.TclError, ValueError, TypeError):
                pass
            for child in widget.winfo_children():
                replace_font(child)

        replace_font(self)
        self.update_idletasks()

    def _build(self) -> None:
        header = ttk.Frame(self, padding=(34, 20, 34, 12)); header.pack(fill="x")
        ttk.Label(header, text="文 映", style="Title.TLabel").pack(side="left")
        ttk.Label(header, text="将文字映入风格，让排版自有气韵", style="Sub.TLabel").pack(side="left", padx=18, pady=(10, 0))
        ttk.Button(header, text="模型设置", style="Quiet.TButton", command=self._settings_dialog).pack(side="right")
        ttk.Button(header, text="公众号设置", style="Quiet.TButton", command=self._wechat_settings_dialog).pack(side="right", padx=(0, 8))
        tk.Frame(self, height=1, bg="#cbc7bc").pack(fill="x", padx=34)
        body = ttk.Frame(self, padding=(34, 20, 34, 24)); body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=6, minsize=680)
        body.columnconfigure(1, weight=5, minsize=480)
        body.rowconfigure(0, weight=1)
        left = ttk.Frame(body, style="Card.TFrame"); left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        right = ttk.Frame(body, style="Card.TFrame", padding=24); right.grid(row=0, column=1, sticky="nsew", padx=(12, 0))
        output_box = ttk.Frame(left, style="Card.TFrame", padding=(24, 10, 24, 16))
        output_box.pack(side="bottom", fill="x")
        ttk.Separator(left).pack(side="bottom", fill="x", padx=24)

        scroll_host = ttk.Frame(left, style="Card.TFrame")
        scroll_host.pack(side="top", fill="both", expand=True)
        canvas = tk.Canvas(scroll_host, bg="#fbf9f3", bd=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(scroll_host, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(fill="both", expand=True)
        scrollbar.place(relx=1.0, rely=0, relheight=1.0, anchor="ne")
        input_box = ttk.Frame(canvas, style="Card.TFrame", padding=(24, 24, 30, 10))
        input_window = canvas.create_window((0, 0), window=input_box, anchor="nw")

        def sync_scroll_layout(_event: tk.Event | None = None) -> None:
            width = max(1, canvas.winfo_width())
            canvas.itemconfigure(input_window, width=width)
            canvas.configure(scrollregion=(0, 0, width, max(input_box.winfo_reqheight(), canvas.winfo_height())))

        input_box.bind("<Configure>", sync_scroll_layout)
        canvas.bind("<Configure>", sync_scroll_layout)

        def wheel(event: tk.Event) -> None:
            canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

        canvas.bind("<Enter>", lambda _event: self.bind_all("<MouseWheel>", wheel))
        canvas.bind("<Leave>", lambda _event: self.unbind_all("<MouseWheel>"))
        self.input_canvas = canvas
        self._inputs(input_box); self._outputs(output_box); self._preview(right)

    def _inputs(self, box: ttk.Frame) -> None:
        ttk.Label(box, text="壹 · 创建原稿", style="Section.TLabel").pack(anchor="w")
        ttk.Label(
            box,
            text="选择一种原稿来源；AI 写作与导入 Word 是两条独立入口。",
            style="Sub.TLabel",
            background="#fbf9f3",
        ).pack(anchor="w", pady=(6, 8))

        source_border = tk.Frame(box, bg="#d8d3c7", bd=0)
        source_border.pack(fill="x")

        import_lane = tk.Frame(source_border, bg="#f5f1e8", bd=0)
        import_lane.pack(fill="x", padx=1, pady=(1, 0))
        import_actions = tk.Frame(import_lane, bg="#f5f1e8")
        import_actions.pack(side="right", padx=10, pady=9)
        ttk.Button(import_actions, text="选择 Word", style="Quiet.TButton", command=self._choose_word).pack(side="left")
        ttk.Button(import_actions, text="添加配套图片", style="Quiet.TButton", command=self._add_article_images).pack(side="left", padx=(6, 0))
        tk.Label(import_lane, text="已有文章排版", bg="#f5f1e8", fg=self.JADE, font=(self.FONT, 11, "bold")).pack(anchor="w", padx=12, pady=(8, 0))
        tk.Label(import_lane, text="严格保留 Word 文字与图片，再生成 HTML", bg="#f5f1e8", fg="#716f68", font=(self.FONT, 9)).pack(anchor="w", padx=12, pady=(1, 8))

        write_lane = tk.Frame(source_border, bg="#eef3ee", bd=0)
        write_lane.pack(fill="x", padx=1, pady=1)
        ttk.Button(write_lane, text="开始 AI 联网写作", style="Ink.TButton", command=self._research_writer_dialog).pack(side="right", padx=10, pady=9)
        tk.Label(write_lane, text="AI 帮我写文章", bg="#eef3ee", fg=self.JADE, font=(self.FONT, 11, "bold")).pack(anchor="w", padx=12, pady=(8, 0))
        tk.Label(write_lane, text="输入主题，搜索资料并生成一篇新原稿", bg="#eef3ee", fg="#716f68", font=(self.FONT, 9)).pack(anchor="w", padx=12, pady=(1, 8))

        self.doc_label = ttk.Label(box, text="当前原稿：尚未创建", style="Sub.TLabel", background="#fbf9f3", wraplength=430)
        self.doc_label.pack(anchor="w", pady=(9, 2))
        ttk.Separator(box).pack(fill="x", pady=16)
        ttk.Label(box, text="贰 · 选择排版方式", style="Section.TLabel").pack(anchor="w")
        ttk.Label(box, text="AI 原创适合自由设计；模板仿排用于复刻参考文章。", style="Sub.TLabel", background="#fbf9f3").pack(anchor="w", pady=(5, 9))
        self.layout_tabs = ttk.Notebook(box, style="WenYing.TNotebook")
        self.layout_tabs.pack(fill="x")
        original_tab = ttk.Frame(self.layout_tabs, style="Card.TFrame", padding=(12, 14, 12, 12))
        template_tab = ttk.Frame(self.layout_tabs, style="Card.TFrame", padding=(12, 14, 12, 8))
        self.layout_tabs.add(original_tab, text="AI 原创排版")
        self.layout_tabs.add(template_tab, text="模板仿排")
        self.layout_tabs.bind("<<NotebookTabChanged>>", self._layout_tab_changed)

        original_row = ttk.Frame(original_tab, style="Card.TFrame"); original_row.pack(fill="x")
        ttk.Label(original_row, text="AI 原创风格", style="Sub.TLabel", background="#fbf9f3").pack(side="left", padx=(0, 8))
        self.original_style = tk.StringVar(value="AI 智能匹配")
        self.original_style_combo = ttk.Combobox(original_row, textvariable=self.original_style, state="readonly", values=list(ORIGINAL_STYLE_PRESETS.keys()), width=16, font=(self.FONT, 11))
        self.original_style_combo.pack(side="left", fill="x", expand=True)
        self.original_style_combo.bind("<<ComboboxSelected>>", self._mark_original_requested)
        self.original_button = ttk.Button(original_row, text="AI 原创排版", style="Ink.TButton", command=self._original_workflow)
        self.original_button.pack(side="right", padx=(8, 0))
        option_row = ttk.Frame(original_tab, style="Card.TFrame"); option_row.pack(fill="x", pady=(9, 0))
        ttk.Label(option_row, text="随机种子", style="Sub.TLabel", background="#fbf9f3").pack(side="left")
        self.seed_var = tk.StringVar(value=str(random.randint(1, 999999)))
        ttk.Entry(option_row, textvariable=self.seed_var, width=10).pack(side="left", padx=(6, 5))
        ttk.Button(option_row, text="换一个", style="Quiet.TButton", command=self._randomize_seed).pack(side="left")
        self.optimize_text_var = tk.BooleanVar(value=False)
        optimize_row = ttk.Frame(original_tab, style="Card.TFrame")
        optimize_row.pack(fill="x", pady=(8, 0))
        ttk.Checkbutton(optimize_row, text="使用 AI 优化正文（默认关闭，开启后允许润色内容）", variable=self.optimize_text_var).pack(anchor="w")
        saved_row = ttk.Frame(template_tab, style="Card.TFrame"); saved_row.pack(fill="x", pady=(0, 7))
        saved_row.columnconfigure(0, weight=1)
        self.template_choice = tk.StringVar()
        self.template_combo = ttk.Combobox(saved_row, textvariable=self.template_choice, state="readonly", width=1, font=(self.FONT, 11))
        self.template_combo.grid(row=0, column=0, sticky="ew")
        self.template_combo.bind("<<ComboboxSelected>>", self._select_saved_template)
        ttk.Button(saved_row, text="刷新模板", style="Quiet.TButton", command=self._reload_templates).grid(row=0, column=1, padx=(6, 0))
        ttk.Button(saved_row, text="删除模板", style="Quiet.TButton", command=self._delete_selected_template).grid(row=0, column=2, padx=(6, 0))
        ttk.Label(template_tab, text="公众号文章地址", style="Sub.TLabel", background="#fbf9f3").pack(anchor="w", pady=(7, 3))
        self.url_var = tk.StringVar(); ttk.Entry(template_tab, textvariable=self.url_var).pack(fill="x")
        row = ttk.Frame(template_tab, style="Card.TFrame"); row.pack(fill="x", pady=(9, 0))
        ttk.Button(row, text="打开模板浏览器", style="Quiet.TButton", command=self._open_template_browser).pack(side="left")
        ttk.Button(row, text="添加模板截图", style="Quiet.TButton", command=self._add_template_images).pack(side="left", padx=6)
        self.shot_label = ttk.Label(row, text="0 张", style="Sub.TLabel", background="#fbf9f3"); self.shot_label.pack(side="left", padx=8)
        self.learn_button = ttk.Button(row, text="使用模板生成", style="Ink.TButton", command=self._workflow)
        self.learn_button.pack(side="right")

    def _layout_tab_changed(self, _event=None) -> None:
        if not hasattr(self, "layout_tabs"):
            return
        if self.layout_tabs.index("current") == 1:
            self.original_mode_requested = False
            if hasattr(self, "status"):
                self.status.configure(text="当前排版方式：模板仿排")
        elif hasattr(self, "status"):
            self.status.configure(text="当前排版方式：AI 原创排版")

    def _outputs(self, box: ttk.Frame) -> None:
        ttk.Label(box, text="叁 · 输出与发布", style="Section.TLabel").pack(anchor="w")
        target_row = ttk.Frame(box, style="Card.TFrame"); target_row.pack(fill="x", pady=(8, 0))
        ttk.Label(target_row, text="输出目标", style="Sub.TLabel", background="#fbf9f3").pack(side="left", padx=(0, 8))
        self.output_target = tk.StringVar(value=TARGETS[0])
        ttk.Combobox(target_row, textvariable=self.output_target, state="readonly", values=TARGETS, width=20, font=(self.FONT, 11)).pack(side="left", fill="x", expand=True)
        row = ttk.Frame(box, style="Card.TFrame"); row.pack(fill="x", pady=(10, 0))
        ttk.Button(row, text="生成预览", style="Ink.TButton", command=self._generate_preview).pack(side="left")
        ttk.Button(row, text="复制适配代码", style="Quiet.TButton", command=self._copy_html).pack(side="left", padx=6)
        ttk.Button(row, text="导出适配 HTML", style="Quiet.TButton", command=self._export_html).pack(side="left")
        publish_row = ttk.Frame(box, style="Card.TFrame"); publish_row.pack(fill="x", pady=(8, 0))
        self.publish_button = ttk.Button(publish_row, text="发布到微信公众号", style="Ink.TButton", command=self._publish_wechat_dialog)
        self.publish_button.pack(side="left")
        ttk.Button(publish_row, text="选择已有 HTML 发布", style="Quiet.TButton", command=self._choose_existing_html_for_publish).pack(side="left", padx=(7, 0))
        ttk.Label(box, text="可发布当前排版，也可直接选择以前导出的 HTML。", style="Sub.TLabel", background="#fbf9f3").pack(anchor="w", pady=(6, 0))
        status_box = tk.Frame(box, bg="#fbf9f3", height=46)
        status_box.pack(fill="x", pady=(12, 0))
        status_box.pack_propagate(False)
        self.status = ttk.Label(status_box, text="就绪", style="Sub.TLabel", background="#fbf9f3", wraplength=900, anchor="nw")
        self.status.pack(fill="both", expand=True)
        self.status.bind("<Configure>", lambda event: self.status.configure(wraplength=max(240, event.width - 4)))

    def _preview(self, box: ttk.Frame) -> None:
        ttk.Label(box, text="文章结构与模板", style="Section.TLabel").pack(anchor="w")
        self.summary = tk.Text(box, wrap="word", bd=0, highlightthickness=1, highlightbackground="#e1ddd2", padx=24, pady=22, bg="#f4f0e6", fg=self.INK, font=(self.FONT, 12), spacing3=9)
        self.summary.pack(fill="both", expand=True, pady=(14, 0)); self._summary("等待导入图文原稿与模板文章。")

    def _show_main(self) -> None:
        self.update_idletasks(); w, h = self.winfo_width(), self.winfo_height()
        self.geometry(f"{w}x{h}+{max(0,(self.winfo_screenwidth()-w)//2)}+{max(0,(self.winfo_screenheight()-h)//2)}")
        self._activate_main_window()

    def _watch_window_restore(self) -> None:
        try:
            current = self.state()
            if self._last_window_state in {"iconic", "withdrawn"} and current == "normal":
                self.after_idle(self._activate_main_window)
            self._last_window_state = current
            self.after(300, self._watch_window_restore)
        except tk.TclError:
            return

    def _activate_main_window(self) -> None:
        try:
            self.deiconify()
            self.state("normal")
            self.lift()
            self.focus_force()
            if sys.platform == "win32":
                user32 = ctypes.windll.user32
                hwnd = user32.GetAncestor(self.winfo_id(), 2) or self.winfo_id()
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                user32.BringWindowToTop(hwnd)
                user32.SetForegroundWindow(hwnd)
        except (tk.TclError, OSError):
            return

    def _center(self, win: tk.Toplevel) -> None:
        win.update_idletasks(); w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        x = self.winfo_rootx() + max(0, (self.winfo_width()-w)//2); y = self.winfo_rooty() + max(0, (self.winfo_height()-h)//2)
        win.geometry(f"{w}x{h}+{x}+{y}")

    def _reload_templates(self) -> None:
        self.saved_templates = list_templates(TEMPLATES)
        if hasattr(self, "template_combo"):
            names = list(self.saved_templates.keys())
            self.template_combo.configure(values=names)
            if names and self.template_choice.get() not in names:
                self.template_choice.set("选择本地模板")

    def _delete_selected_template(self) -> None:
        name = self.template_choice.get()
        path = self.saved_templates.get(name)
        if not path:
            messagebox.showinfo("未选择模板", "请先从下拉框选择需要删除的本地模板。", parent=self)
            return
        if not messagebox.askyesno("删除模板", f"确定删除本地模板“{name}”吗？此操作无法撤销。", parent=self):
            return
        try:
            path.unlink()
            self.template = dict(DEFAULT_TEMPLATE)
            self.template_ready = False
            self.template_choice.set("选择本地模板")
            self.learn_button.configure(text="学习并生成")
            self._reload_templates()
            self.status.configure(text=f"已删除本地模板：{name}")
            self._refresh()
        except Exception as exc:
            messagebox.showerror("删除失败", str(exc), parent=self)
    def _select_saved_template(self, _event=None) -> None:
        name = self.template_choice.get()
        path = self.saved_templates.get(name)
        if not path:
            return
        try:
            if hasattr(self, "layout_tabs"):
                self.layout_tabs.select(1)
            self.template = load_template(path)
            self.template_ready = True
            self.learn_button.configure(text="使用模板生成")
            self.status.configure(text=f"已选择本地模板：{name}；导入原稿后可直接生成")
            self._refresh()
        except Exception as exc:
            messagebox.showerror("模板读取失败", str(exc), parent=self)
    def _settings_dialog(self) -> None:
        win = tk.Toplevel(self); win.title("模型与应用设置"); win.configure(bg=self.PAPER); win.transient(self); win.attributes("-toolwindow", True)
        frame = ttk.Frame(win, padding=30); frame.pack(fill="both", expand=True)
        fields = [("模型 API 服务地址（不是公众号地址）", "endpoint"), ("模型名称", "model"), ("API Key（保存在本机）", "api_key")]; entries = {}
        for label, key in fields:
            ttk.Label(frame, text=label).pack(anchor="w", pady=(0,4)); e=ttk.Entry(frame, width=54, show="•" if key=="api_key" else ""); e.insert(0,self.settings.get(key,"")); e.pack(fill="x",pady=(0,14)); entries[key]=e
        ttk.Label(frame, text="HTML 输出目录").pack(anchor="w", pady=(0, 4))
        output_var = tk.StringVar(value=str(self.settings.get("output_dir", OUTPUT)))
        output_row = ttk.Frame(frame); output_row.pack(fill="x", pady=(0, 14))
        ttk.Entry(output_row, textvariable=output_var).pack(side="left", fill="x", expand=True)
        def choose_output_dir() -> None:
            selected = filedialog.askdirectory(parent=win, initialdir=output_var.get() or str(OUTPUT))
            if selected:
                output_var.set(selected)
        ttk.Button(output_row, text="选择目录", style="Quiet.TButton", command=choose_output_dir).pack(side="left", padx=(8, 0))
        ttk.Label(frame, text="界面字体").pack(anchor="w", pady=(0, 4))
        font_var = tk.StringVar(value=str(self.settings.get("ui_font", "华文行楷")))
        ttk.Combobox(frame, textvariable=font_var, state="readonly", values=("华文行楷", "楷体"), font=(self.FONT, 11)).pack(fill="x", pady=(0, 14))
        ttk.Label(frame, text="配置保存在项目 data/settings.json，仅供本机使用。", style="Sub.TLabel").pack(anchor="w", pady=(0,14))
        def save() -> None:
            updated = dict(self.settings)
            updated.update({k:e.get().strip() for k,e in entries.items()})
            output_path = Path(output_var.get().strip() or str(OUTPUT)).expanduser()
            try:
                output_path.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                messagebox.showerror("输出目录不可用", str(exc), parent=win); return
            updated["output_dir"] = str(output_path.resolve())
            updated["ui_font"] = font_var.get() or "华文行楷"
            font_changed = updated["ui_font"] != self.FONT
            self.settings = updated
            if "mp.weixin.qq.com" in self.settings["endpoint"]:
                messagebox.showerror("地址填写错误", "这里需要模型 API 地址，例如 https://api.openai.com/v1。公众号地址请填写在主页面。", parent=win); return
            SETTINGS.write_text(json.dumps(self.settings, ensure_ascii=False, indent=2), encoding="utf-8")
            self._apply_ui_font(updated["ui_font"])
            win.destroy()
            self.status.configure(text=f"设置已保存；输出目录：{self.settings['output_dir']}")
            if font_changed:
                messagebox.showinfo("字体已切换", f"界面字体已立即切换为“{updated['ui_font']}”。", parent=self)
        ttk.Button(frame,text="保存配置",style="Ink.TButton",command=save).pack(anchor="e")
        win.update_idletasks(); self._center(win); win.grab_set(); win.focus_force()

    def _wechat_settings_dialog(self) -> None:
        win = tk.Toplevel(self); win.title("微信公众号接口设置"); win.configure(bg=self.PAPER); win.transient(self); win.attributes("-toolwindow", True)
        frame = ttk.Frame(win, padding=30); frame.pack(fill="both", expand=True)
        fields = [("公众号 AppID", "wechat_appid"), ("公众号 AppSecret（保存在本机）", "wechat_secret"), ("默认作者", "wechat_author")]
        entries: dict[str, ttk.Entry] = {}
        for label, key in fields:
            ttk.Label(frame, text=label).pack(anchor="w", pady=(0, 4))
            entry = ttk.Entry(frame, width=56, show="•" if key == "wechat_secret" else "")
            entry.insert(0, self.settings.get(key, "")); entry.pack(fill="x", pady=(0, 14)); entries[key] = entry
        ttk.Label(
            frame,
            text="请在微信公众平台开启开发者接口，并把本机公网 IP 加入白名单。AppSecret 仅写入项目 data/settings.json。",
            style="Sub.TLabel", wraplength=480,
        ).pack(anchor="w", pady=(0, 14))
        def save() -> None:
            self.settings.update({key: entry.get().strip() for key, entry in entries.items()})
            SETTINGS.write_text(json.dumps(self.settings, ensure_ascii=False, indent=2), encoding="utf-8")
            win.destroy(); self.status.configure(text="公众号接口配置已保存")
        ttk.Button(frame, text="保存公众号配置", style="Ink.TButton", command=save).pack(anchor="e")
        win.update_idletasks(); self._center(win); win.grab_set(); win.focus_force()

    def _research_writer_dialog(self) -> None:
        if self.research_writing:
            self.status.configure(text="AI 正在联网检索并写作，请等待当前任务完成")
            return
        win = tk.Toplevel(self); win.title("AI 联网写作"); win.configure(bg=self.PAPER); win.transient(self); win.attributes("-toolwindow", True)
        frame = ttk.Frame(win, padding=28); frame.pack(fill="both", expand=True)
        topic_var = tk.StringVar()
        keywords_var = tk.StringVar()
        type_var = tk.StringVar(value="资讯综述")
        focus_var = tk.StringVar(value="自动判断")
        length_var = tk.StringVar(value="1500")
        sources_var = tk.BooleanVar(value=True)
        ttk.Label(frame, text="文章主题").pack(anchor="w", pady=(0, 4))
        ttk.Entry(frame, textvariable=topic_var, width=62).pack(fill="x", pady=(0, 12))
        ttk.Label(frame, text="搜索关键词（留空则使用主题）").pack(anchor="w", pady=(0, 4))
        ttk.Entry(frame, textvariable=keywords_var).pack(fill="x", pady=(0, 12))
        option_row = ttk.Frame(frame); option_row.pack(fill="x", pady=(0, 12))
        ttk.Label(option_row, text="文章类型").pack(side="left")
        ttk.Combobox(option_row, textvariable=type_var, state="readonly", values=("资讯综述", "新闻解读", "科普文章", "技术教程", "代码实战", "产品评测", "行业分析", "活动推文", "文化随笔", "品牌故事"), width=14, font=(self.FONT, 11)).pack(side="left", padx=(8, 20))
        ttk.Label(option_row, text="目标篇幅").pack(side="left")
        ttk.Combobox(option_row, textvariable=length_var, state="readonly", values=("800", "1200", "1500", "2000", "2500"), width=8, font=(self.FONT, 11)).pack(side="left", padx=8)
        ttk.Label(frame, text="文章侧重点（可选择，也可自行输入）").pack(anchor="w", pady=(0, 4))
        ttk.Combobox(
            frame,
            textvariable=focus_var,
            state="normal",
            values=("自动判断", "技术原理", "操作教程", "代码实战", "案例分析", "数据解读", "产品功能与使用", "行业趋势", "政策解读", "常见问题解答", "人物与故事", "活动亮点与报名转化"),
            font=(self.FONT, 11),
        ).pack(fill="x", pady=(0, 12))
        ttk.Label(frame, text="具体内容要求（可选）").pack(anchor="w", pady=(0, 4))
        requirements_text = tk.Text(frame, height=3, wrap="word", bd=1, relief="solid", bg="#fffdf8", fg=self.INK, font=(self.FONT, 11), padx=8, pady=6)
        requirements_text.pack(fill="x", pady=(0, 12))
        ttk.Label(frame, text="示例：面向初学者，包含完整 Python 代码、安装命令、运行步骤和常见错误。", style="Sub.TLabel", wraplength=520).pack(anchor="w", pady=(0, 10))
        ttk.Checkbutton(frame, text="在文章末尾保留资料来源（推荐）", variable=sources_var).pack(anchor="w", pady=(0, 12))
        ttk.Label(frame, text="应用会搜索公开网页、提取资料，再交给当前配置的模型写作。生成内容仍建议人工核查事实、日期和引用。", style="Sub.TLabel", wraplength=520).pack(anchor="w", pady=(0, 16))
        def start() -> None:
            topic = topic_var.get().strip()
            if not topic:
                messagebox.showinfo("缺少主题", "请输入要写作的文章主题。", parent=win); return
            if not self.settings.get("api_key"):
                messagebox.showinfo("缺少模型配置", "请先在“模型设置”中填写 API Key。", parent=win); return
            requirements = requirements_text.get("1.0", "end").strip()
            task_args = (topic, keywords_var.get().strip(), type_var.get(), int(length_var.get()), bool(sources_var.get()), focus_var.get().strip(), requirements)
            while not self.research_results.empty():
                try:
                    self.research_results.get_nowait()
                except queue.Empty:
                    break
            self.research_writing = True; self.research_started_at = time.monotonic()
            self.status.configure(text="正在搜索公开资料…"); win.destroy(); self._animate_research_progress()
            threading.Thread(
                target=self._research_writer_worker,
                args=task_args,
                daemon=True,
            ).start()
            self.after(150, self._poll_research_result)
        ttk.Button(frame, text="开始联网写作", style="Ink.TButton", command=start).pack(anchor="e")
        win.update_idletasks(); self._center(win); win.grab_set(); win.focus_force()

    def _animate_research_progress(self) -> None:
        if not self.research_writing:
            return
        elapsed = int(time.monotonic() - self.research_started_at)
        phases = ("搜索公开网页", "提取并清理资料", "核对多来源信息", "组织文章结构", "AI 撰写正文", "整理资料来源")
        phase = phases[min(elapsed // 10, len(phases) - 1)]
        self.status.configure(text=f"AI 联网写作：{phase}（已用时 {elapsed} 秒）")
        self._summary(f"AI 联网写作进行中\n\n当前阶段：{phase}\n已用时：{elapsed} 秒\n\n完成后文章会作为新的图文原稿载入。")
        self.after(1000, self._animate_research_progress)

    def _research_writer_worker(self, topic: str, keywords: str, article_type: str, length: int, include_sources: bool, focus: str, requirements: str) -> None:
        try:
            settings = dict(self.settings)
            document, sources = write_article(
                settings.get("endpoint", ""), settings.get("api_key", ""), settings.get("model", ""),
                topic, keywords, article_type, length, include_sources, focus, requirements,
            )
            self.research_results.put(("ok", (document, len(sources))))
        except Exception as exc:
            try:
                with (DATA / "wenying_error.log").open("a", encoding="utf-8") as handle:
                    handle.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] AI research writer error\n{traceback.format_exc()}\n")
            except OSError:
                pass
            self.research_results.put(("error", str(exc)))

    def _poll_research_result(self) -> None:
        if not self.research_writing:
            return
        try:
            kind, payload = self.research_results.get_nowait()
        except queue.Empty:
            self.after(150, self._poll_research_result)
            return
        if kind == "ok":
            document, source_count = payload
            self._research_writer_done(document, source_count)
        else:
            self._research_writer_failed(str(payload))

    def _research_writer_done(self, document: DocumentContent, source_count: int) -> None:
        self.research_writing = False
        self.document = document; self.unmatched_images = []; self.output_html = ""
        self.template = dict(DEFAULT_TEMPLATE); self.template_ready = False; self.original_mode_requested = True
        self.status.configure(text=f"联网写作完成：参考 {source_count} 个来源；可添加图片或点击 AI 原创排版")
        self._refresh()

    def _research_writer_failed(self, error: str) -> None:
        self.research_writing = False; self.status.configure(text="AI 联网写作失败")
        messagebox.showerror("联网写作失败", error, parent=self)

    def _choose_word(self) -> None:
        path=filedialog.askopenfilename(parent=self,filetypes=[("Word 文档","*.docx")])
        if not path:return
        try:
            self.document=parse_docx(path,str(ASSETS/Path(path).stem)); self.unmatched_images=[]; self._refresh(); self.status.configure(text="Word 解析完成，可继续添加正文图片")
        except Exception as exc: messagebox.showerror("解析失败",str(exc),parent=self)

    def _add_article_images(self) -> None:
        if not self.document: messagebox.showinfo("请先选择 Word","需要先导入 Word，再添加配套图片。",parent=self); return
        paths=filedialog.askopenfilenames(parent=self,filetypes=[("图片","*.png *.jpg *.jpeg *.webp *.gif")])
        if paths:
            self.unmatched_images.extend(add_external_images(self.document,list(paths),str(ASSETS/self.document.title))); self._refresh(); self.status.configure(text=f"正文图片已加入，{len(self.unmatched_images)} 张需要 AI 定位")

    def _open_template_browser(self) -> None:
        url = self.url_var.get().strip()
        if not url.startswith(("http://", "https://")):
            messagebox.showinfo("缺少模板地址", "请先填写公众号模板文章地址。", parent=self)
            return
        try:
            if BROWSER_CAPTURE.exists():
                BROWSER_CAPTURE.unlink()
            worker = Path(__file__).with_name("browser_capture.py")
            subprocess.Popen([sys.executable, str(worker), url, str(BROWSER_CAPTURE)], cwd=str(ROOT))
            self.status.configure(text="模板浏览器已打开；页面加载后点击右下角“采集此模板”")
            self.after(1500, self._poll_browser_capture)
        except Exception as exc:
            messagebox.showerror("浏览器启动失败", str(exc), parent=self)

    def _poll_browser_capture(self) -> None:
        if BROWSER_CAPTURE.exists():
            try:
                data = json.loads(BROWSER_CAPTURE.read_text(encoding="utf-8"))
                count = len(data.get("assets", []))
                self.template_ready = False
                self.status.configure(text=f"浏览器采集完成：{count} 个素材；点击生成预览将先学习模板")
                self._refresh()
                return
            except Exception:
                pass
        self.after(1500, self._poll_browser_capture)
    def _add_template_images(self) -> None:
        paths=filedialog.askopenfilenames(parent=self,filetypes=[("图片","*.png *.jpg *.jpeg *.webp")])
        if paths:self.template_images=list(paths);self.shot_label.configure(text=f"{len(paths)} 张")

    def _mark_original_requested(self, _event=None) -> None:
        if hasattr(self, "layout_tabs"):
            self.layout_tabs.select(0)
        self.original_mode_requested = True
        self.status.configure(text="原创风格已更改；点击生成预览将重新调用 AI")
    def _randomize_seed(self) -> None:
        self.seed_var.set(str(random.randint(1, 999999)))
    def _animate_ai_progress(self) -> None:
        if not self.ai_generating:
            return
        target = self.current_output_target
        if target == TARGETS[0]:
            phases = ("理解 Word 内容结构", "分析图片与文字关系", "设计标题、卡片与图文层级", "生成渐变、SVG 与动态装饰", "渲染自由网页母版", "等待模型返回最终设计")
        else:
            phases = ("理解 Word 内容结构", "分析图片与文字关系", "设计标题、卡片与图文层级", "生成自由网页母版", f"准备 {target} 的安全降级规则", "等待模型返回最终设计")
        elapsed = max(0, int(time.monotonic() - self.ai_started_at))
        phase_index = min(elapsed // 12, len(phases) - 1)
        phase = phases[phase_index]
        dots = "." * ((self.ai_progress_step % 3) + 1)
        self.original_button.configure(text=f"AI 生成中{dots}")
        wait_hint = "；模型响应较慢；首次 75 秒超时后会自动重试一次" if elapsed >= 60 else ""
        self.status.configure(text=f"AI 原创排版：{phase}{dots}（已用时 {elapsed} 秒）{wait_hint}")
        if self.document:
            self._summary(
                f"AI 原创排版生成中\n\n风格：{self.current_original_style}\n随机种子：{self.current_original_seed}\n"
                f"输出目标：{target}\n正文优化：{'已开启' if self.current_optimize_text else '关闭（严格保持原文）'}\n\n"
                f"当前阶段：{phase}{dots}\n已用时：{elapsed} 秒\n\n"
                f"原稿内容块：{len(self.document.blocks)}　图片：{len(self.document.images)}\n"
                "进度阶段不会循环；模型返回后会自动完成并打开预览。"
            )
        self.ai_progress_step += 1
        self.after(1000, self._animate_ai_progress)
    def _original_workflow(self) -> None:
        if self.ai_generating:
            self.status.configure(text="AI 正在生成，请稍候……")
            return
        if not self.document:
            messagebox.showinfo("缺少原稿", "请先导入 Word，再使用 AI 原创排版。", parent=self)
            return
        style_name = self.original_style.get().strip() or "AI 智能匹配"
        try:
            seed = int(self.seed_var.get().strip())
        except ValueError:
            seed = random.randint(1, 999999)
            self.seed_var.set(str(seed))
        optimize_text = bool(self.optimize_text_var.get())
        action = "优化正文并设计" if optimize_text else "保持原文并设计"
        self.ai_generating = True
        self.original_mode_requested = True
        self.current_original_style = style_name
        self.current_original_seed = seed
        self.current_optimize_text = optimize_text
        self.current_output_target = self.output_target.get() or TARGETS[0]
        self.ai_started_at = time.monotonic()
        self.ai_progress_step = 0
        self.original_button.configure(state="disabled", text="AI 生成中…")
        self.status.configure(text=f"AI 正在{action}“{style_name}”排版，种子 {seed}……")
        self._animate_ai_progress()
        threading.Thread(target=self._original_worker, args=(style_name, seed, optimize_text), daemon=True).start()

    def _original_worker(self, style_name: str, seed: int, optimize_text: bool) -> None:
        try:
            settings = self.settings
            working_document = copy.deepcopy(self.document)
            if optimize_text:
                optimized = optimize_document_text(settings["endpoint"], settings["api_key"], settings["model"], working_document.to_dict(), seed)
                for index, value in optimized.items():
                    if 0 <= index < len(working_document.blocks):
                        working_document.blocks[index].text = value
            template = generate_original_template(settings["endpoint"], settings["api_key"], settings["model"], working_document.to_dict(), style_name, seed)
            if self.unmatched_images:
                placements = choose_image_positions(settings["endpoint"], settings["api_key"], settings["model"], working_document.to_dict(), self.unmatched_images)
                apply_ai_placements(working_document, placements)
                placed = {str(item.get("imageId", "")) for item in placements}
                self.unmatched_images = [item for item in self.unmatched_images if item not in placed]
            place_images_evenly(working_document, self.unmatched_images)
            self.unmatched_images = []
            template["documentPlan"] = plan_document_layout(settings["endpoint"], settings["api_key"], settings["model"], working_document.to_dict(), template)
            saved_path = save_template(template, {}, TEMPLATES)
            self.template = load_template(saved_path)
            self.template["documentPlan"] = template["documentPlan"]
            self.template_ready = True
            self.output_html = render_html(working_document, self.template)
            self._write_preview()
            self.after(0, lambda: self._original_done(style_name))
        except Exception as exc:
            self.after(0, lambda error=str(exc): self._original_failed(error))
    def _original_failed(self, error: str) -> None:
        self.ai_generating = False
        self.original_button.configure(state="normal", text="AI 原创排版")
        self.status.configure(text="AI 原创排版失败")
        messagebox.showerror("原创排版失败", error, parent=self)
    def _original_done(self, style_name: str) -> None:
        self.ai_generating = False
        self.original_button.configure(state="normal", text="AI 原创排版")
        self._reload_templates()
        self.template_choice.set(str(self.template.get("name", "")))
        self.status.configure(text=f'“{style_name}”原创排版已生成并保存为本地模板')
        self._refresh()
        self._open_preview()
    def _workflow(self) -> None:
        if not self.document:
            messagebox.showinfo("缺少原稿", "请先导入 Word。", parent=self)
            return
        if self.template_ready:
            self.status.configure(text=f"正在使用本地模板“{self.template.get('name', '')}”生成文章……")
            threading.Thread(target=self._saved_template_worker, daemon=True).start()
            return
        if not self.url_var.get().strip() and not self.template_images:
            messagebox.showinfo("缺少模板", "请选择本地模板，或填写模板文章地址/添加模板截图。", parent=self)
            return
        self.status.configure(text="正在读取模板文章并学习排版，请稍候……")
        threading.Thread(target=self._workflow_worker, daemon=True).start()

    def _saved_template_worker(self) -> None:
        try:
            if self.unmatched_images:
                s = self.settings
                placements = choose_image_positions(s["endpoint"], s["api_key"], s["model"], self.document.to_dict(), self.unmatched_images)
                apply_ai_placements(self.document, placements)
                placed = {str(item.get("imageId", "")) for item in placements}
                self.unmatched_images = [item for item in self.unmatched_images if item not in placed]
            place_images_evenly(self.document, self.unmatched_images)
            self.unmatched_images = []
            s = self.settings
            self.template["documentPlan"] = plan_document_layout(s["endpoint"], s["api_key"], s["model"], self.document.to_dict(), self.template)
            self.output_html = render_html(self.document, self.template)
            self._write_preview()
            self.after(0, self._saved_template_done)
        except Exception as exc:
            self.after(0, lambda error=str(exc): (self.status.configure(text="本地模板生成失败"), messagebox.showerror("生成失败", error, parent=self)))

    def _saved_template_done(self) -> None:
        self.status.configure(text=f"已使用本地模板“{self.template.get('name', '')}”生成 HTML")
        self._refresh()
        self._open_preview()
    def _workflow_worker(self) -> None:
        try:
            s=self.settings
            capture = {}
            if BROWSER_CAPTURE.exists():
                candidate = json.loads(BROWSER_CAPTURE.read_text(encoding="utf-8"))
                if candidate.get("sourceUrl") == self.url_var.get().strip():
                    capture = candidate
            self.template=learn_template(s["endpoint"],s["api_key"],s["model"],self.url_var.get().strip(),self.template_images,capture)
            saved_path = save_template(self.template, capture, TEMPLATES)
            self.template = load_template(saved_path)
            if self.unmatched_images:
                placements=choose_image_positions(s["endpoint"],s["api_key"],s["model"],self.document.to_dict(),self.unmatched_images); apply_ai_placements(self.document,placements)
                placed={str(p.get("imageId","")) for p in placements}; self.unmatched_images=[i for i in self.unmatched_images if i not in placed]
            place_images_evenly(self.document, self.unmatched_images)
            self.unmatched_images=[]; self.template_ready=True; self.template["documentPlan"]=plan_document_layout(s["endpoint"],s["api_key"],s["model"],self.document.to_dict(),self.template); self.output_html=render_html(self.document,self.template); self._write_preview()
            self.after(0,self._workflow_done)
        except Exception as exc:
            self.after(0,lambda error=str(exc): (self.status.configure(text="学习生成失败"),messagebox.showerror("学习生成失败",error,parent=self)))

    def _workflow_done(self) -> None:
        self._reload_templates()
        self.template_choice.set(str(self.template.get("name", "")))
        self.status.configure(text="模板已保存到本地；智能配图和 HTML 生成完成")
        self._refresh()
        self._open_preview()
    def _make_html(self) -> bool:
        if not self.document: messagebox.showinfo("缺少原稿","请先导入 Word。",parent=self); return False
        self.output_html=render_html(self.document,self.template); self._write_preview(); return True

    def _generate_preview(self) -> None:
        if self.original_mode_requested or self.template.get("sourceType") == "ai_original":
            self._original_workflow()
            return
        if not self.template_ready and (self.url_var.get().strip() or BROWSER_CAPTURE.exists()):
            self._workflow()
            return
        if self._make_html(): self.status.configure(text=f"预览已生成：{self._preview_path()}"); self._open_preview()

    def _copy_html(self) -> None:
        if not self.output_html and not self._make_html(): return
        target = self.output_target.get() or TARGETS[0]
        adapted = adapt_html(self.output_html, target)
        self.clipboard_clear(); self.clipboard_append(adapted.html)
        self.status.configure(text=f"{target}已复制；" + "；".join(adapted.report))

    def _export_html(self) -> None:
        if not self.output_html and not self._make_html(): return
        target = self.output_target.get() or TARGETS[0]
        adapted = adapt_html(self.output_html, target)
        suffix = {"自由网页 HTML": "web", "135 编辑器代码": "135", "秀米兼容代码": "xiumi", "微信公众号正文": "wechat"}[target]
        path=filedialog.asksaveasfilename(parent=self,defaultextension=".html",initialdir=str(self._output_dir()),initialfile=f"{self.document.title}_{suffix}.html",filetypes=[("HTML 文件","*.html")])
        if path:
            Path(path).write_text(adapted.html,encoding="utf-8")
            self.status.configure(text=f"已导出 {target}：{path}；" + "；".join(adapted.report))

    def _choose_existing_html_for_publish(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="选择已有 HTML 发布",
            initialdir=str(self._output_dir()),
            filetypes=[("HTML 文件", "*.html *.htm"), ("所有文件", "*.*")],
        )
        if not path:
            return
        source_path = Path(path)
        try:
            raw = source_path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            try:
                raw = source_path.read_text(encoding="gb18030")
            except Exception as exc:
                messagebox.showerror("HTML 读取失败", str(exc), parent=self); return
        except OSError as exc:
            messagebox.showerror("HTML 读取失败", str(exc), parent=self); return
        if not raw.strip() or "<" not in raw:
            messagebox.showerror("HTML 无效", "所选文件中没有可识别的 HTML 内容。", parent=self); return

        soup = BeautifulSoup(raw, "html.parser")
        for image in soup.find_all("img"):
            src = str(image.get("src", "")).strip()
            if not src or src.startswith(("data:", "http://", "https://")):
                continue
            if src.startswith("file:"):
                continue
            candidate = Path(src)
            if not candidate.is_absolute():
                candidate = (source_path.parent / candidate).resolve()
            if candidate.is_file():
                image["src"] = str(candidate)
        title_node = soup.find("title") or soup.find("h1")
        title = title_node.get_text(" ", strip=True) if title_node else source_path.stem
        first_paragraph = next((node.get_text(" ", strip=True) for node in soup.find_all("p") if node.get_text(" ", strip=True)), "")
        self.status.configure(text=f"已选择已有 HTML：{source_path.name}；无需重新生成")
        self._publish_wechat_dialog(str(soup), title, first_paragraph[:100], source_path)

    def _publish_wechat_dialog(self, source_html: str | None = None, source_title: str = "", source_digest: str = "", source_path: Path | None = None) -> None:
        if self.wechat_publishing:
            self.status.configure(text="正在上传微信公众号，请等待当前任务完成")
            return
        if source_html is None:
            if not self.output_html and not self._make_html():
                return
            publish_html = self.output_html
        else:
            publish_html = source_html
        if not self.settings.get("wechat_appid") or not self.settings.get("wechat_secret"):
            messagebox.showinfo("尚未配置公众号", "请先点击右上角“公众号设置”，填写 AppID 和 AppSecret。", parent=self)
            self._wechat_settings_dialog(); return
        win = tk.Toplevel(self); win.title("发布到微信公众号"); win.configure(bg=self.PAPER); win.transient(self); win.attributes("-toolwindow", True)
        frame = ttk.Frame(win, padding=28); frame.pack(fill="both", expand=True)
        title_var = tk.StringVar(value=source_title or (self.document.title if self.document else ""))
        author_var = tk.StringVar(value=self.settings.get("wechat_author", ""))
        first_paragraph = source_digest or (next((b.text for b in self.document.blocks if b.type == "paragraph" and b.text.strip()), "") if self.document else "")
        digest_var = tk.StringVar(value=first_paragraph[:100])
        cover_var = tk.StringVar(value="")
        for label, variable in (("文章标题", title_var), ("作者", author_var), ("摘要", digest_var)):
            ttk.Label(frame, text=label).pack(anchor="w", pady=(0, 4))
            ttk.Entry(frame, textvariable=variable, width=62).pack(fill="x", pady=(0, 12))
        ttk.Label(frame, text="封面图片（不选择则使用正文第一张图）").pack(anchor="w", pady=(0, 4))
        cover_row = ttk.Frame(frame); cover_row.pack(fill="x", pady=(0, 12))
        ttk.Entry(cover_row, textvariable=cover_var).pack(side="left", fill="x", expand=True)
        def choose_cover() -> None:
            value = filedialog.askopenfilename(parent=win, filetypes=[("图片", "*.png *.jpg *.jpeg *.webp")])
            if value: cover_var.set(value)
        ttk.Button(cover_row, text="选择封面", style="Quiet.TButton", command=choose_cover).pack(side="left", padx=(8, 0))
        source_note = f"发布来源：已有 HTML（{source_path.name}），不会重新生成。" if source_path else "发布来源：当前排版结果。"
        ttk.Label(frame, text=source_note, style="Sub.TLabel", wraplength=540).pack(anchor="w", pady=(2, 5))
        ttk.Label(frame, text="可先查看微信兼容版草稿预览；保存草稿不会触达读者。直接发布与群发是不同接口，均要求公众号具备相应权限。", style="Sub.TLabel", wraplength=540).pack(anchor="w", pady=(0, 16))

        def preview_draft() -> None:
            adapted = adapt_html(publish_html, "微信公众号正文")
            cover = cover_var.get().strip()
            cover_html = ""
            if cover and Path(cover).is_file():
                cover_html = f'<img src="{Path(cover).resolve().as_uri()}" style="display:block;width:100%;max-height:360px;object-fit:cover;margin:0 0 22px">'
            elif not cover:
                cover_html = '<p style="padding:10px 14px;background:#fff7df;color:#765b20;font-size:13px">未单独选择封面，上传时将使用正文第一张图片。</p>'
            preview_html = f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>公众号草稿预览</title></head>
<body style="margin:0;padding:28px 12px;background:#ededed"><main style="box-sizing:border-box;max-width:677px;margin:auto;padding:28px 22px 48px;background:#fff">
<p style="margin:0 0 8px;color:#999;font-size:13px">微信公众号草稿预览</p><h1 style="margin:0 0 12px;font-size:26px;line-height:1.45">{html.escape(title_var.get().strip() or '未命名文章')}</h1>
<p style="margin:0 0 20px;color:#888;font-size:14px">作者：{html.escape(author_var.get().strip() or '未填写')}</p>{cover_html}{adapted.html}</main></body></html>'''
            draft_filename = self._safe_html_filename(title_var.get().strip() or "未命名文章", "_公众号草稿预览")
            path = self._write_preview(draft_filename, preview_html)
            self.status.configure(text=f"公众号草稿预览已生成：{path}")
            self._open_preview(draft_filename)

        def submit(mode: str) -> None:
            title = title_var.get().strip()
            if not title:
                messagebox.showinfo("缺少标题", "请填写文章标题。", parent=win); return
            if mode == "publish" and not messagebox.askyesno("确认直接发布", "文章将先创建草稿，随后立即提交正式发布，可能触达公众号读者且难以撤回。确定继续吗？", parent=win):
                return
            if mode == "mass" and not messagebox.askyesno("确认群发给全部用户", "此操作将尝试把图文消息群发给全部关注用户，会消耗群发次数且难以撤回。确认账号、文章和封面均无误后再继续。确定群发吗？", parent=win):
                return
            self.settings["wechat_author"] = author_var.get().strip()
            SETTINGS.write_text(json.dumps(self.settings, ensure_ascii=False, indent=2), encoding="utf-8")
            adapted = adapt_html(publish_html, "微信公众号正文")
            self.wechat_publishing = True; self.publish_button.configure(state="disabled", text="正在上传…")
            action_text = {"draft": "正在上传到微信公众号草稿箱…", "publish": "正在上传并直接发布…", "mass": "正在上传并群发给全部关注用户…"}
            self.status.configure(text=action_text[mode])
            win.destroy()
            while not self.publish_results.empty():
                try:
                    self.publish_results.get_nowait()
                except queue.Empty:
                    break
            threading.Thread(
                target=self._publish_wechat_worker,
                args=(adapted.html, title, author_var.get().strip(), digest_var.get().strip(), cover_var.get().strip(), mode),
                daemon=True,
            ).start()
            self.after(150, self._poll_publish_result)
        action_row = ttk.Frame(frame); action_row.pack(fill="x")
        action_row.columnconfigure(0, weight=1, uniform="publish_primary")
        action_row.columnconfigure(1, weight=1, uniform="publish_primary")
        ttk.Button(action_row, text="预览微信草稿", style="Quiet.TButton", command=preview_draft).grid(row=0, column=0, sticky="ew", padx=(0, 5))
        ttk.Button(action_row, text="保存到草稿箱", style="Ink.TButton", command=lambda: submit("draft")).grid(row=0, column=1, sticky="ew", padx=(5, 0))

        risk_box = tk.Frame(frame, bg="#f7ece8", highlightthickness=1, highlightbackground="#dfc5be")
        risk_box.pack(fill="x", pady=(14, 0))
        tk.Label(risk_box, text="高风险操作", bg="#f7ece8", fg="#8f4a42", font=(self.FONT, 10, "bold")).pack(anchor="w", padx=12, pady=(9, 1))
        tk.Label(risk_box, text="可能触达读者并消耗发布或群发额度，请先预览并保存草稿检查。", bg="#f7ece8", fg="#84655f", font=(self.FONT, 9)).pack(anchor="w", padx=12, pady=(0, 8))
        direct_row = tk.Frame(risk_box, bg="#f7ece8")
        direct_row.pack(fill="x", padx=11, pady=(0, 11))
        direct_row.columnconfigure(0, weight=1, uniform="publish_risk")
        direct_row.columnconfigure(1, weight=1, uniform="publish_risk")
        ttk.Button(direct_row, text="直接发布", style="Quiet.TButton", command=lambda: submit("publish")).grid(row=0, column=0, sticky="ew", padx=(0, 5))
        ttk.Button(direct_row, text="群发全部用户", style="Danger.TButton", command=lambda: submit("mass")).grid(row=0, column=1, sticky="ew", padx=(5, 0))
        win.update_idletasks(); self._center(win); win.grab_set(); win.focus_force()

    def _publish_wechat_worker(self, content: str, title: str, author: str, digest: str, cover: str, mode: str) -> None:
        try:
            publisher = WeChatPublisher(self.settings.get("wechat_appid", ""), self.settings.get("wechat_secret", ""))
            result = publisher.publish(content, title, author, digest, cover, direct_publish=mode == "publish", mass_send=mode == "mass")
            self.publish_results.put(("ok", (result.draft_media_id, result.publish_id, result.mass_msg_id)))
        except Exception as exc:
            self.publish_results.put(("error", str(exc)))

    def _poll_publish_result(self) -> None:
        if not self.wechat_publishing:
            return
        try:
            kind, payload = self.publish_results.get_nowait()
        except queue.Empty:
            self.after(150, self._poll_publish_result)
            return
        if kind == "ok":
            media_id, publish_id, mass_msg_id = payload
            self._publish_wechat_done(str(media_id), str(publish_id), str(mass_msg_id))
        else:
            self._publish_wechat_failed(str(payload))

    def _publish_wechat_done(self, media_id: str, publish_id: str, mass_msg_id: str = "") -> None:
        self.wechat_publishing = False; self.publish_button.configure(state="normal", text="发布到微信公众号")
        if mass_msg_id:
            self.status.configure(text=f"群发任务已提交：{mass_msg_id}")
            messagebox.showinfo("群发任务已提交", f"图文消息已提交给全部关注用户。\n素材 media_id：{media_id}\n群发 msg_id：{mass_msg_id}", parent=self)
        elif publish_id:
            self.status.configure(text=f"已创建草稿并提交发布，发布任务：{publish_id}")
            messagebox.showinfo("已提交发布", f"草稿已创建并提交微信异步发布。\n草稿 media_id：{media_id}\n发布任务：{publish_id}", parent=self)
        else:
            self.status.configure(text="文章已上传到微信公众号草稿箱")
            messagebox.showinfo("草稿创建成功", "文章和图片已上传到微信公众号草稿箱，请登录公众号后台检查后发布。", parent=self)

    def _publish_wechat_failed(self, error: str) -> None:
        self.wechat_publishing = False; self.publish_button.configure(state="normal", text="发布到微信公众号")
        self.status.configure(text="微信公众号上传失败")
        messagebox.showerror("公众号发布失败", error, parent=self)

    def _summary(self,text:str)->None:
        self.summary.configure(state="normal");self.summary.delete("1.0","end");self.summary.insert("1.0",text);self.summary.configure(state="disabled")

    def _refresh(self)->None:
        if not self.document:return
        placed=sum(1 for b in self.document.blocks if b.type=="image"); headings=[b.text for b in self.document.blocks if b.type=="heading"]
        t=self.template.get("styleTokens",{}); self.doc_label.configure(text=f"当前原稿：{self.document.title} · {len(self.document.images)} 张图 · 已定位 {placed} 张")
        template_name = self.template.get("name", "未命名") if self.template_ready else ("浏览器已采集，等待学习" if BROWSER_CAPTURE.exists() else "尚未学习")
        self._summary(f"原稿\n《{self.document.title}》\n内容块：{len(self.document.blocks)}　图片：{len(self.document.images)}　待定位：{len(self.unmatched_images)}\n小节：{'、'.join(headings[:8]) or '未识别'}\n\n模板\n{template_name}\n主色：{t.get('primaryColor','-')}　点色：{t.get('accentColor','-')}\n\n"+'\n'.join('· '+r for r in self.template.get('layoutRules',[])))

    def _close(self)->None:
        self.quit();self.destroy()


def run() -> None:
    WenYingApp().mainloop()









