import os
import re
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox
import threading
import queue
import time
import requests
import asyncio
import webbrowser
try:
    import customtkinter as ctk
except ModuleNotFoundError as exc:
    raise ModuleNotFoundError("Missing GUI dependency 'customtkinter'. Run install.bat first.") from exc

try:
    from PIL import Image, ImageTk
except ModuleNotFoundError as exc:
    raise ModuleNotFoundError("Missing GUI dependency 'Pillow'. Run install.bat first.") from exc

# 导入下载器模块
from .comic_downloader import ComicDownloader
from .comic_reader import (
    DEFAULT_READER_ZOOM_MODE,
    get_comic_source_requirement_message,
    get_format_support_notice_lines,
    get_optional_comic_support_status,
    calculate_reader_image_size,
    clamp_reader_zoom_percent,
    discover_comics,
    format_bytes,
    list_comic_pages,
    load_comic_page_image,
    normalize_reader_zoom_mode,
)
from .getinfo import GetComics
from .download import download_comics
from .getcomics_gui_helpers import (
    collect_selected_getcomics_results,
    format_getcomics_results_for_clipboard,
    remove_getcomics_results,
    upsert_getcomics_results,
)
from .gui_state import (
    DEFAULT_APPEARANCE_MODE,
    DEFAULT_GETCOMICS_RESULTS,
    DEFAULT_RENAME_API_MODEL,
    DEFAULT_RENAME_API_TIMEOUT,
    DEFAULT_RENAME_API_URL,
    DEFAULT_WINDOWS_READER_FULLSCREEN_MODE,
    build_getcomics_history_label,
    load_gui_state,
    load_getcomics_favorites_file,
    normalize_cached_getcomics_results,
    normalize_reader_scroll_fraction,
    save_getcomics_favorites_file,
    save_gui_state,
    upsert_recent_getcomics_search,
)
from .logger import log_filename, main_logger, setup_gui_logging

# DeepSeek API配置
ENV_DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()

# 设置 customtkinter 主题
ctk.set_appearance_mode("Dark")  # Modes: "System" (standard), "Dark", "Light"
ctk.set_default_color_theme("blue")  # Themes: "blue" (standard), "green", "dark-blue"

CHAPTER_FAILURE_POLICY_LABELS = {
    "continue": "继续后续章节",
    "stop": "失败即停止",
}
CHAPTER_FAILURE_POLICY_VALUES = {
    label: value for value, label in CHAPTER_FAILURE_POLICY_LABELS.items()
}
READER_ZOOM_MODE_LABELS = {
    "fit_window": "适应窗口",
    "fit_width": "适应宽度",
    "manual": "自定义缩放",
}
READER_ZOOM_MODE_VALUES = {
    label: value for value, label in READER_ZOOM_MODE_LABELS.items()
}
WINDOWS_READER_FULLSCREEN_MODE_LABELS = {
    "smooth": "顺滑全屏（推荐）",
    "exclusive": "真全屏（隐藏任务栏）",
}
WINDOWS_READER_FULLSCREEN_MODE_VALUES = {
    label: value for value, label in WINDOWS_READER_FULLSCREEN_MODE_LABELS.items()
}
READER_ZOOM_STEP = 10
SUPPORT_NOTICE_COLOR = "#d0b26f"
QUEUE_BATCH_LIMIT = 200
QUEUE_EMPTY_POLL_MS = 120
QUEUE_BUSY_POLL_MS = 25
QUEUE_PROGRESS_MIN_INTERVAL = 0.08
QUEUE_PROGRESS_MIN_DELTA = 0.4
READER_PREVIEW_REFRESH_DELAY_MS = 90
READER_FULLSCREEN_TRANSITION_DELAY_MS = 220
READER_SMOOTH_FULLSCREEN_TRANSITION_DELAY_MS = 140
READER_EXCLUSIVE_FULLSCREEN_TRANSITION_DELAY_MS = 280

class ComicDownloaderGUI(ctk.CTk):
    def __init__(self):
        super().__init__()

        # 窗口基本设置
        self.title("漫画下载器整合版 - Modern UI")
        self.geometry("1280x820")
        self.minsize(1120, 720)
        
        # 下载器实例
        self.comic_dl_downloader = ComicDownloader()
        self.getcomics_downloader = None
        self.getcomics_results_data = []
        self.getcomics_current_page = 0
        self.default_getcomics_save_dir = os.path.join(os.path.expanduser("~"), "Documents", "Comics")
        self.gui_state_path = Path(__file__).resolve().parent.parent / ".gui_state.json"
        self.gui_state = load_gui_state(self.gui_state_path, default_save_dir=self.default_getcomics_save_dir)
        settings_state = self.gui_state.get("settings", {})
        self.appearance_mode = str(
            settings_state.get("appearance_mode", DEFAULT_APPEARANCE_MODE)
        ).strip() or DEFAULT_APPEARANCE_MODE
        self.reader_windows_fullscreen_mode = str(
            settings_state.get(
                "reader_windows_fullscreen_mode",
                DEFAULT_WINDOWS_READER_FULLSCREEN_MODE,
            )
        ).strip() or DEFAULT_WINDOWS_READER_FULLSCREEN_MODE
        self.rename_api_key = str(settings_state.get("rename_api_key", "") or "").strip()
        self.rename_api_url = str(
            settings_state.get("rename_api_url", DEFAULT_RENAME_API_URL) or DEFAULT_RENAME_API_URL
        ).strip() or DEFAULT_RENAME_API_URL
        self.rename_api_model = str(
            settings_state.get("rename_api_model", DEFAULT_RENAME_API_MODEL) or DEFAULT_RENAME_API_MODEL
        ).strip() or DEFAULT_RENAME_API_MODEL
        self.rename_api_timeout = int(
            settings_state.get("rename_api_timeout", DEFAULT_RENAME_API_TIMEOUT)
            or DEFAULT_RENAME_API_TIMEOUT
        )
        ctk.set_appearance_mode(self.appearance_mode)
        self.getcomics_recent_searches = list(self.gui_state["getcomics"]["recent_searches"])
        self.getcomics_favorites = [
            (item["url"], item["title"])
            for item in self.gui_state["getcomics"]["favorites"]
        ]
        self.getcomics_download_queue = [
            (item["url"], item["title"])
            for item in self.gui_state["getcomics"]["queue_items"]
        ]
        self.getcomics_view_mode = self.gui_state["getcomics"]["view_mode"]
        self.getcomics_search_results_data = []
        self.getcomics_search_current_page = self.gui_state["getcomics"]["last_page"]
        self.getcomics_recent_search_map = {}
        self.getcomics_results_restored_from_cache = False
        self.is_updating_getcomics_history_menu = False
        self.reader_library_entries = []
        self.reader_current_entry = None
        self.reader_current_pages = []
        self.reader_current_page_index = -1
        self.reader_source_image = None
        self.reader_preview_photo = None
        self.reader_preview_canvas_image_id = None
        self.reader_preview_placeholder = "从左侧选择漫画后即可在这里翻页阅读"
        self.reader_preview_render_key = None
        reader_state = self.gui_state.get("reader", {})
        self.reader_zoom_mode = normalize_reader_zoom_mode(
            reader_state.get("zoom_mode", DEFAULT_READER_ZOOM_MODE)
        )
        self.reader_zoom_percent = clamp_reader_zoom_percent(
            reader_state.get("zoom_percent", 100)
        )
        self.reader_focus_mode = bool(reader_state.get("focus_mode", False))
        self.reader_fullscreen_mode = False
        self.reader_focus_mode_before_fullscreen = self.reader_focus_mode
        self.reader_window_state_before_fullscreen = None
        self.reader_window_geometry_before_fullscreen = ""
        self.reader_preview_refresh_after_id = None
        self.reader_pending_preview_refresh = None
        self.reader_fullscreen_transition_after_id = None
        self.reader_fullscreen_transition_in_progress = False
        self.reader_scroll_positions = {}
        active_reader_path = str(reader_state.get("active_path") or "").strip()
        active_reader_page = max(0, int(reader_state.get("active_page", 0) or 0))
        if active_reader_path and active_reader_page > 0:
            self.reader_scroll_positions[(active_reader_path, active_reader_page - 1)] = (
                normalize_reader_scroll_fraction(reader_state.get("scroll_x")),
                normalize_reader_scroll_fraction(reader_state.get("scroll_y")),
            )
        self.queue_check_after_id = None
        self.queue_throttle_lock = threading.Lock()
        self._queued_progress_state = {"timestamp": 0.0, "value": None}
        self._queued_info_state = {}
        
        # 队列用于线程间通信
        self.queue = queue.Queue()
        
        # 设置 GUI 日志处理程序
        setup_gui_logging(self.queue)
        
        # 配置网格布局 (1x2)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        
        # ========== 侧边栏 (Sidebar) ==========
        self.sidebar_frame = ctk.CTkFrame(self, width=140, corner_radius=0)
        self.sidebar_frame.grid(row=0, column=0, rowspan=2, sticky="nsew")
        self.sidebar_frame.grid_rowconfigure(9, weight=1)
        
        self.logo_label = ctk.CTkLabel(self.sidebar_frame, text="漫画下载器", font=ctk.CTkFont(size=20, weight="bold"))
        self.logo_label.grid(row=0, column=0, padx=20, pady=(20, 10))
        
        self.sidebar_button_1 = ctk.CTkButton(self.sidebar_frame, text="主菜单", command=lambda: self.select_frame_by_name("home"))
        self.sidebar_button_1.grid(row=1, column=0, padx=20, pady=10)
        
        self.sidebar_button_2 = ctk.CTkButton(self.sidebar_frame, text="Comic-DL下载", command=lambda: self.select_frame_by_name("comic_dl"))
        self.sidebar_button_2.grid(row=2, column=0, padx=20, pady=10)
        
        self.sidebar_button_3 = ctk.CTkButton(self.sidebar_frame, text="GetComics下载", command=lambda: self.select_frame_by_name("getcomics"))
        self.sidebar_button_3.grid(row=3, column=0, padx=20, pady=10)
        
        self.sidebar_button_4 = ctk.CTkButton(self.sidebar_frame, text="转换为CBZ", command=lambda: self.select_frame_by_name("convert"))
        self.sidebar_button_4.grid(row=4, column=0, padx=20, pady=10)
        
        self.sidebar_button_5 = ctk.CTkButton(self.sidebar_frame, text="漫画重命名", command=lambda: self.select_frame_by_name("rename"))
        self.sidebar_button_5.grid(row=5, column=0, padx=20, pady=10)
        
        self.sidebar_button_6 = ctk.CTkButton(self.sidebar_frame, text="漫画阅读器", command=lambda: self.select_frame_by_name("reader"))
        self.sidebar_button_6.grid(row=6, column=0, padx=20, pady=10)

        self.sidebar_button_7 = ctk.CTkButton(self.sidebar_frame, text="运行日志", command=lambda: self.select_frame_by_name("logs"))
        self.sidebar_button_7.grid(row=7, column=0, padx=20, pady=10)

        self.sidebar_button_8 = ctk.CTkButton(self.sidebar_frame, text="设置", command=lambda: self.select_frame_by_name("settings"))
        self.sidebar_button_8.grid(row=8, column=0, padx=20, pady=10)

        self.appearance_mode_label = ctk.CTkLabel(self.sidebar_frame, text="外观模式:", anchor="w")
        self.appearance_mode_label.grid(row=10, column=0, padx=20, pady=(10, 0))
        self.appearance_mode_optionemenu = ctk.CTkOptionMenu(self.sidebar_frame, values=["Light", "Dark", "System"],
                                                                       command=self.change_appearance_mode_event)
        self.appearance_mode_optionemenu.grid(row=11, column=0, padx=20, pady=(10, 20))
        self.appearance_mode_optionemenu.set(self.appearance_mode)

        # ========== 内容区域 (Content Frames) ==========
        # 1. 主菜单 (Home)
        self.home_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.home_frame.grid_columnconfigure((0, 1), weight=1)
        self.home_frame.grid_rowconfigure(5, weight=1)
        
        self.home_title = ctk.CTkLabel(self.home_frame, text="漫画下载器整合版", font=ctk.CTkFont(size=28, weight="bold"))
        self.home_title.grid(row=0, column=0, columnspan=2, padx=20, pady=(32, 12))
        
        self.home_subtitle = ctk.CTkLabel(
            self.home_frame,
            text="把在线下载、本地整理、格式转换和阅读放到同一个界面里，减少来回切工具的打断感。",
            font=ctk.CTkFont(size=16),
        )
        self.home_subtitle.grid(row=1, column=0, columnspan=2, padx=20, pady=(0, 18))

        self.home_intro_frame = ctk.CTkFrame(
            self.home_frame,
            corner_radius=18,
            border_width=1,
            border_color="#325a78",
        )
        self.home_intro_frame.grid(row=2, column=0, columnspan=2, padx=20, pady=(0, 8), sticky="ew")
        self.home_intro_frame.grid_columnconfigure(0, weight=1)

        self.home_intro_title = ctk.CTkLabel(
            self.home_intro_frame,
            text="一站式漫画工作流",
            font=ctk.CTkFont(size=20, weight="bold"),
            anchor="w",
        )
        self.home_intro_title.grid(row=0, column=0, padx=20, pady=(18, 8), sticky="ew")

        self.home_intro_desc = ctk.CTkLabel(
            self.home_intro_frame,
            text=(
                "推荐流程：在线下载 -> 转换为 CBZ -> 进入阅读空间 -> AI 统一命名\n"
                "支持图片文件夹、CBZ/ZIP、PDF、7z，以及安装外部解包工具后的 CBR/RAR。"
            ),
            justify="left",
            anchor="w",
            font=ctk.CTkFont(size=13),
        )
        self.home_intro_desc.grid(row=1, column=0, padx=20, pady=(0, 12), sticky="ew")

        self.home_quick_actions = ctk.CTkFrame(self.home_intro_frame, fg_color="transparent")
        self.home_quick_actions.grid(row=2, column=0, padx=20, pady=(0, 18), sticky="ew")
        self.home_quick_actions.grid_columnconfigure((0, 1, 2), weight=1)

        ctk.CTkButton(
            self.home_quick_actions,
            text="开始抓取漫画",
            command=lambda: self.select_frame_by_name("comic_dl"),
        ).grid(row=0, column=0, padx=(0, 8), sticky="ew")
        ctk.CTkButton(
            self.home_quick_actions,
            text="搜索 GetComics",
            command=lambda: self.select_frame_by_name("getcomics"),
        ).grid(row=0, column=1, padx=8, sticky="ew")
        ctk.CTkButton(
            self.home_quick_actions,
            text="进入阅读空间",
            command=lambda: self.select_frame_by_name("reader"),
        ).grid(row=0, column=2, padx=(8, 0), sticky="ew")

        # 功能卡片
        self.card_1 = self.create_feature_card(
            self.home_frame,
            "Comic-DL 下载",
            "支持多种在线漫画网站的爬取和下载，\n包括章节选择和图片自动打包。",
            3,
            0,
            button_text="开始抓取",
            command=lambda: self.select_frame_by_name("comic_dl"),
        )
        self.card_2 = self.create_feature_card(
            self.home_frame,
            "GetComics 下载",
            "适合搜索和下载美漫，支持分页结果、收藏、队列和 aria2c 加速。",
            3,
            1,
            button_text="去搜索",
            command=lambda: self.select_frame_by_name("getcomics"),
        )
        self.card_3 = self.create_feature_card(
            self.home_frame,
            "转换为 CBZ",
            "将图片文件夹、ZIP、PDF、7z 以及配置工具后的 CBR/RAR 转成标准 CBZ。",
            4,
            0,
            button_text="开始转换",
            command=lambda: self.select_frame_by_name("convert"),
        )
        self.card_4 = self.create_feature_card(
            self.home_frame,
            "漫画阅读器",
            "独立阅读标签页，支持翻页、缩放、适应宽度和专注阅读模式。",
            4,
            1,
            button_text="打开阅读",
            command=lambda: self.select_frame_by_name("reader"),
        )
        self.card_5 = self.create_feature_card(
            self.home_frame,
            "AI 漫画重命名",
            "利用 DeepSeek AI 智能分析文件名，统一标题、卷号、期号和命名结构。",
            5,
            0,
            button_text="整理文件",
            command=lambda: self.select_frame_by_name("rename"),
        )
        self.card_6 = self.create_feature_card(
            self.home_frame,
            "运行日志与维护",
            "下载状态、详细日志和最近错误会集中到独立日志标签页，方便排查问题和反馈维护。",
            5,
            1,
            button_text="查看日志",
            command=lambda: self.select_frame_by_name("logs"),
        )
        
        # 2. Comic-DL 下载
        self.comic_dl_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.setup_comic_dl_frame()
        
        # 3. GetComics 下载
        self.getcomics_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.setup_getcomics_frame()
        
        # 4. 转换 CBZ
        self.convert_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.setup_convert_frame()
        
        # 5. 重命名
        self.rename_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.setup_rename_frame()
        self.reader_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.setup_reader_frame()
        self.logs_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.setup_logs_frame()
        self.settings_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.setup_settings_frame()
        self.restore_getcomics_state()

        # 默认显示 Home
        self.select_frame_by_name("home")
        
        # 线程控制
        self.download_thread = None
        self.getcomics_thread = None
        self.is_cancelled = False
        self.is_getcomics_cancelled = False
        
        # 绑定事件
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.bind("<Prior>", lambda event: self.handle_reader_shortcut("prev"))
        self.bind("<Next>", lambda event: self.handle_reader_shortcut("next"))
        self.bind("<Home>", lambda event: self.handle_reader_shortcut("first"))
        self.bind("<End>", lambda event: self.handle_reader_shortcut("last"))
        self.bind("<Left>", lambda event: self.handle_reader_shortcut("prev"))
        self.bind("<Right>", lambda event: self.handle_reader_shortcut("next"))
        self.bind("<F11>", lambda event: self.handle_reader_shortcut("toggle_fullscreen"))
        self.bind("<Escape>", lambda event: self.handle_reader_shortcut("escape"))
        self.restore_reader_state()
        
        # 定期检查队列
        self.check_queue()
        
        # 初始日志
        main_logger.info("现代版 GUI 已经启动，基于 CustomTkinter")
        self.log("提示: 下载状态和详细日志已移到“运行日志”标签页，方便维护和查看报错。")
        if self.getcomics_results_restored_from_cache and self.getcomics_results_data:
            self.log(f"已恢复上次 GetComics 缓存结果，共 {len(self.getcomics_results_data)} 项；重新搜索后可继续翻页")

    def setup_comic_dl_frame(self):
        self.comic_dl_frame.grid_columnconfigure(0, weight=1)
        
        # URL 输入
        url_group = ctk.CTkFrame(self.comic_dl_frame)
        url_group.grid(row=0, column=0, padx=20, pady=10, sticky="ew")
        url_group.grid_columnconfigure(1, weight=1)
        
        ctk.CTkLabel(url_group, text="漫画 URL:").grid(row=0, column=0, padx=10, pady=10)
        self.url_entry = ctk.CTkEntry(url_group, placeholder_text="请输入漫画主页链接...")
        self.url_entry.grid(row=0, column=1, padx=10, pady=10, sticky="ew")
        self.url_entry.bind("<KeyRelease>", self.update_site_status)
        self.url_entry.bind("<FocusOut>", self.update_site_status)
        self.fetch_button = ctk.CTkButton(url_group, text="获取信息", command=self.fetch_comic_info, width=100)
        self.fetch_button.grid(row=0, column=2, padx=10, pady=10)

        # 站点识别与模块说明
        site_group = ctk.CTkFrame(self.comic_dl_frame)
        site_group.grid(row=1, column=0, padx=20, pady=(0, 10), sticky="ew")
        site_group.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(site_group, text="站点模块:").grid(row=0, column=0, padx=10, pady=(10, 5), sticky="nw")
        self.site_status_label = ctk.CTkLabel(site_group, text="等待输入 URL", anchor="w", justify="left")
        self.site_status_label.grid(row=0, column=1, padx=10, pady=(10, 5), sticky="ew")

        ctk.CTkLabel(site_group, text="当前支持:").grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nw")
        self.supported_sites_label = ctk.CTkLabel(
            site_group,
            text=self.comic_dl_downloader.get_supported_sites_summary(),
            anchor="w",
            justify="left",
            wraplength=780,
        )
        self.supported_sites_label.grid(row=1, column=1, padx=10, pady=(0, 10), sticky="ew")

        ctk.CTkLabel(site_group, text="站点配置:").grid(row=2, column=0, padx=10, pady=(0, 10), sticky="nw")
        site_config_group = ctk.CTkFrame(site_group, fg_color="transparent")
        site_config_group.grid(row=2, column=1, padx=10, pady=(0, 10), sticky="ew")
        site_config_group.grid_columnconfigure(13, weight=1)

        site_keys = [site.key for site in self.comic_dl_downloader.get_supported_sites()]
        self.site_override_var = tk.StringVar(value=site_keys[0] if site_keys else "")
        self.site_override_menu = ctk.CTkOptionMenu(
            site_config_group,
            values=site_keys or [""],
            variable=self.site_override_var,
            command=self.on_site_override_selected,
            width=180,
        )
        self.site_override_menu.grid(row=0, column=0, padx=(0, 10), pady=0, sticky="w")

        ctk.CTkLabel(site_config_group, text="覆盖并发:").grid(row=0, column=1, padx=(0, 6), pady=0, sticky="w")
        self.site_override_workers_entry = ctk.CTkEntry(site_config_group, width=70)
        self.site_override_workers_entry.grid(row=0, column=2, padx=(0, 10), pady=0, sticky="w")

        ctk.CTkLabel(site_config_group, text="重试次数:").grid(row=0, column=3, padx=(0, 6), pady=0, sticky="w")
        self.site_override_retries_entry = ctk.CTkEntry(site_config_group, width=70)
        self.site_override_retries_entry.grid(row=0, column=4, padx=(0, 10), pady=0, sticky="w")

        ctk.CTkLabel(site_config_group, text="间隔(s):").grid(row=0, column=5, padx=(0, 6), pady=0, sticky="w")
        self.site_override_delay_entry = ctk.CTkEntry(site_config_group, width=80)
        self.site_override_delay_entry.grid(row=0, column=6, padx=(0, 10), pady=0, sticky="w")

        ctk.CTkLabel(site_config_group, text="超时(s):").grid(row=0, column=7, padx=(0, 6), pady=0, sticky="w")
        self.site_override_timeout_entry = ctk.CTkEntry(site_config_group, width=80)
        self.site_override_timeout_entry.grid(row=0, column=8, padx=(0, 10), pady=0, sticky="w")

        ctk.CTkLabel(site_config_group, text="失败策略:").grid(row=0, column=9, padx=(0, 6), pady=0, sticky="w")
        self.site_failure_policy_var = tk.StringVar(value=CHAPTER_FAILURE_POLICY_LABELS["continue"])
        self.site_failure_policy_menu = ctk.CTkOptionMenu(
            site_config_group,
            values=list(CHAPTER_FAILURE_POLICY_VALUES.keys()),
            variable=self.site_failure_policy_var,
            width=130,
        )
        self.site_failure_policy_menu.grid(row=0, column=10, padx=(0, 10), pady=0, sticky="w")

        self.save_site_override_button = ctk.CTkButton(
            site_config_group,
            text="保存",
            command=self.save_site_override_settings,
            width=80,
        )
        self.save_site_override_button.grid(row=0, column=11, padx=(0, 8), pady=0, sticky="w")

        self.reset_site_override_button = ctk.CTkButton(
            site_config_group,
            text="恢复默认",
            command=self.reset_site_override_settings,
            width=90,
            fg_color="gray",
            hover_color="#3d3d3d",
        )
        self.reset_site_override_button.grid(row=0, column=12, padx=(0, 10), pady=0, sticky="w")

        self.site_override_status_label = ctk.CTkLabel(
            site_group,
            text="站点配置会保存到优化版目录中的 .site_overrides.json",
            anchor="w",
            justify="left",
        )
        self.site_override_status_label.grid(row=3, column=1, padx=10, pady=(0, 10), sticky="ew")
        
        # 章节列表
        self.chapter_listbox = tk.Listbox(self.comic_dl_frame, selectmode=tk.MULTIPLE, bg="#2b2b2b", fg="white", 
                                        borderwidth=0, highlightthickness=0, font=("Arial", 10))
        self.chapter_listbox.grid(row=2, column=0, padx=20, pady=10, sticky="nsew")
        self.comic_dl_frame.grid_rowconfigure(2, weight=1)
        
        # 按钮
        btn_group = ctk.CTkFrame(self.comic_dl_frame)
        btn_group.grid(row=3, column=0, padx=20, pady=10, sticky="ew")
        
        ctk.CTkButton(btn_group, text="全选", command=self.select_all, width=80).grid(row=0, column=0, padx=10, pady=10)
        ctk.CTkButton(btn_group, text="取消全选", command=self.deselect_all, width=80).grid(row=0, column=1, padx=10, pady=10)
        
        # 保存路径
        save_group = ctk.CTkFrame(self.comic_dl_frame)
        save_group.grid(row=4, column=0, padx=20, pady=10, sticky="ew")
        save_group.grid_columnconfigure(1, weight=1)
        
        ctk.CTkLabel(save_group, text="保存位置:").grid(row=0, column=0, padx=10, pady=10)
        self.save_entry = ctk.CTkEntry(save_group)
        self.save_entry.grid(row=0, column=1, padx=10, pady=10, sticky="ew")
        self.save_entry.insert(0, self.comic_dl_downloader.base_dir)
        ctk.CTkButton(save_group, text="浏览", command=self.browse_save_dir, width=80).grid(row=0, column=2, padx=5, pady=10)
        ctk.CTkButton(save_group, text="打开", command=lambda: self.open_folder(self.save_entry.get()), width=80).grid(row=0, column=3, padx=5, pady=10)
        
        # 控制
        ctrl_group = ctk.CTkFrame(self.comic_dl_frame)
        ctrl_group.grid(row=5, column=0, padx=20, pady=10, sticky="ew")
        self.download_button = ctk.CTkButton(ctrl_group, text="开始下载", command=self.start_comic_dl_download, fg_color="green", hover_color="darkgreen")
        self.download_button.grid(row=0, column=0, padx=10, pady=10)
        self.cancel_button = ctk.CTkButton(ctrl_group, text="取消下载", command=self.cancel_download, state="disabled", fg_color="red", hover_color="darkred")
        self.cancel_button.grid(row=0, column=1, padx=10, pady=10)
        self.load_site_override_form()
        self.update_site_status()

    def setup_getcomics_frame(self):
        self.getcomics_frame.grid_columnconfigure(0, weight=1)
        
        # 搜索
        search_group = ctk.CTkFrame(self.getcomics_frame)
        search_group.grid(row=0, column=0, padx=20, pady=10, sticky="ew")
        search_group.grid_columnconfigure(1, weight=1)
        
        ctk.CTkLabel(search_group, text="搜索内容:").grid(row=0, column=0, padx=10, pady=5)
        self.getcomics_query_entry = ctk.CTkEntry(search_group, placeholder_text="输入漫画关键词...")
        self.getcomics_query_entry.grid(row=0, column=1, padx=10, pady=5, sticky="ew")
        
        ctk.CTkLabel(search_group, text="日期过滤:").grid(row=1, column=0, padx=10, pady=5)
        self.getcomics_date_entry = ctk.CTkEntry(search_group, placeholder_text="YYYY-MM-DD 或 YYYY-MM")
        self.getcomics_date_entry.grid(row=1, column=1, padx=10, pady=5, sticky="ew")
        
        ctk.CTkLabel(search_group, text="结果数量:").grid(row=2, column=0, padx=10, pady=5)
        self.getcomics_results_var = tk.StringVar(value=DEFAULT_GETCOMICS_RESULTS)
        self.getcomics_results_combo = ctk.CTkOptionMenu(search_group, values=["5", "10", "20", "50"], variable=self.getcomics_results_var)
        self.getcomics_results_combo.grid(row=2, column=1, padx=10, pady=5, sticky="w")

        history_group = ctk.CTkFrame(search_group, fg_color="transparent")
        history_group.grid(row=3, column=0, columnspan=2, padx=10, pady=(0, 5), sticky="ew")
        history_group.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(history_group, text="最近搜索:").grid(row=0, column=0, padx=(0, 10), pady=0, sticky="w")
        self.getcomics_recent_var = tk.StringVar(value="最近搜索")
        self.getcomics_recent_menu = ctk.CTkOptionMenu(
            history_group,
            values=["最近搜索"],
            variable=self.getcomics_recent_var,
            command=self.apply_recent_getcomics_search,
            state="disabled",
        )
        self.getcomics_recent_menu.grid(row=0, column=1, padx=(0, 10), pady=0, sticky="ew")
        self.getcomics_recent_clear_button = ctk.CTkButton(
            history_group,
            text="清空历史",
            command=self.clear_getcomics_history,
            width=90,
            state="disabled",
        )
        self.getcomics_recent_clear_button.grid(row=0, column=2, padx=0, pady=0, sticky="e")
        
        self.getcomics_search_button = ctk.CTkButton(search_group, text="搜索漫画", command=self.search_getcomics)
        self.getcomics_search_button.grid(row=4, column=0, columnspan=2, padx=10, pady=10, sticky="ew")

        pagination_group = ctk.CTkFrame(search_group, fg_color="transparent")
        pagination_group.grid(row=5, column=0, columnspan=2, padx=10, pady=(0, 10), sticky="ew")
        pagination_group.grid_columnconfigure(1, weight=1)

        self.getcomics_prev_button = ctk.CTkButton(
            pagination_group,
            text="上一页",
            command=self.load_previous_getcomics_page,
            state="disabled",
            width=90,
        )
        self.getcomics_prev_button.grid(row=0, column=0, padx=(0, 8), pady=0, sticky="w")

        self.getcomics_page_label = ctk.CTkLabel(pagination_group, text="当前页: 未搜索", anchor="w")
        self.getcomics_page_label.grid(row=0, column=1, padx=(0, 8), pady=0, sticky="ew")

        ctk.CTkLabel(pagination_group, text="跳转:").grid(row=0, column=2, padx=(0, 6), pady=0, sticky="e")
        self.getcomics_jump_entry = ctk.CTkEntry(
            pagination_group,
            width=70,
            placeholder_text="页码",
            state="disabled",
        )
        self.getcomics_jump_entry.grid(row=0, column=3, padx=(0, 6), pady=0, sticky="e")
        self.getcomics_jump_entry.bind("<Return>", lambda event: self.jump_to_getcomics_page())

        self.getcomics_jump_button = ctk.CTkButton(
            pagination_group,
            text="跳转",
            command=self.jump_to_getcomics_page,
            state="disabled",
            width=70,
        )
        self.getcomics_jump_button.grid(row=0, column=4, padx=(0, 8), pady=0, sticky="e")

        self.getcomics_next_button = ctk.CTkButton(
            pagination_group,
            text="下一页",
            command=self.load_next_getcomics_page,
            state="disabled",
            width=90,
        )
        self.getcomics_next_button.grid(row=0, column=5, padx=0, pady=0, sticky="e")
        
        # 结果列表
        self.getcomics_listbox = tk.Listbox(self.getcomics_frame, selectmode=tk.MULTIPLE, bg="#2b2b2b", fg="white", 
                                          borderwidth=0, highlightthickness=0, font=("Arial", 10))
        self.getcomics_listbox.grid(row=1, column=0, padx=20, pady=10, sticky="nsew")
        self.getcomics_frame.grid_rowconfigure(1, weight=1)
        self.getcomics_listbox.bind("<<ListboxSelect>>", lambda event: self.update_getcomics_result_actions())
        self.getcomics_listbox.bind("<Double-Button-1>", lambda event: self.open_selected_getcomics_results())
        self.getcomics_listbox.bind("<Return>", lambda event: self.open_selected_getcomics_results())
        self.getcomics_listbox.bind("<Button-3>", self.show_getcomics_results_menu)

        self.getcomics_results_menu = tk.Menu(self.getcomics_listbox, tearoff=0)
        self.getcomics_results_menu.add_command(label="打开详情页", command=self.open_selected_getcomics_results)
        self.getcomics_results_menu.add_command(label="复制链接", command=self.copy_selected_getcomics_links)
        self.getcomics_results_menu.add_separator()
        self.getcomics_results_menu.add_command(label="加入收藏", command=self.add_selected_getcomics_to_favorites)
        self.getcomics_results_menu.add_command(label="移除收藏", command=self.remove_selected_getcomics_from_favorites)
        self.getcomics_results_menu.add_command(label="查看收藏", command=self.toggle_getcomics_view_mode)
        self.getcomics_results_menu.add_separator()
        self.getcomics_results_menu.add_command(label="加入队列", command=self.add_selected_getcomics_to_queue)
        self.getcomics_results_menu.add_command(label="移出队列", command=self.remove_selected_getcomics_from_queue)
        self.getcomics_results_menu.add_command(label="查看队列", command=self.toggle_getcomics_queue_view)
        self.getcomics_results_menu.add_separator()
        self.getcomics_results_menu.add_command(label="全选结果", command=self.select_all_getcomics_results)

        result_actions_group = ctk.CTkFrame(self.getcomics_frame)
        result_actions_group.grid(row=2, column=0, padx=20, pady=(0, 10), sticky="ew")
        self.getcomics_open_result_button = ctk.CTkButton(
            result_actions_group,
            text="打开详情",
            command=self.open_selected_getcomics_results,
            width=100,
            state="disabled",
        )
        self.getcomics_open_result_button.grid(row=0, column=0, padx=10, pady=10)
        self.getcomics_copy_links_button = ctk.CTkButton(
            result_actions_group,
            text="复制链接",
            command=self.copy_selected_getcomics_links,
            width=100,
            state="disabled",
        )
        self.getcomics_copy_links_button.grid(row=0, column=1, padx=10, pady=10)
        self.getcomics_select_all_button = ctk.CTkButton(
            result_actions_group,
            text="全选结果",
            command=self.select_all_getcomics_results,
            width=100,
            state="disabled",
        )
        self.getcomics_select_all_button.grid(row=0, column=2, padx=10, pady=10)
        self.getcomics_add_favorite_button = ctk.CTkButton(
            result_actions_group,
            text="加入收藏",
            command=self.add_selected_getcomics_to_favorites,
            width=100,
            state="disabled",
        )
        self.getcomics_add_favorite_button.grid(row=0, column=3, padx=10, pady=10)
        self.getcomics_remove_favorite_button = ctk.CTkButton(
            result_actions_group,
            text="移除收藏",
            command=self.remove_selected_getcomics_from_favorites,
            width=100,
            state="disabled",
        )
        self.getcomics_remove_favorite_button.grid(row=0, column=4, padx=10, pady=10)
        self.getcomics_toggle_view_button = ctk.CTkButton(
            result_actions_group,
            text="查看收藏",
            command=self.toggle_getcomics_view_mode,
            width=100,
            state="disabled",
        )
        self.getcomics_toggle_view_button.grid(row=0, column=5, padx=10, pady=10)
        self.getcomics_import_favorites_button = ctk.CTkButton(
            result_actions_group,
            text="导入收藏",
            command=self.import_getcomics_favorites,
            width=100,
        )
        self.getcomics_import_favorites_button.grid(row=0, column=6, padx=10, pady=10)
        self.getcomics_export_favorites_button = ctk.CTkButton(
            result_actions_group,
            text="导出收藏",
            command=self.export_getcomics_favorites,
            width=100,
            state="disabled",
        )
        self.getcomics_export_favorites_button.grid(row=0, column=7, padx=10, pady=10)
        self.getcomics_add_queue_button = ctk.CTkButton(
            result_actions_group,
            text="加入队列",
            command=self.add_selected_getcomics_to_queue,
            width=100,
            state="disabled",
        )
        self.getcomics_add_queue_button.grid(row=1, column=0, padx=10, pady=(0, 10))
        self.getcomics_remove_queue_button = ctk.CTkButton(
            result_actions_group,
            text="移出队列",
            command=self.remove_selected_getcomics_from_queue,
            width=100,
            state="disabled",
        )
        self.getcomics_remove_queue_button.grid(row=1, column=1, padx=10, pady=(0, 10))
        self.getcomics_toggle_queue_button = ctk.CTkButton(
            result_actions_group,
            text="查看队列",
            command=self.toggle_getcomics_queue_view,
            width=100,
            state="disabled",
        )
        self.getcomics_toggle_queue_button.grid(row=1, column=2, padx=10, pady=(0, 10))
        self.getcomics_clear_queue_button = ctk.CTkButton(
            result_actions_group,
            text="清空队列",
            command=self.clear_getcomics_queue,
            width=100,
            state="disabled",
        )
        self.getcomics_clear_queue_button.grid(row=1, column=3, padx=10, pady=(0, 10))
        
        # 保存位置
        save_group = ctk.CTkFrame(self.getcomics_frame)
        save_group.grid(row=3, column=0, padx=20, pady=10, sticky="ew")
        save_group.grid_columnconfigure(1, weight=1)
        
        ctk.CTkLabel(save_group, text="保存位置:").grid(row=0, column=0, padx=10, pady=10)
        self.getcomics_save_entry = ctk.CTkEntry(save_group)
        self.getcomics_save_entry.grid(row=0, column=1, padx=10, pady=10, sticky="ew")
        self.getcomics_save_entry.insert(0, self.default_getcomics_save_dir)
        ctk.CTkButton(save_group, text="浏览", command=self.browse_getcomics_save_dir, width=80).grid(row=0, column=2, padx=5, pady=10)
        ctk.CTkButton(save_group, text="打开", command=lambda: self.open_folder(self.getcomics_save_entry.get()), width=80).grid(row=0, column=3, padx=5, pady=10)
        
        # 控制
        ctrl_group = ctk.CTkFrame(self.getcomics_frame)
        ctrl_group.grid(row=4, column=0, padx=20, pady=10, sticky="ew")
        self.getcomics_download_button = ctk.CTkButton(ctrl_group, text="开始下载", command=self.start_getcomics_download, fg_color="green", hover_color="darkgreen")
        self.getcomics_download_button.grid(row=0, column=0, padx=10, pady=10)
        self.getcomics_download_queue_button = ctk.CTkButton(
            ctrl_group,
            text="下载队列",
            command=self.start_getcomics_queue_download,
            fg_color="#1f6f5f",
            hover_color="#18594d",
            state="disabled",
        )
        self.getcomics_download_queue_button.grid(row=0, column=1, padx=10, pady=10)
        self.getcomics_cancel_button = ctk.CTkButton(ctrl_group, text="取消下载", command=self.cancel_getcomics_download, state="disabled", fg_color="red", hover_color="darkred")
        self.getcomics_cancel_button.grid(row=0, column=2, padx=10, pady=10)
        self.update_getcomics_result_actions()
        self.update_getcomics_pagination_controls(searching=False)

    def setup_convert_frame(self):
        self.convert_frame.grid_columnconfigure(0, weight=1)
        
        group = ctk.CTkFrame(self.convert_frame)
        group.grid(row=0, column=0, padx=20, pady=20, sticky="ew")
        group.grid_columnconfigure(1, weight=1)
        
        ctk.CTkLabel(group, text="输入路径 (文件夹/CBZ/ZIP/CBR/RAR/PDF/CB7/7z):").grid(row=0, column=0, padx=10, pady=10)
        self.convert_input_entry = ctk.CTkEntry(group)
        self.convert_input_entry.grid(row=0, column=1, padx=10, pady=10, sticky="ew")
        ctk.CTkButton(group, text="浏览", command=self.browse_convert_input, width=80).grid(row=0, column=2, padx=10, pady=10)
        
        ctk.CTkLabel(group, text="输出路径 (.cbz):").grid(row=1, column=0, padx=10, pady=10)
        self.convert_output_entry = ctk.CTkEntry(group)
        self.convert_output_entry.grid(row=1, column=1, padx=10, pady=10, sticky="ew")
        ctk.CTkButton(group, text="浏览", command=self.browse_convert_output, width=80).grid(row=1, column=2, padx=5, pady=10)
        ctk.CTkButton(group, text="打开", command=lambda: self.open_folder(os.path.dirname(self.convert_output_entry.get())), width=80).grid(row=1, column=3, padx=5, pady=10)
        
        self.convert_button = ctk.CTkButton(group, text="开始转换", command=self.start_convert, width=200, height=40)
        self.convert_button.grid(row=2, column=0, columnspan=3, padx=10, pady=20)
        self.convert_support_label = ctk.CTkLabel(
            group,
            text=self.build_format_support_notice_text("convert"),
            justify="left",
            anchor="w",
            wraplength=760,
            text_color=SUPPORT_NOTICE_COLOR,
        )
        self.convert_support_label.grid(row=3, column=0, columnspan=4, padx=10, pady=(0, 10), sticky="ew")

    def setup_rename_frame(self):
        self.rename_frame.grid_columnconfigure(1, weight=1)
        self.rename_frame.grid_rowconfigure(0, weight=1)
        
        # 左侧控制
        left_ctrl = ctk.CTkFrame(self.rename_frame, width=300)
        left_ctrl.grid(row=0, column=0, padx=20, pady=20, sticky="nsew")
        
        ctk.CTkLabel(left_ctrl, text="文件夹路径:", font=ctk.CTkFont(weight="bold")).pack(padx=10, pady=(10, 5), anchor="w")
        self.rename_folder_path = tk.StringVar()
        f_group = ctk.CTkFrame(left_ctrl, fg_color="transparent")
        f_group.pack(fill="x", padx=10, pady=5)
        ctk.CTkEntry(f_group, textvariable=self.rename_folder_path).pack(side="left", fill="x", expand=True, padx=(0, 5))
        ctk.CTkButton(f_group, text="浏览", command=self.rename_browse_folder, width=60).pack(side="left", padx=2)
        ctk.CTkButton(f_group, text="打开", command=lambda: self.open_folder(self.rename_folder_path.get()), width=60).pack(side="left", padx=2)
        
        ctk.CTkButton(left_ctrl, text="刷新文件列表", command=self.rename_refresh_files).pack(padx=10, pady=10, fill="x")
        
        ctk.CTkLabel(left_ctrl, text="AI 提示词设置:", font=ctk.CTkFont(weight="bold")).pack(padx=10, pady=(20, 5), anchor="w")
        self.rename_prompt_text = ctk.CTkTextbox(left_ctrl, height=100)
        self.rename_prompt_text.pack(padx=10, pady=5, fill="x")
        self.rename_prompt_text.insert("1.0", "你是一个漫画文件名分析专家，擅长识别美漫的标题、期号和年份。请将输入的文件名分析为标准格式：'漫画标题 #期号 (年份).扩展名'。只返回分析后的文件名，不要包含其他内容。")

        rename_api_hint_frame = ctk.CTkFrame(left_ctrl, fg_color="transparent")
        rename_api_hint_frame.pack(fill="x", padx=10, pady=(0, 8))
        ctk.CTkLabel(
            rename_api_hint_frame,
            text="AI 接口 Key、地址和模型请到“设置”页配置。",
            justify="left",
            anchor="w",
            wraplength=210,
        ).pack(side="left", fill="x", expand=True)
        ctk.CTkButton(
            rename_api_hint_frame,
            text="打开设置",
            width=82,
            command=self.open_settings_for_api,
        ).pack(side="right", padx=(8, 0))

        self.rename_include_folder = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(left_ctrl, text="包含文件夹名作为参考", variable=self.rename_include_folder).pack(padx=10, pady=10, anchor="w")
        
        self.analyze_button = ctk.CTkButton(left_ctrl, text="AI 分析文件名", command=self.rename_analyze_with_ai, fg_color="purple", hover_color="darkorchid")
        self.analyze_button.pack(padx=10, pady=10, fill="x")
        
        self.rename_exec_button = ctk.CTkButton(left_ctrl, text="执行批量重命名", command=self.rename_execute_rename, fg_color="green", hover_color="darkgreen")
        self.rename_exec_button.pack(padx=10, pady=10, fill="x")
        
        # 右侧表格
        right_table = ctk.CTkFrame(self.rename_frame)
        right_table.grid(row=0, column=1, padx=(0, 20), pady=20, sticky="nsew")
        right_table.grid_columnconfigure(0, weight=1)
        right_table.grid_rowconfigure(0, weight=1)
        
        from tkinter import ttk
        style = ttk.Style()
        style.theme_use("default")
        style.configure("Treeview", background="#2b2b2b", foreground="white", fieldbackground="#2b2b2b", borderwidth=0)
        style.map("Treeview", background=[('selected', '#1f538d')])
        
        self.rename_tree = ttk.Treeview(right_table, columns=("original", "new"), show="headings")
        self.rename_tree.heading("original", text="原始文件名")
        self.rename_tree.heading("new", text="新文件名")
        self.rename_tree.grid(row=0, column=0, sticky="nsew")
        
        scroll = ctk.CTkScrollbar(right_table, orientation="vertical", command=self.rename_tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.rename_tree.configure(yscrollcommand=scroll.set)

    def setup_reader_frame(self):
        self.reader_frame.grid_columnconfigure(1, weight=1)
        self.reader_frame.grid_rowconfigure(1, weight=1)

        self.reader_workspace_header = ctk.CTkFrame(
            self.reader_frame,
            corner_radius=16,
            border_width=1,
            border_color="#3d3d3d",
        )
        self.reader_workspace_header.grid(row=0, column=0, columnspan=2, padx=20, pady=(20, 10), sticky="ew")
        self.reader_workspace_header.grid_columnconfigure(0, weight=1)

        self.reader_workspace_title = ctk.CTkLabel(
            self.reader_workspace_header,
            text="漫画阅读空间",
            font=ctk.CTkFont(size=22, weight="bold"),
            anchor="w",
        )
        self.reader_workspace_title.grid(row=0, column=0, padx=18, pady=(14, 4), sticky="ew")

        self.reader_workspace_hint_label = ctk.CTkLabel(
            self.reader_workspace_header,
            text="阅读页已独立出来，可从左侧浏览文件并在右侧翻页。开启专注阅读后会折叠资料区，让更多空间留给漫画页面。",
            justify="left",
            anchor="w",
            wraplength=860,
        )
        self.reader_workspace_hint_label.grid(row=1, column=0, padx=18, pady=(0, 10), sticky="ew")

        self.reader_header_actions = ctk.CTkFrame(self.reader_workspace_header, fg_color="transparent")
        self.reader_header_actions.grid(row=0, column=1, rowspan=2, padx=(12, 18), pady=14, sticky="e")
        self.reader_header_actions.grid_columnconfigure((0, 1, 2, 3), weight=1)

        ctk.CTkButton(
            self.reader_header_actions,
            text="浏览目录",
            width=100,
            command=self.browse_reader_library_dir,
        ).grid(row=0, column=0, padx=(0, 8), pady=0)

        ctk.CTkButton(
            self.reader_header_actions,
            text="选择文件",
            width=100,
            command=self.browse_reader_library_file,
        ).grid(row=0, column=1, padx=8, pady=0)

        self.reader_focus_button = ctk.CTkButton(
            self.reader_header_actions,
            text="专注阅读",
            width=120,
            command=self.toggle_reader_focus_mode,
        )
        self.reader_focus_button.grid(row=0, column=2, padx=(8, 0), pady=0)

        self.reader_fullscreen_button = ctk.CTkButton(
            self.reader_header_actions,
            text="全屏阅读",
            width=120,
            command=self.toggle_reader_fullscreen_mode,
        )
        self.reader_fullscreen_button.grid(row=0, column=3, padx=(8, 0), pady=0)

        left_panel = ctk.CTkFrame(self.reader_frame, width=280)
        left_panel.grid(row=1, column=0, padx=(20, 10), pady=(0, 20), sticky="nsew")
        left_panel.grid_columnconfigure(0, weight=1)
        left_panel.grid_rowconfigure(4, weight=1)
        self.reader_sidebar_frame = left_panel

        ctk.CTkLabel(
            left_panel,
            text="本地漫画文件",
            font=ctk.CTkFont(size=20, weight="bold"),
        ).grid(row=0, column=0, padx=15, pady=(15, 10), sticky="w")

        self.reader_source_entry = ctk.CTkEntry(
            left_panel,
            placeholder_text="选择漫画目录或单个 CBZ/ZIP/CBR/RAR/7z/PDF 文件",
        )
        self.reader_source_entry.grid(row=1, column=0, padx=15, pady=(0, 10), sticky="ew")
        self.reader_source_entry.insert(0, self.default_getcomics_save_dir)
        self.reader_source_entry.bind("<Return>", lambda event: self.refresh_reader_library())

        reader_path_buttons = ctk.CTkFrame(left_panel, fg_color="transparent")
        reader_path_buttons.grid(row=2, column=0, padx=15, pady=(0, 10), sticky="ew")
        reader_path_buttons.grid_columnconfigure((0, 1, 2), weight=1)

        ctk.CTkButton(
            reader_path_buttons,
            text="浏览目录",
            command=self.browse_reader_library_dir,
        ).grid(row=0, column=0, padx=(0, 5), pady=0, sticky="ew")
        ctk.CTkButton(
            reader_path_buttons,
            text="选择文件",
            command=self.browse_reader_library_file,
        ).grid(row=0, column=1, padx=5, pady=0, sticky="ew")
        ctk.CTkButton(
            reader_path_buttons,
            text="刷新列表",
            command=self.refresh_reader_library,
        ).grid(row=0, column=2, padx=(5, 0), pady=0, sticky="ew")

        self.reader_support_label = ctk.CTkLabel(
            left_panel,
            text=self.build_format_support_notice_text("reader"),
            justify="left",
            anchor="w",
            wraplength=250,
            text_color=SUPPORT_NOTICE_COLOR,
        )
        self.reader_support_label.grid(row=3, column=0, padx=15, pady=(0, 10), sticky="ew")

        self.reader_listbox = tk.Listbox(
            left_panel,
            selectmode=tk.SINGLE,
            bg="#2b2b2b",
            fg="white",
            borderwidth=0,
            highlightthickness=0,
            font=("Arial", 10),
        )
        self.reader_listbox.grid(row=4, column=0, padx=15, pady=(0, 10), sticky="nsew")
        self.reader_listbox.bind("<<ListboxSelect>>", lambda event: self.on_reader_selection_changed())
        self.reader_listbox.bind("<Double-Button-1>", lambda event: self.open_selected_reader_comic())
        self.reader_listbox.bind("<Return>", lambda event: self.open_selected_reader_comic())

        reader_list_actions = ctk.CTkFrame(left_panel, fg_color="transparent")
        reader_list_actions.grid(row=5, column=0, padx=15, pady=(0, 10), sticky="ew")
        reader_list_actions.grid_columnconfigure((0, 1), weight=1)

        self.reader_open_button = ctk.CTkButton(
            reader_list_actions,
            text="开始阅读",
            command=self.open_selected_reader_comic,
            state="disabled",
        )
        self.reader_open_button.grid(row=0, column=0, padx=(0, 5), pady=0, sticky="ew")
        self.reader_open_file_button = ctk.CTkButton(
            reader_list_actions,
            text="打开文件",
            command=self.open_selected_reader_item,
            state="disabled",
        )
        self.reader_open_file_button.grid(row=0, column=1, padx=(5, 0), pady=0, sticky="ew")

        self.reader_open_folder_button = ctk.CTkButton(
            left_panel,
            text="打开所在目录",
            command=self.open_selected_reader_parent,
            state="disabled",
        )
        self.reader_open_folder_button.grid(row=6, column=0, padx=15, pady=(0, 15), sticky="ew")

        right_panel = ctk.CTkFrame(self.reader_frame)
        right_panel.grid(row=1, column=1, padx=(10, 20), pady=(0, 20), sticky="nsew")
        right_panel.grid_columnconfigure(0, weight=1)
        right_panel.grid_rowconfigure(2, weight=1)
        self.reader_content_frame = right_panel

        self.reader_title_label = ctk.CTkLabel(
            right_panel,
            text="漫画阅读器",
            font=ctk.CTkFont(size=20, weight="bold"),
            anchor="w",
        )
        self.reader_title_label.grid(row=0, column=0, padx=20, pady=(15, 5), sticky="ew")

        self.reader_info_textbox = ctk.CTkTextbox(right_panel, height=82)
        self.reader_info_textbox.grid(row=1, column=0, padx=20, pady=(0, 10), sticky="ew")
        self.reader_info_textbox.configure(state="disabled")

        preview_frame = ctk.CTkFrame(right_panel)
        preview_frame.grid(row=2, column=0, padx=20, pady=(0, 10), sticky="nsew")
        preview_frame.grid_columnconfigure(0, weight=1)
        preview_frame.grid_rowconfigure(1, weight=1)

        reader_zoom_toolbar = ctk.CTkFrame(preview_frame, fg_color="transparent")
        reader_zoom_toolbar.grid(row=0, column=0, padx=10, pady=(10, 0), sticky="ew")
        reader_zoom_toolbar.grid_columnconfigure(5, weight=1)

        ctk.CTkLabel(reader_zoom_toolbar, text="缩放").grid(row=0, column=0, padx=(0, 8), pady=0)
        self.reader_zoom_out_button = ctk.CTkButton(
            reader_zoom_toolbar,
            text="-",
            width=36,
            command=lambda: self.adjust_reader_zoom(-READER_ZOOM_STEP),
            state="disabled",
        )
        self.reader_zoom_out_button.grid(row=0, column=1, padx=(0, 6), pady=0)
        self.reader_zoom_value_label = ctk.CTkLabel(
            reader_zoom_toolbar,
            text=f"{self.reader_zoom_percent}%",
            width=60,
        )
        self.reader_zoom_value_label.grid(row=0, column=2, padx=0, pady=0)
        self.reader_zoom_in_button = ctk.CTkButton(
            reader_zoom_toolbar,
            text="+",
            width=36,
            command=lambda: self.adjust_reader_zoom(READER_ZOOM_STEP),
            state="disabled",
        )
        self.reader_zoom_in_button.grid(row=0, column=3, padx=(6, 6), pady=0)
        self.reader_zoom_reset_button = ctk.CTkButton(
            reader_zoom_toolbar,
            text="100%",
            width=60,
            command=self.reset_reader_zoom,
            state="disabled",
        )
        self.reader_zoom_reset_button.grid(row=0, column=4, padx=(0, 10), pady=0)
        self.reader_zoom_mode_menu = ctk.CTkOptionMenu(
            reader_zoom_toolbar,
            values=list(READER_ZOOM_MODE_VALUES.keys()),
            command=self.handle_reader_zoom_mode_change,
            state="disabled",
            width=150,
        )
        self.reader_zoom_mode_menu.grid(row=0, column=5, padx=0, pady=0, sticky="e")
        self.reader_zoom_mode_menu.set(self.get_reader_zoom_mode_label(self.reader_zoom_mode))

        preview_canvas_frame = ctk.CTkFrame(preview_frame)
        preview_canvas_frame.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")
        preview_canvas_frame.grid_columnconfigure(0, weight=1)
        preview_canvas_frame.grid_rowconfigure(0, weight=1)

        self.reader_preview_canvas = tk.Canvas(
            preview_canvas_frame,
            bg="#111111",
            highlightthickness=0,
            borderwidth=0,
            xscrollincrement=1,
            yscrollincrement=1,
        )
        self.reader_preview_canvas.grid(row=0, column=0, sticky="nsew")

        self.reader_preview_y_scrollbar = ctk.CTkScrollbar(
            preview_canvas_frame,
            orientation="vertical",
            command=self.reader_preview_canvas.yview,
        )
        self.reader_preview_y_scrollbar.grid(row=0, column=1, padx=(10, 0), sticky="ns")
        self.reader_preview_x_scrollbar = ctk.CTkScrollbar(
            preview_canvas_frame,
            orientation="horizontal",
            command=self.reader_preview_canvas.xview,
        )
        self.reader_preview_x_scrollbar.grid(row=1, column=0, pady=(10, 0), sticky="ew")
        self.reader_preview_canvas.configure(
            xscrollcommand=self.reader_preview_x_scrollbar.set,
            yscrollcommand=self.reader_preview_y_scrollbar.set,
        )
        self.reader_preview_canvas.bind(
            "<Configure>",
            lambda event: self.handle_reader_preview_configure(),
        )
        self.reader_preview_canvas.bind("<MouseWheel>", self.handle_reader_mousewheel)
        self.reader_preview_canvas.bind("<Shift-MouseWheel>", self.handle_reader_mousewheel)
        self.reader_preview_canvas.bind("<Button-4>", self.handle_reader_mousewheel)
        self.reader_preview_canvas.bind("<Button-5>", self.handle_reader_mousewheel)
        self.reader_preview_canvas.bind(
            "<Double-Button-1>",
            lambda event: self.toggle_reader_fullscreen_mode(),
        )

        reader_controls = ctk.CTkFrame(right_panel)
        reader_controls.grid(row=3, column=0, padx=20, pady=(0, 15), sticky="ew")
        reader_controls.grid_columnconfigure((0, 1, 2, 3, 4, 5), weight=1)

        self.reader_first_button = ctk.CTkButton(
            reader_controls,
            text="首页",
            command=lambda: self.set_reader_page(0),
            state="disabled",
        )
        self.reader_first_button.grid(row=0, column=0, padx=(0, 5), pady=0, sticky="ew")
        self.reader_prev_button = ctk.CTkButton(
            reader_controls,
            text="上一页",
            command=lambda: self.change_reader_page(-1),
            state="disabled",
        )
        self.reader_prev_button.grid(row=0, column=1, padx=5, pady=0, sticky="ew")

        self.reader_page_entry = ctk.CTkEntry(
            reader_controls,
            width=80,
            justify="center",
            state="disabled",
        )
        self.reader_page_entry.grid(row=0, column=2, padx=5, pady=0, sticky="ew")
        self.reader_page_entry.bind("<Return>", lambda event: self.jump_reader_page())

        self.reader_page_total_label = ctk.CTkLabel(reader_controls, text="/ 0")
        self.reader_page_total_label.grid(row=0, column=3, padx=5, pady=0)

        self.reader_next_button = ctk.CTkButton(
            reader_controls,
            text="下一页",
            command=lambda: self.change_reader_page(1),
            state="disabled",
        )
        self.reader_next_button.grid(row=0, column=4, padx=5, pady=0, sticky="ew")
        self.reader_last_button = ctk.CTkButton(
            reader_controls,
            text="末页",
            command=self.go_to_last_reader_page,
            state="disabled",
        )
        self.reader_last_button.grid(row=0, column=5, padx=(5, 0), pady=0, sticky="ew")

        self.set_reader_info_text("漫画列表会显示目录下的图片文件夹、CBZ/ZIP/CBR/RAR/7z/PDF 文件。")
        self.show_reader_preview_placeholder(self.reader_preview_placeholder)
        self.update_reader_zoom_controls()
        self.refresh_reader_library(initial_path=self.default_getcomics_save_dir, select_first=False)
        self.set_reader_focus_mode(self.reader_focus_mode, persist=False, refresh=False)

    def setup_logs_frame(self):
        self.logs_frame.grid_columnconfigure(0, weight=1)
        self.logs_frame.grid_rowconfigure(4, weight=1)

        ctk.CTkLabel(
            self.logs_frame,
            text="运行日志与维护信息",
            font=ctk.CTkFont(size=24, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, padx=20, pady=(24, 6), sticky="ew")

        ctk.CTkLabel(
            self.logs_frame,
            text="这里集中显示任务状态、详细执行日志和错误信息，方便回看下载过程、定位异常并把日志发给维护者。",
            justify="left",
            anchor="w",
        ).grid(row=1, column=0, padx=20, pady=(0, 14), sticky="ew")

        logs_status_frame = ctk.CTkFrame(self.logs_frame)
        logs_status_frame.grid(row=2, column=0, padx=20, pady=(0, 12), sticky="ew")
        logs_status_frame.grid_columnconfigure(0, weight=1)

        self.status_label = ctk.CTkLabel(logs_status_frame, text="准备就绪", anchor="w")
        self.status_label.grid(row=0, column=0, padx=18, pady=(14, 6), sticky="ew")

        self.percent_label = ctk.CTkLabel(logs_status_frame, text="0%")
        self.percent_label.grid(row=0, column=1, padx=(0, 18), pady=(14, 6), sticky="e")

        self.progress_var = tk.DoubleVar()
        self.progress_bar = ctk.CTkProgressBar(logs_status_frame)
        self.progress_bar.grid(row=1, column=0, columnspan=2, padx=18, pady=(0, 10), sticky="ew")
        self.progress_bar.set(0)

        self.logs_error_title_label = ctk.CTkLabel(logs_status_frame, text="最近错误:", anchor="w")
        self.logs_error_title_label.grid(row=2, column=0, padx=18, pady=(0, 4), sticky="w")
        self.logs_error_value_label = ctk.CTkLabel(
            logs_status_frame,
            text="暂无错误",
            justify="left",
            anchor="w",
            wraplength=860,
            text_color="#d97c7c",
        )
        self.logs_error_value_label.grid(row=3, column=0, columnspan=2, padx=18, pady=(0, 10), sticky="ew")

        self.logs_file_title_label = ctk.CTkLabel(logs_status_frame, text="日志文件:", anchor="w")
        self.logs_file_title_label.grid(row=4, column=0, padx=18, pady=(0, 4), sticky="w")
        self.logs_file_value_label = ctk.CTkLabel(
            logs_status_frame,
            text=str(Path(log_filename).resolve()),
            justify="left",
            anchor="w",
            wraplength=860,
        )
        self.logs_file_value_label.grid(row=5, column=0, columnspan=2, padx=18, pady=(0, 14), sticky="ew")

        logs_action_frame = ctk.CTkFrame(self.logs_frame, fg_color="transparent")
        logs_action_frame.grid(row=3, column=0, padx=20, pady=(0, 10), sticky="ew")
        logs_action_frame.grid_columnconfigure((0, 1, 2, 3, 4), weight=1)

        self.open_folder_button = ctk.CTkButton(
            logs_action_frame,
            text="打开当前目录",
            command=self.open_current_download_folder,
        )
        self.open_folder_button.grid(row=0, column=0, padx=(0, 8), sticky="ew")
        ctk.CTkButton(
            logs_action_frame,
            text="打开日志目录",
            command=self.open_logs_folder,
        ).grid(row=0, column=1, padx=8, sticky="ew")
        ctk.CTkButton(
            logs_action_frame,
            text="打开日志文件",
            command=self.open_log_file,
        ).grid(row=0, column=2, padx=8, sticky="ew")
        ctk.CTkButton(
            logs_action_frame,
            text="复制日志",
            command=self.copy_logs_to_clipboard,
        ).grid(row=0, column=3, padx=8, sticky="ew")
        ctk.CTkButton(
            logs_action_frame,
            text="清空日志",
            command=self.clear_logs,
        ).grid(row=0, column=4, padx=(8, 0), sticky="ew")

        self.log_textbox = ctk.CTkTextbox(self.logs_frame)
        self.log_textbox.grid(row=4, column=0, padx=20, pady=(0, 20), sticky="nsew")
        self.log_textbox.configure(state="disabled")

        self.log_menu = tk.Menu(self.log_textbox, tearoff=0)
        self.log_menu.add_command(label="清空日志", command=self.clear_logs)
        self.log_menu.add_command(label="复制日志", command=self.copy_logs_to_clipboard)
        self.log_textbox.bind("<Button-3>", self.show_log_menu)

    def setup_settings_frame(self):
        self.settings_frame.grid_columnconfigure(0, weight=1)
        self.settings_frame.grid_rowconfigure(4, weight=1)

        ctk.CTkLabel(
            self.settings_frame,
            text="设置",
            font=ctk.CTkFont(size=24, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, padx=20, pady=(24, 6), sticky="ew")

        ctk.CTkLabel(
            self.settings_frame,
            text="统一管理外观、Windows 阅读器全屏方式，以及 AI 漫画重命名接口配置。",
            justify="left",
            anchor="w",
        ).grid(row=1, column=0, padx=20, pady=(0, 14), sticky="ew")

        display_group = ctk.CTkFrame(self.settings_frame)
        display_group.grid(row=2, column=0, padx=20, pady=(0, 12), sticky="ew")
        display_group.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            display_group,
            text="界面外观",
            font=ctk.CTkFont(weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, padx=16, pady=(16, 6), sticky="w")
        self.settings_appearance_optionemenu = ctk.CTkOptionMenu(
            display_group,
            values=["Light", "Dark", "System"],
            command=self.change_appearance_mode_event,
            width=180,
        )
        self.settings_appearance_optionemenu.grid(row=0, column=1, padx=16, pady=(16, 6), sticky="w")
        self.settings_appearance_optionemenu.set(self.appearance_mode)

        ctk.CTkLabel(
            display_group,
            text="Windows 阅读器全屏方式",
            font=ctk.CTkFont(weight="bold"),
            anchor="w",
        ).grid(row=1, column=0, padx=16, pady=6, sticky="w")
        self.settings_reader_fullscreen_optionemenu = ctk.CTkOptionMenu(
            display_group,
            values=list(WINDOWS_READER_FULLSCREEN_MODE_VALUES.keys()),
            command=lambda _value: self.refresh_settings_fullscreen_hint(),
            width=220,
        )
        self.settings_reader_fullscreen_optionemenu.grid(row=1, column=1, padx=16, pady=6, sticky="w")
        self.settings_reader_fullscreen_optionemenu.set(
            self.get_windows_reader_fullscreen_mode_label(self.reader_windows_fullscreen_mode)
        )
        if os.name != "nt":
            self.settings_reader_fullscreen_optionemenu.configure(state="disabled")

        self.settings_reader_fullscreen_hint_label = ctk.CTkLabel(
            display_group,
            text="",
            justify="left",
            anchor="w",
            wraplength=860,
        )
        self.settings_reader_fullscreen_hint_label.grid(
            row=2,
            column=0,
            columnspan=2,
            padx=16,
            pady=(4, 16),
            sticky="ew",
        )

        api_group = ctk.CTkFrame(self.settings_frame)
        api_group.grid(row=3, column=0, padx=20, pady=(0, 12), sticky="ew")
        api_group.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            api_group,
            text="AI 漫画重命名接口",
            font=ctk.CTkFont(weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, columnspan=2, padx=16, pady=(16, 8), sticky="w")

        ctk.CTkLabel(api_group, text="API Key").grid(row=1, column=0, padx=16, pady=6, sticky="w")
        self.settings_api_key_entry = ctk.CTkEntry(api_group, show="*")
        self.settings_api_key_entry.grid(row=1, column=1, padx=16, pady=6, sticky="ew")
        self.settings_api_key_entry.insert(0, self.rename_api_key)

        self.settings_show_api_key_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            api_group,
            text="显示 Key",
            variable=self.settings_show_api_key_var,
            command=self.toggle_settings_api_key_visibility,
        ).grid(row=2, column=1, padx=16, pady=(0, 6), sticky="w")

        ctk.CTkLabel(api_group, text="接口地址").grid(row=3, column=0, padx=16, pady=6, sticky="w")
        self.settings_api_url_entry = ctk.CTkEntry(api_group)
        self.settings_api_url_entry.grid(row=3, column=1, padx=16, pady=6, sticky="ew")
        self.settings_api_url_entry.insert(0, self.rename_api_url)

        ctk.CTkLabel(api_group, text="模型").grid(row=4, column=0, padx=16, pady=6, sticky="w")
        self.settings_api_model_entry = ctk.CTkEntry(api_group)
        self.settings_api_model_entry.grid(row=4, column=1, padx=16, pady=6, sticky="ew")
        self.settings_api_model_entry.insert(0, self.rename_api_model)

        ctk.CTkLabel(api_group, text="超时（秒）").grid(row=5, column=0, padx=16, pady=6, sticky="w")
        self.settings_api_timeout_entry = ctk.CTkEntry(api_group)
        self.settings_api_timeout_entry.grid(row=5, column=1, padx=16, pady=6, sticky="ew")
        self.settings_api_timeout_entry.insert(0, str(self.rename_api_timeout))

        self.settings_api_status_label = ctk.CTkLabel(
            api_group,
            text="",
            justify="left",
            anchor="w",
            wraplength=860,
        )
        self.settings_api_status_label.grid(
            row=6,
            column=0,
            columnspan=2,
            padx=16,
            pady=(4, 16),
            sticky="ew",
        )

        settings_action_group = ctk.CTkFrame(self.settings_frame, fg_color="transparent")
        settings_action_group.grid(row=4, column=0, padx=20, pady=(0, 20), sticky="ew")
        settings_action_group.grid_columnconfigure(2, weight=1)

        ctk.CTkButton(
            settings_action_group,
            text="保存设置",
            command=self.save_settings,
        ).grid(row=0, column=0, padx=(0, 8), sticky="w")
        ctk.CTkButton(
            settings_action_group,
            text="恢复默认",
            command=self.reset_settings,
        ).grid(row=0, column=1, padx=8, sticky="w")

        self.settings_status_label = ctk.CTkLabel(
            settings_action_group,
            text="修改后会写入本地 .gui_state.json，AI Key 优先使用这里的设置。",
            justify="left",
            anchor="w",
        )
        self.settings_status_label.grid(row=0, column=2, padx=(12, 0), sticky="ew")

        self.refresh_settings_fullscreen_hint()
        self.refresh_settings_api_status_label()

    def show_progress(self):
        """显示进度和日志面板"""
        return None

    def hide_progress(self):
        """隐藏进度和日志面板"""
        return None

    def select_frame_by_name(self, name):
        self.current_frame_name = name
        if name != "reader" and getattr(self, "reader_fullscreen_mode", False):
            self.set_reader_fullscreen_mode(False, refresh=False)
        # 隐藏所有 frame
        self.home_frame.grid_forget()
        self.comic_dl_frame.grid_forget()
        self.getcomics_frame.grid_forget()
        self.convert_frame.grid_forget()
        self.rename_frame.grid_forget()
        self.reader_frame.grid_forget()
        self.logs_frame.grid_forget()
        self.settings_frame.grid_forget()

        # 显示选中的 frame
        if name == "home":
            self.home_frame.grid(row=0, column=1, sticky="nsew")
        elif name == "comic_dl":
            self.comic_dl_frame.grid(row=0, column=1, sticky="nsew")
        elif name == "getcomics":
            self.getcomics_frame.grid(row=0, column=1, sticky="nsew")
        elif name == "convert":
            self.convert_frame.grid(row=0, column=1, sticky="nsew")
        elif name == "rename":
            self.rename_frame.grid(row=0, column=1, sticky="nsew")
        elif name == "reader":
            self.reader_frame.grid(row=0, column=1, sticky="nsew")
        elif name == "logs":
            self.logs_frame.grid(row=0, column=1, sticky="nsew")
        elif name == "settings":
            self.settings_frame.grid(row=0, column=1, sticky="nsew")

    def is_any_task_running(self):
        """检查是否有任何后台任务正在运行"""
        # 这里可以通过检查线程状态或进度条状态来判断
        # 简单起见，如果进度条不是 0 且不是 100%，或者状态不是"准备就绪"，就认为在运行
        return self.status_label.cget("text") != "准备就绪" and self.progress_bar.get() < 1.0

    def change_appearance_mode_event(self, new_appearance_mode: str):
        self.appearance_mode = str(new_appearance_mode or DEFAULT_APPEARANCE_MODE).strip() or DEFAULT_APPEARANCE_MODE
        ctk.set_appearance_mode(self.appearance_mode)
        if hasattr(self, "appearance_mode_optionemenu"):
            self.appearance_mode_optionemenu.set(self.appearance_mode)
        if hasattr(self, "settings_appearance_optionemenu"):
            self.settings_appearance_optionemenu.set(self.appearance_mode)
        self.persist_gui_state_snapshot()

    def get_windows_reader_fullscreen_mode_label(self, value):
        return WINDOWS_READER_FULLSCREEN_MODE_LABELS.get(
            str(value or "").strip().lower(),
            WINDOWS_READER_FULLSCREEN_MODE_LABELS[DEFAULT_WINDOWS_READER_FULLSCREEN_MODE],
        )

    def get_windows_reader_fullscreen_mode_value(self, label):
        return WINDOWS_READER_FULLSCREEN_MODE_VALUES.get(
            str(label or "").strip(),
            DEFAULT_WINDOWS_READER_FULLSCREEN_MODE,
        )

    def refresh_settings_fullscreen_hint(self):
        if not hasattr(self, "settings_reader_fullscreen_hint_label"):
            return

        mode = self.get_windows_reader_fullscreen_mode_value(
            self.settings_reader_fullscreen_optionemenu.get()
            if hasattr(self, "settings_reader_fullscreen_optionemenu")
            else self.get_windows_reader_fullscreen_mode_label(self.reader_windows_fullscreen_mode)
        )
        if os.name != "nt":
            hint_text = "当前系统不是 Windows，此选项主要用于兼容保存；阅读器会继续使用标准全屏行为。"
        elif mode == "exclusive":
            hint_text = "真全屏会隐藏任务栏，沉浸感更强，但切换时比顺滑全屏更重一些。"
        else:
            hint_text = "顺滑全屏使用窗口最大化，不隐藏任务栏，切换更快，也更适合频繁进出全屏。"
        self.settings_reader_fullscreen_hint_label.configure(text=hint_text)

    def toggle_settings_api_key_visibility(self):
        if not hasattr(self, "settings_api_key_entry"):
            return
        self.settings_api_key_entry.configure(
            show="" if self.settings_show_api_key_var.get() else "*"
        )

    def refresh_settings_api_status_label(self):
        if not hasattr(self, "settings_api_status_label"):
            return

        current_key = ""
        if hasattr(self, "settings_api_key_entry"):
            current_key = self.settings_api_key_entry.get().strip()

        if current_key:
            status = "当前会优先使用设置页中的 API Key。"
        elif ENV_DEEPSEEK_API_KEY:
            status = "设置页未填写 API Key，运行时会回退使用环境变量 DEEPSEEK_API_KEY。"
        else:
            status = "当前还没有可用的 API Key，使用 AI 漫画重命名前请先填写。"
        self.settings_api_status_label.configure(text=status)

    def open_settings_for_api(self):
        self.select_frame_by_name("settings")
        if hasattr(self, "settings_api_key_entry"):
            self.settings_api_key_entry.focus_set()

    def get_rename_api_request_settings(self):
        api_key = self.rename_api_key.strip() or ENV_DEEPSEEK_API_KEY
        if not api_key:
            raise ValueError("未配置 AI 重命名 API Key，请先到“设置”页填写，或设置环境变量 DEEPSEEK_API_KEY。")

        api_url = str(self.rename_api_url or DEFAULT_RENAME_API_URL).strip() or DEFAULT_RENAME_API_URL
        api_model = str(self.rename_api_model or DEFAULT_RENAME_API_MODEL).strip() or DEFAULT_RENAME_API_MODEL
        try:
            api_timeout = int(self.rename_api_timeout)
        except (TypeError, ValueError):
            api_timeout = DEFAULT_RENAME_API_TIMEOUT

        return {
            "api_key": api_key,
            "api_url": api_url,
            "api_model": api_model,
            "api_timeout": max(5, min(300, api_timeout)),
        }

    def save_settings(self, success_message="设置已保存"):
        appearance_mode = (
            self.settings_appearance_optionemenu.get().strip()
            if hasattr(self, "settings_appearance_optionemenu")
            else self.appearance_mode
        ) or DEFAULT_APPEARANCE_MODE
        fullscreen_mode = self.get_windows_reader_fullscreen_mode_value(
            self.settings_reader_fullscreen_optionemenu.get()
        )
        api_key = self.settings_api_key_entry.get().strip()
        api_url = self.settings_api_url_entry.get().strip() or DEFAULT_RENAME_API_URL
        api_model = self.settings_api_model_entry.get().strip() or DEFAULT_RENAME_API_MODEL
        timeout_text = self.settings_api_timeout_entry.get().strip()

        try:
            api_timeout = int(round(float(timeout_text or DEFAULT_RENAME_API_TIMEOUT)))
            if api_timeout < 5 or api_timeout > 300:
                raise ValueError
        except ValueError:
            messagebox.showerror("错误", "AI 接口超时必须是 5 到 300 秒之间的整数。")
            return

        previous_fullscreen_mode = self.reader_windows_fullscreen_mode

        self.reader_windows_fullscreen_mode = fullscreen_mode
        self.rename_api_key = api_key
        self.rename_api_url = api_url
        self.rename_api_model = api_model
        self.rename_api_timeout = api_timeout
        self.refresh_settings_fullscreen_hint()
        self.refresh_settings_api_status_label()
        self.change_appearance_mode_event(appearance_mode)

        extra_note = ""
        if self.reader_fullscreen_mode and previous_fullscreen_mode != fullscreen_mode:
            extra_note = "，新的全屏方式会在下次进入全屏时生效"

        self.settings_status_label.configure(text=f"{success_message}{extra_note}")
        self.persist_gui_state_snapshot()
        self.log(
            f"已保存设置：外观 {self.appearance_mode} / Windows 全屏 {self.get_windows_reader_fullscreen_mode_label(self.reader_windows_fullscreen_mode)} / AI 模型 {self.rename_api_model}"
        )

    def reset_settings(self):
        if hasattr(self, "settings_appearance_optionemenu"):
            self.settings_appearance_optionemenu.set(DEFAULT_APPEARANCE_MODE)
        if hasattr(self, "settings_reader_fullscreen_optionemenu"):
            self.settings_reader_fullscreen_optionemenu.set(
                self.get_windows_reader_fullscreen_mode_label(DEFAULT_WINDOWS_READER_FULLSCREEN_MODE)
            )
        if hasattr(self, "settings_api_key_entry"):
            self.settings_api_key_entry.delete(0, tk.END)
        if hasattr(self, "settings_api_url_entry"):
            self.settings_api_url_entry.delete(0, tk.END)
            self.settings_api_url_entry.insert(0, DEFAULT_RENAME_API_URL)
        if hasattr(self, "settings_api_model_entry"):
            self.settings_api_model_entry.delete(0, tk.END)
            self.settings_api_model_entry.insert(0, DEFAULT_RENAME_API_MODEL)
        if hasattr(self, "settings_api_timeout_entry"):
            self.settings_api_timeout_entry.delete(0, tk.END)
            self.settings_api_timeout_entry.insert(0, str(DEFAULT_RENAME_API_TIMEOUT))
        if hasattr(self, "settings_show_api_key_var"):
            self.settings_show_api_key_var.set(False)
            self.toggle_settings_api_key_visibility()
        self.refresh_settings_fullscreen_hint()
        self.refresh_settings_api_status_label()
        self.save_settings(success_message="设置已恢复默认值")

    def create_feature_card(self, parent, title, desc, row, col, button_text=None, command=None):
        """创建一个首页功能介绍卡片"""
        card = ctk.CTkFrame(parent, corner_radius=15, border_width=1, border_color="#3d3d3d")
        card.grid(row=row, column=col, padx=15, pady=15, sticky="nsew")
        card.grid_columnconfigure(0, weight=1)
        
        card_title = ctk.CTkLabel(card, text=title, font=ctk.CTkFont(size=18, weight="bold"))
        card_title.pack(padx=20, pady=(20, 10))
        
        card_desc = ctk.CTkLabel(
            card,
            text=desc,
            font=ctk.CTkFont(size=13),
            justify="center",
            wraplength=320,
        )
        card_desc.pack(padx=20, pady=(0, 14))

        if command:
            ctk.CTkButton(
                card,
                text=button_text or "打开功能",
                command=command,
            ).pack(padx=20, pady=(0, 18), fill="x")
        return card

    def build_format_support_notice_text(self, context="reader"):
        lines = get_format_support_notice_lines()
        status = get_optional_comic_support_status()
        prefix = "阅读支持" if context == "reader" else "转换支持"

        if context == "convert":
            lines = [line.replace("直接支持", "可转换") for line in lines]

        if not status["rar"]["available"]:
            lines.append("提示：安装 7-Zip 后，把 7z.exe 加入 PATH 通常就够用了。")

        return prefix + "：" + "\n".join(lines)

    def refresh_format_support_labels(self):
        if hasattr(self, "reader_support_label"):
            self.reader_support_label.configure(text=self.build_format_support_notice_text("reader"))
        if hasattr(self, "convert_support_label"):
            self.convert_support_label.configure(text=self.build_format_support_notice_text("convert"))

    def show_comic_source_support_message(self, source_path, action):
        support_message = get_comic_source_requirement_message(source_path, action=action)
        if support_message:
            messagebox.showinfo("需要额外支持", support_message)
            return True
        return False

    def get_reader_zoom_mode_label(self, value):
        normalized_mode = normalize_reader_zoom_mode(value)
        return READER_ZOOM_MODE_LABELS.get(
            normalized_mode,
            READER_ZOOM_MODE_LABELS[DEFAULT_READER_ZOOM_MODE],
        )

    def get_reader_zoom_mode_value(self, label):
        return READER_ZOOM_MODE_VALUES.get(
            str(label or "").strip(),
            DEFAULT_READER_ZOOM_MODE,
        )

    def get_reader_preview_viewport_size(self):
        canvas = getattr(self, "reader_preview_canvas", None)
        if canvas is None:
            return 240, 240

        canvas_width = canvas.winfo_width() - 4
        canvas_height = canvas.winfo_height() - 4
        if canvas_width <= 1:
            canvas_width = 240
        if canvas_height <= 1:
            canvas_height = 240

        return (
            max(canvas_width, 1),
            max(canvas_height, 1),
        )

    def get_reader_effective_zoom_percent(self, viewport_size=None):
        if self.reader_source_image is None:
            return clamp_reader_zoom_percent(self.reader_zoom_percent)

        if viewport_size is None:
            viewport_size = self.get_reader_preview_viewport_size()

        target_width, _ = calculate_reader_image_size(
            self.reader_source_image.size,
            viewport_size,
            zoom_mode=self.reader_zoom_mode,
            zoom_percent=self.reader_zoom_percent,
        )
        source_width = max(self.reader_source_image.size[0], 1)
        return max(1, int(round((target_width / source_width) * 100)))

    def get_reader_scroll_key(self, entry=None, page_index=None):
        target_entry = entry if entry is not None else self.reader_current_entry
        target_page_index = self.reader_current_page_index if page_index is None else int(page_index)
        if not target_entry or target_page_index < 0:
            return None
        return (target_entry["path"], target_page_index)

    def get_reader_canvas_scroll_position(self):
        canvas = getattr(self, "reader_preview_canvas", None)
        if canvas is None:
            return (0.0, 0.0)

        try:
            x_start = normalize_reader_scroll_fraction(canvas.xview()[0])
        except (IndexError, tk.TclError, ValueError, TypeError):
            x_start = 0.0
        try:
            y_start = normalize_reader_scroll_fraction(canvas.yview()[0])
        except (IndexError, tk.TclError, ValueError, TypeError):
            y_start = 0.0
        return (x_start, y_start)

    def get_reader_saved_scroll_position(self, entry=None, page_index=None):
        scroll_key = self.get_reader_scroll_key(entry=entry, page_index=page_index)
        if scroll_key is None:
            return (0.0, 0.0)
        return self.reader_scroll_positions.get(scroll_key, (0.0, 0.0))

    def store_current_reader_scroll_position(self):
        scroll_key = self.get_reader_scroll_key()
        if scroll_key is None:
            return (0.0, 0.0)

        scroll_position = self.get_reader_canvas_scroll_position()
        self.reader_scroll_positions[scroll_key] = scroll_position
        return scroll_position

    def apply_reader_scroll_position(self, scroll_position):
        canvas = getattr(self, "reader_preview_canvas", None)
        if canvas is None:
            return

        scroll_x, scroll_y = scroll_position or (0.0, 0.0)
        canvas.xview_moveto(normalize_reader_scroll_fraction(scroll_x))
        canvas.yview_moveto(normalize_reader_scroll_fraction(scroll_y))

    def can_reader_scroll_vertically(self, direction):
        canvas = getattr(self, "reader_preview_canvas", None)
        if canvas is None:
            return False

        try:
            start, end = canvas.yview()
        except tk.TclError:
            return False

        if direction < 0:
            return start > 0.001
        if direction > 0:
            return end < 0.999
        return False

    def scroll_reader_preview_vertically(self, direction, steps=1):
        canvas = getattr(self, "reader_preview_canvas", None)
        if canvas is None:
            return False

        normalized_steps = max(1, int(abs(steps or 1)))
        if not self.can_reader_scroll_vertically(direction):
            return False

        canvas.yview_scroll(int(direction) * normalized_steps, "units")
        self.store_current_reader_scroll_position()
        return True

    def handle_reader_mousewheel(self, event):
        if getattr(self, "current_frame_name", "") != "reader" or not self.reader_current_pages:
            return None

        focused_widget = self.focus_get()
        if isinstance(focused_widget, (tk.Entry, tk.Text, tk.Listbox)):
            return None

        event_num = getattr(event, "num", None)
        event_delta = getattr(event, "delta", 0)
        if event_num == 4:
            direction = -1
            step_count = 3
        elif event_num == 5:
            direction = 1
            step_count = 3
        else:
            if event_delta == 0:
                return "break"
            direction = -1 if event_delta > 0 else 1
            step_count = max(1, abs(int(event_delta)) // 120)

        if self.scroll_reader_preview_vertically(direction, steps=step_count):
            return "break"

        if direction > 0:
            self.change_reader_page(1)
        else:
            self.change_reader_page(-1)
        return "break"

    def show_reader_preview_placeholder(self, text=None):
        canvas = getattr(self, "reader_preview_canvas", None)
        self.reader_preview_placeholder = str(text or self.reader_preview_placeholder or "").strip()
        if canvas is None:
            return

        canvas.delete("all")
        self.reader_preview_photo = None
        self.reader_preview_canvas_image_id = None
        self.reader_preview_render_key = None
        canvas_width = canvas.winfo_width()
        canvas_height = canvas.winfo_height()
        if canvas_width <= 1:
            canvas_width = 240
        if canvas_height <= 1:
            canvas_height = 240
        canvas.configure(scrollregion=(0, 0, canvas_width, canvas_height))
        canvas.create_text(
            canvas_width / 2,
            canvas_height / 2,
            text=self.reader_preview_placeholder,
            fill="#d8d8d8",
            width=max(canvas_width - 40, 180),
            justify="center",
            font=("Microsoft YaHei UI", 14),
        )
        canvas.xview_moveto(0)
        canvas.yview_moveto(0)

    def cancel_reader_preview_refresh(self):
        if self.reader_preview_refresh_after_id:
            try:
                self.after_cancel(self.reader_preview_refresh_after_id)
            except tk.TclError:
                pass
            self.reader_preview_refresh_after_id = None

    def queue_reader_preview_refresh(self, reset_scroll=False, scroll_position=None, invalidate=False):
        pending = self.reader_pending_preview_refresh or {
            "reset_scroll": False,
            "scroll_position": None,
            "invalidate": False,
        }
        pending["reset_scroll"] = pending["reset_scroll"] or bool(reset_scroll)
        pending["invalidate"] = pending["invalidate"] or bool(invalidate)

        normalized_scroll_position = None
        if scroll_position is not None:
            normalized_scroll_position = (
                normalize_reader_scroll_fraction(scroll_position[0]),
                normalize_reader_scroll_fraction(scroll_position[1]),
            )

        if pending["reset_scroll"]:
            pending["scroll_position"] = None
        elif normalized_scroll_position is not None:
            pending["scroll_position"] = normalized_scroll_position

        self.reader_pending_preview_refresh = pending

    def schedule_reader_preview_refresh(
        self,
        delay_ms=READER_PREVIEW_REFRESH_DELAY_MS,
        reset_scroll=False,
        scroll_position=None,
        invalidate=False,
    ):
        self.queue_reader_preview_refresh(
            reset_scroll=reset_scroll,
            scroll_position=scroll_position,
            invalidate=invalidate,
        )
        if self.reader_fullscreen_transition_in_progress:
            return

        self.cancel_reader_preview_refresh()
        try:
            self.reader_preview_refresh_after_id = self.after(
                max(1, int(delay_ms or READER_PREVIEW_REFRESH_DELAY_MS)),
                self.flush_scheduled_reader_preview_refresh,
            )
        except tk.TclError:
            self.reader_preview_refresh_after_id = None

    def flush_scheduled_reader_preview_refresh(self):
        self.reader_preview_refresh_after_id = None
        pending = self.reader_pending_preview_refresh or {}
        self.reader_pending_preview_refresh = None
        if pending.get("invalidate"):
            self.reader_preview_render_key = None
        self.refresh_reader_preview(
            reset_scroll=bool(pending.get("reset_scroll", False)),
            scroll_position=pending.get("scroll_position"),
        )

    def cancel_reader_fullscreen_transition(self):
        if self.reader_fullscreen_transition_after_id:
            try:
                self.after_cancel(self.reader_fullscreen_transition_after_id)
            except tk.TclError:
                pass
            self.reader_fullscreen_transition_after_id = None
        self.reader_fullscreen_transition_in_progress = False

    def finish_reader_fullscreen_transition(self, refresh=True):
        self.reader_fullscreen_transition_after_id = None
        self.reader_fullscreen_transition_in_progress = False
        try:
            self.update_idletasks()
        except tk.TclError:
            return
        if not refresh or getattr(self, "current_frame_name", "") != "reader":
            self.cancel_reader_preview_refresh()
            self.reader_pending_preview_refresh = None
            return
        self.schedule_reader_preview_refresh(invalidate=True)

    def get_reader_fullscreen_transition_delay_ms(self):
        if os.name == "nt":
            if self.reader_windows_fullscreen_mode == "exclusive":
                return READER_EXCLUSIVE_FULLSCREEN_TRANSITION_DELAY_MS
            return READER_SMOOTH_FULLSCREEN_TRANSITION_DELAY_MS
        return READER_FULLSCREEN_TRANSITION_DELAY_MS

    def begin_reader_fullscreen_transition(self, refresh=True):
        self.cancel_reader_fullscreen_transition()
        self.cancel_reader_preview_refresh()
        self.reader_fullscreen_transition_in_progress = True
        try:
            self.reader_fullscreen_transition_after_id = self.after(
                self.get_reader_fullscreen_transition_delay_ms(),
                lambda: self.finish_reader_fullscreen_transition(refresh=refresh),
            )
        except tk.TclError:
            self.reader_fullscreen_transition_after_id = None
            self.reader_fullscreen_transition_in_progress = False
            if refresh:
                self.schedule_reader_preview_refresh(invalidate=True)

    def get_window_state(self):
        try:
            return str(self.state())
        except tk.TclError:
            return "normal"

    def remember_reader_window_state(self):
        self.reader_window_state_before_fullscreen = self.get_window_state()
        try:
            self.reader_window_geometry_before_fullscreen = self.geometry()
        except tk.TclError:
            self.reader_window_geometry_before_fullscreen = ""

    def apply_reader_fullscreen_window_state(self):
        if os.name == "nt":
            if self.reader_windows_fullscreen_mode == "exclusive":
                try:
                    self.state("normal")
                except tk.TclError:
                    pass
                try:
                    self.attributes("-topmost", True)
                except tk.TclError:
                    pass
                try:
                    self.attributes("-fullscreen", True)
                except tk.TclError:
                    try:
                        self.state("zoomed")
                    except tk.TclError:
                        pass
            else:
                try:
                    self.attributes("-fullscreen", False)
                except tk.TclError:
                    pass
                try:
                    self.attributes("-topmost", False)
                except tk.TclError:
                    pass
                try:
                    self.state("zoomed")
                except tk.TclError:
                    pass
            return

        try:
            self.attributes("-fullscreen", True)
        except tk.TclError:
            pass

    def restore_reader_window_state(self):
        previous_state = self.reader_window_state_before_fullscreen or "normal"
        previous_geometry = self.reader_window_geometry_before_fullscreen

        try:
            self.attributes("-topmost", False)
        except tk.TclError:
            pass

        try:
            self.attributes("-fullscreen", False)
        except tk.TclError:
            pass

        try:
            self.state("normal")
        except tk.TclError:
            pass

        if previous_geometry and previous_state == "normal":
            try:
                self.geometry(previous_geometry)
            except tk.TclError:
                pass

        if previous_state != "normal":
            try:
                self.state(previous_state)
            except tk.TclError:
                pass

    def handle_reader_preview_configure(self):
        if self.reader_source_image is None:
            self.show_reader_preview_placeholder(self.reader_preview_placeholder)
            return

        if getattr(self, "current_frame_name", "") != "reader":
            return

        self.schedule_reader_preview_refresh(invalidate=True)

    def handle_reader_zoom_mode_change(self, selected_label):
        self.set_reader_zoom_mode(
            self.get_reader_zoom_mode_value(selected_label),
            reset_scroll=True,
        )

    def update_reader_zoom_controls(self):
        has_pages = self.reader_current_entry is not None and bool(self.reader_current_pages)
        control_state = "normal" if has_pages else "disabled"
        effective_zoom = self.get_reader_effective_zoom_percent()

        if hasattr(self, "reader_zoom_value_label"):
            self.reader_zoom_value_label.configure(text=f"{effective_zoom}%")
        if hasattr(self, "reader_zoom_out_button"):
            self.reader_zoom_out_button.configure(state=control_state)
        if hasattr(self, "reader_zoom_in_button"):
            self.reader_zoom_in_button.configure(state=control_state)
        if hasattr(self, "reader_zoom_reset_button"):
            self.reader_zoom_reset_button.configure(state=control_state)
        if hasattr(self, "reader_zoom_mode_menu"):
            self.reader_zoom_mode_menu.configure(state=control_state)
            self.reader_zoom_mode_menu.set(self.get_reader_zoom_mode_label(self.reader_zoom_mode))

    def set_reader_zoom_mode(self, mode, persist=True, refresh=True, reset_scroll=False):
        self.reader_zoom_mode = normalize_reader_zoom_mode(mode)
        self.update_reader_zoom_controls()

        if refresh:
            self.refresh_reader_preview(reset_scroll=reset_scroll)
        if persist:
            self.persist_gui_state_snapshot()

    def set_reader_zoom_percent(self, zoom_percent, persist=True, refresh=True, reset_scroll=False):
        self.reader_zoom_percent = clamp_reader_zoom_percent(
            zoom_percent,
            fallback=self.reader_zoom_percent,
        )
        self.reader_zoom_mode = "manual"
        self.update_reader_zoom_controls()

        if refresh:
            self.refresh_reader_preview(reset_scroll=reset_scroll)
        if persist:
            self.persist_gui_state_snapshot()

    def adjust_reader_zoom(self, delta):
        if self.reader_source_image is None:
            return

        base_zoom = self.get_reader_effective_zoom_percent()
        self.set_reader_zoom_percent(base_zoom + int(delta), reset_scroll=True)

    def reset_reader_zoom(self):
        if self.reader_source_image is None:
            return

        self.set_reader_zoom_percent(100, reset_scroll=True)

    def set_reader_info_text(self, text):
        self.reader_info_textbox.configure(state="normal")
        self.reader_info_textbox.delete("1.0", "end")
        self.reader_info_textbox.insert("1.0", text)
        self.reader_info_textbox.configure(state="disabled")

    def update_reader_focus_button(self):
        if hasattr(self, "reader_focus_button"):
            self.reader_focus_button.configure(
                text="专注阅读中" if self.reader_fullscreen_mode else ("退出专注阅读" if self.reader_focus_mode else "专注阅读"),
                state="disabled" if self.reader_fullscreen_mode else "normal",
            )
        if hasattr(self, "reader_workspace_hint_label"):
            hint_text = (
                "全屏阅读已开启：应用侧边栏和阅读页头部已隐藏。按 Esc 或双击预览区即可退出全屏。"
                if self.reader_fullscreen_mode
                else (
                    "专注阅读已开启：左侧资料区和文件详情会暂时折叠，当前空间优先用于放大预览漫画页面。滚轮会先滚动页面，到边界时自动翻页；按 F11 可进入全屏。"
                    if self.reader_focus_mode
                    else "阅读页已独立出来，可从左侧浏览文件并在右侧翻页。滚轮会先滚动页面，到边界时自动翻页；开启专注阅读后会折叠资料区，按 F11 或双击预览区可进入全屏。"
                )
            )
            self.reader_workspace_hint_label.configure(text=hint_text)

    def update_reader_fullscreen_button(self):
        if hasattr(self, "reader_fullscreen_button"):
            self.reader_fullscreen_button.configure(
                text="退出全屏" if self.reader_fullscreen_mode else "全屏阅读"
            )

    def set_reader_focus_mode(self, enabled, persist=True, refresh=True):
        scroll_position = self.store_current_reader_scroll_position()
        self.reader_focus_mode = bool(enabled)

        if hasattr(self, "reader_sidebar_frame") and hasattr(self, "reader_content_frame"):
            if self.reader_focus_mode:
                self.reader_sidebar_frame.grid_remove()
                self.reader_info_textbox.grid_remove()
                self.reader_content_frame.grid_configure(
                    row=1,
                    column=0,
                    columnspan=2,
                    padx=20,
                    pady=(0, 20),
                )
            else:
                self.reader_sidebar_frame.grid()
                self.reader_info_textbox.grid()
                self.reader_content_frame.grid_configure(
                    row=1,
                    column=1,
                    columnspan=1,
                    padx=(10, 20),
                    pady=(0, 20),
                )

        self.update_reader_focus_button()
        self.update_reader_fullscreen_button()

        if refresh:
            self.schedule_reader_preview_refresh(
                scroll_position=scroll_position,
                invalidate=True,
            )

        if persist:
            self.persist_gui_state_snapshot()

    def toggle_reader_focus_mode(self):
        self.set_reader_focus_mode(not self.reader_focus_mode)

    def set_reader_fullscreen_mode(self, enabled, refresh=True):
        target_mode = bool(enabled)
        if target_mode == self.reader_fullscreen_mode:
            self.update_reader_focus_button()
            self.update_reader_fullscreen_button()
            return

        scroll_position = self.store_current_reader_scroll_position()
        self.reader_fullscreen_mode = target_mode
        self.begin_reader_fullscreen_transition(refresh=refresh)

        if self.reader_fullscreen_mode:
            self.remember_reader_window_state()
            self.apply_reader_fullscreen_window_state()
            self.reader_focus_mode_before_fullscreen = self.reader_focus_mode
            self.set_reader_focus_mode(True, persist=False, refresh=False)
            self.sidebar_frame.grid_remove()
            self.reader_workspace_header.grid_remove()
            self.reader_content_frame.grid_configure(padx=20, pady=20)
            self.log("已进入全屏阅读模式")
            self.status_label.configure(text="全屏阅读模式已开启")
        else:
            self.restore_reader_window_state()
            self.sidebar_frame.grid()
            self.reader_workspace_header.grid()
            restored_focus_mode = bool(self.reader_focus_mode_before_fullscreen)
            self.set_reader_focus_mode(restored_focus_mode, persist=False, refresh=False)
            if restored_focus_mode:
                self.reader_content_frame.grid_configure(padx=20, pady=(0, 20))
            else:
                self.reader_content_frame.grid_configure(padx=(10, 20), pady=(0, 20))
            self.log("已退出全屏阅读模式")
            self.status_label.configure(text="已退出全屏阅读模式")

        self.update_reader_focus_button()
        self.update_reader_fullscreen_button()

        if refresh:
            self.schedule_reader_preview_refresh(
                scroll_position=scroll_position,
                invalidate=True,
            )

    def toggle_reader_fullscreen_mode(self):
        if getattr(self, "current_frame_name", "") != "reader":
            self.select_frame_by_name("reader")
        self.set_reader_fullscreen_mode(not self.reader_fullscreen_mode)

    def get_reader_entry_kind_label(self, entry):
        if not entry:
            return ""

        kind = entry.get("kind")
        if kind == "folder":
            return "文件夹"
        if kind == "pdf":
            return "PDF"
        return entry.get("format") or "压缩包"

    def browse_reader_library_dir(self):
        directory = filedialog.askdirectory(title="选择漫画目录")
        if not directory:
            return
        self.refresh_reader_library(initial_path=directory)
        self.persist_gui_state_snapshot()

    def browse_reader_library_file(self):
        file_path = filedialog.askopenfilename(
            title="选择漫画文件",
            filetypes=[
                ("Comic Files", "*.cbz *.zip *.cbr *.rar *.cb7 *.7z *.pdf"),
                ("CBZ Files", "*.cbz"),
                ("ZIP Files", "*.zip"),
                ("CBR Files", "*.cbr"),
                ("RAR Files", "*.rar"),
                ("CB7 Files", "*.cb7"),
                ("7z Files", "*.7z"),
                ("PDF Files", "*.pdf"),
                ("All Files", "*.*"),
            ],
        )
        if not file_path:
            return
        if self.show_comic_source_support_message(file_path, "打开"):
            self.reader_source_entry.delete(0, tk.END)
            self.reader_source_entry.insert(0, file_path)
            self.reset_reader_session("当前文件需要额外支持，详情见上方提示。")
            self.persist_gui_state_snapshot()
            return
        self.refresh_reader_library(initial_path=file_path)
        self.persist_gui_state_snapshot()

    def get_selected_reader_entry(self):
        selection = self.reader_listbox.curselection()
        if not selection:
            return None
        try:
            index = int(selection[0])
        except (TypeError, ValueError):
            return None
        if index < 0 or index >= len(self.reader_library_entries):
            return None
        return self.reader_library_entries[index]

    def find_reader_entry_index(self, target_path):
        normalized_target = str(target_path or "").strip()
        if not normalized_target:
            return None

        for index, entry in enumerate(self.reader_library_entries):
            if entry["path"] == normalized_target:
                return index

        return None

    def select_reader_entry_by_path(self, target_path):
        index = self.find_reader_entry_index(target_path)
        if index is None:
            return None

        self.reader_listbox.selection_clear(0, tk.END)
        self.reader_listbox.selection_set(index)
        self.on_reader_selection_changed()
        return self.reader_library_entries[index]

    def update_reader_file_actions(self, entry=None):
        state = "normal" if entry else "disabled"
        self.reader_open_button.configure(state=state)
        self.reader_open_file_button.configure(state=state)
        self.reader_open_folder_button.configure(state=state)

    def update_reader_details(self, entry=None):
        if not entry:
            self.reader_title_label.configure(text="漫画阅读器")
            self.set_reader_info_text("选择左侧列表中的漫画后，可以在这里查看文件信息并开始阅读。")
            self.update_reader_file_actions(None)
            return

        kind_label = self.get_reader_entry_kind_label(entry)
        modified_text = datetime.fromtimestamp(entry["modified_ts"]).strftime("%Y-%m-%d %H:%M:%S")
        info_lines = [
            f"名称: {entry['name']}",
            f"类型: {kind_label}",
            f"页数: {entry['page_count']}",
            f"大小: {format_bytes(entry['size_bytes'])}",
            f"修改时间: {modified_text}",
            f"路径: {entry['path']}",
        ]
        support_message = get_comic_source_requirement_message(entry["path"], action="打开")
        if support_message:
            info_lines.append("")
            info_lines.append(f"提示: {support_message}")

        info_text = "\n".join(info_lines)
        self.reader_title_label.configure(text=entry["name"])
        self.set_reader_info_text(info_text)
        self.update_reader_file_actions(entry)

    def reset_reader_session(self, placeholder="从左侧选择漫画后即可在这里翻页阅读"):
        self.store_current_reader_scroll_position()
        self.reader_current_entry = None
        self.reader_current_pages = []
        self.reader_current_page_index = -1
        self.reader_source_image = None
        self.reader_preview_photo = None
        self.reader_preview_canvas_image_id = None
        self.reader_preview_render_key = None
        self.show_reader_preview_placeholder(placeholder)
        self.update_reader_page_controls()
        self.update_reader_zoom_controls()

    def refresh_reader_library(self, initial_path=None, select_first=True):
        if initial_path is not None:
            self.reader_source_entry.delete(0, tk.END)
            self.reader_source_entry.insert(0, initial_path)

        source_path = self.reader_source_entry.get().strip()
        if not source_path:
            self.reader_listbox.delete(0, tk.END)
            self.reader_library_entries = []
            self.update_reader_details(None)
            self.reset_reader_session("请先选择漫画目录或 CBZ/ZIP/CBR/RAR/7z/PDF 文件")
            return

        expanded_source = str(Path(source_path).expanduser())
        self.reader_source_entry.delete(0, tk.END)
        self.reader_source_entry.insert(0, expanded_source)

        if not os.path.exists(expanded_source):
            self.reader_listbox.delete(0, tk.END)
            self.reader_library_entries = []
            self.update_reader_details(None)
            self.reset_reader_session("所选路径不存在，请重新选择")
            return

        if Path(expanded_source).is_file():
            support_message = get_comic_source_requirement_message(expanded_source, action="打开")
            if support_message:
                self.reader_listbox.delete(0, tk.END)
                self.reader_library_entries = []
                self.update_reader_details(None)
                self.reset_reader_session("当前文件需要额外支持，详情见上方提示。")
                if hasattr(self, "status_label"):
                    self.status_label.configure(text="当前文件缺少必要支持")
                return

        selected_entry = self.get_selected_reader_entry()
        previous_path = ""
        if selected_entry:
            previous_path = selected_entry["path"]
        elif self.reader_current_entry:
            previous_path = self.reader_current_entry["path"]

        try:
            entries = discover_comics(expanded_source)
        except Exception as exc:
            messagebox.showerror("错误", f"扫描漫画文件失败: {exc}")
            return

        self.reader_library_entries = entries
        self.reader_listbox.delete(0, tk.END)
        for item in entries:
            kind_text = self.get_reader_entry_kind_label(item)
            self.reader_listbox.insert(tk.END, f"{item['name']}  [{kind_text} · {item['page_count']} 页]")

        if not entries:
            self.update_reader_details(None)
            self.reset_reader_session("当前路径下没有找到可阅读的漫画文件")
            if hasattr(self, "status_label"):
                self.status_label.configure(text="未发现可阅读的漫画文件")
            return

        target_index = None
        for index, item in enumerate(entries):
            if item["path"] == previous_path:
                target_index = index
                break

        if target_index is None and select_first:
            target_index = 0

        if target_index is not None:
            self.reader_listbox.selection_clear(0, tk.END)
            self.reader_listbox.selection_set(target_index)
            self.on_reader_selection_changed()
        else:
            self.update_reader_details(None)

        if hasattr(self, "status_label"):
            self.status_label.configure(text=f"已加载 {len(entries)} 个本地漫画条目")

    def on_reader_selection_changed(self):
        entry = self.get_selected_reader_entry()
        self.update_reader_details(entry)

    def open_selected_reader_item(self):
        entry = self.get_selected_reader_entry()
        if not entry:
            messagebox.showerror("错误", "请先选择漫画文件")
            return

        source_path = Path(entry["path"])
        if source_path.is_dir():
            self.open_folder(str(source_path))
            return

        try:
            os.startfile(str(source_path))
        except Exception as exc:
            messagebox.showerror("错误", f"无法打开文件: {exc}")

    def open_selected_reader_parent(self):
        entry = self.get_selected_reader_entry()
        if not entry:
            messagebox.showerror("错误", "请先选择漫画文件")
            return

        source_path = Path(entry["path"])
        target_dir = source_path if source_path.is_dir() else source_path.parent
        self.open_folder(str(target_dir))

    def open_reader_entry(self, entry, target_page=1, persist=True, announce=True):
        if not entry:
            return False

        if self.show_comic_source_support_message(entry["path"], "打开"):
            if hasattr(self, "status_label"):
                self.status_label.configure(text="当前文件缺少必要支持")
            return False

        try:
            pages = list_comic_pages(entry["path"])
        except Exception as exc:
            messagebox.showerror("错误", f"读取漫画页失败: {exc}")
            return False

        if not pages:
            messagebox.showerror("错误", "当前漫画没有可读取的页面")
            return False

        try:
            target_page_number = int(target_page)
        except (TypeError, ValueError):
            target_page_number = 1

        self.store_current_reader_scroll_position()
        self.reader_current_entry = entry
        self.reader_current_pages = pages
        self.reader_current_page_index = -1
        if not self.set_reader_page(
            min(max(1, target_page_number), len(pages)) - 1,
            persist=persist,
        ):
            return False
        if announce:
            self.log(f"已打开本地漫画: {entry['name']}")
            self.status_label.configure(text=f"正在阅读: {entry['name']}")

        return True

    def open_selected_reader_comic(self):
        entry = self.get_selected_reader_entry()
        if not entry:
            messagebox.showerror("错误", "请先选择漫画文件")
            return

        self.open_reader_entry(entry)

    def update_reader_page_controls(self):
        total_pages = len(self.reader_current_pages)
        has_pages = total_pages > 0 and self.reader_current_entry is not None
        current_page = self.reader_current_page_index + 1 if has_pages else 0

        self.reader_page_total_label.configure(text=f"/ {total_pages}")
        self.reader_page_entry.configure(state="normal" if has_pages else "disabled")
        self.reader_page_entry.delete(0, tk.END)
        if has_pages:
            self.reader_page_entry.insert(0, str(current_page))

        self.reader_first_button.configure(
            state="normal" if has_pages and self.reader_current_page_index > 0 else "disabled"
        )
        self.reader_prev_button.configure(
            state="normal" if has_pages and self.reader_current_page_index > 0 else "disabled"
        )
        self.reader_next_button.configure(
            state="normal" if has_pages and self.reader_current_page_index < total_pages - 1 else "disabled"
        )
        self.reader_last_button.configure(
            state="normal" if has_pages and self.reader_current_page_index < total_pages - 1 else "disabled"
        )
        self.update_reader_zoom_controls()

    def set_reader_page(self, index, persist=True):
        if not self.reader_current_entry or not self.reader_current_pages:
            return False

        if index < 0 or index >= len(self.reader_current_pages):
            return False

        previous_page_index = self.reader_current_page_index
        if previous_page_index >= 0:
            current_scroll_position = self.store_current_reader_scroll_position()
        else:
            current_scroll_position = (0.0, 0.0)

        page_name = self.reader_current_pages[index]
        try:
            self.reader_source_image = load_comic_page_image(self.reader_current_entry["path"], page_name)
        except Exception as exc:
            messagebox.showerror("错误", f"读取漫画页面失败: {exc}")
            return False

        if previous_page_index == index:
            target_scroll_position = current_scroll_position
        else:
            target_scroll_position = self.get_reader_saved_scroll_position(page_index=index)
        self.reader_current_page_index = index
        self.update_reader_page_controls()
        self.refresh_reader_preview(scroll_position=target_scroll_position)
        self.status_label.configure(
            text=f"正在阅读 {self.reader_current_entry['name']} - 第 {index + 1}/{len(self.reader_current_pages)} 页"
        )
        if persist:
            self.persist_gui_state_snapshot()
        return True

    def change_reader_page(self, delta):
        if self.reader_current_page_index < 0:
            return
        self.set_reader_page(self.reader_current_page_index + int(delta))

    def go_to_last_reader_page(self):
        if not self.reader_current_pages:
            return
        self.set_reader_page(len(self.reader_current_pages) - 1)

    def jump_reader_page(self):
        if not self.reader_current_pages:
            return

        try:
            page_number = int(self.reader_page_entry.get().strip())
        except ValueError:
            messagebox.showerror("错误", "请输入有效的页码")
            return

        if page_number < 1 or page_number > len(self.reader_current_pages):
            messagebox.showerror("错误", "页码超出范围")
            return

        self.set_reader_page(page_number - 1)

    def handle_reader_shortcut(self, action):
        if getattr(self, "current_frame_name", "") != "reader":
            return

        if action == "toggle_fullscreen":
            self.toggle_reader_fullscreen_mode()
            return

        if action == "escape":
            if self.reader_fullscreen_mode:
                self.set_reader_fullscreen_mode(False)
                return
            if self.reader_focus_mode:
                self.set_reader_focus_mode(False)
            return

        if not self.reader_current_pages:
            return

        focused_widget = self.focus_get()
        if isinstance(focused_widget, (tk.Entry, tk.Text, tk.Listbox)):
            return

        if action == "prev":
            self.change_reader_page(-1)
        elif action == "next":
            self.change_reader_page(1)
        elif action == "first":
            self.set_reader_page(0)
        elif action == "last":
            self.go_to_last_reader_page()

    def refresh_reader_preview(self, reset_scroll=False, scroll_position=None):
        self.cancel_reader_preview_refresh()
        self.reader_pending_preview_refresh = None
        canvas = getattr(self, "reader_preview_canvas", None)
        if canvas is None:
            return

        if self.reader_source_image is None:
            self.show_reader_preview_placeholder(self.reader_preview_placeholder)
            self.update_reader_zoom_controls()
            return

        if reset_scroll:
            target_scroll_position = (0.0, 0.0)
        elif scroll_position is not None:
            target_scroll_position = (
                normalize_reader_scroll_fraction(scroll_position[0]),
                normalize_reader_scroll_fraction(scroll_position[1]),
            )
        else:
            target_scroll_position = self.get_reader_canvas_scroll_position()

        viewport_size = self.get_reader_preview_viewport_size()
        target_size = calculate_reader_image_size(
            self.reader_source_image.size,
            viewport_size,
            zoom_mode=self.reader_zoom_mode,
            zoom_percent=self.reader_zoom_percent,
        )
        render_key = (
            id(self.reader_source_image),
            self.reader_current_page_index,
            self.reader_zoom_mode,
            self.reader_zoom_percent,
            viewport_size,
            target_size,
        )

        if self.reader_preview_render_key == render_key and self.reader_preview_canvas_image_id is not None:
            self.apply_reader_scroll_position(target_scroll_position)
            self.update_reader_zoom_controls()
            return

        if target_size == self.reader_source_image.size:
            preview_image = self.reader_source_image.copy()
        else:
            preview_image = self.reader_source_image.resize(target_size, Image.LANCZOS)

        preview_photo = ImageTk.PhotoImage(preview_image)
        canvas.delete("all")

        viewport_width, viewport_height = viewport_size
        image_width, image_height = target_size
        image_x = max((viewport_width - image_width) // 2, 0)
        image_y = max((viewport_height - image_height) // 2, 0)
        self.reader_preview_canvas_image_id = canvas.create_image(
            image_x,
            image_y,
            anchor="nw",
            image=preview_photo,
        )
        canvas.configure(
            scrollregion=(
                0,
                0,
                max(viewport_width, image_width),
                max(viewport_height, image_height),
            )
        )

        self.reader_preview_photo = preview_photo
        self.reader_preview_render_key = render_key
        self.apply_reader_scroll_position(target_scroll_position)
        self.update_reader_zoom_controls()

    # ========== 核心业务逻辑 (保持不变) ==========
    def browse_save_dir(self):
        directory = filedialog.askdirectory(title="选择保存目录")
        if directory:
            self.save_entry.delete(0, tk.END)
            self.save_entry.insert(0, directory)
            self.comic_dl_downloader.set_base_dir(directory)

    def get_supported_sites_error_message(self):
        return "不支持的网站。\n\n当前支持：\n" + self.comic_dl_downloader.get_supported_sites_summary()

    def get_chapter_failure_policy_label(self, value):
        return CHAPTER_FAILURE_POLICY_LABELS.get(value, CHAPTER_FAILURE_POLICY_LABELS["continue"])

    def get_chapter_failure_policy_value(self, label):
        return CHAPTER_FAILURE_POLICY_VALUES.get(label, "continue")

    def refresh_supported_sites_summary(self):
        self.supported_sites_label.configure(text=self.comic_dl_downloader.get_supported_sites_summary())

    def on_site_override_selected(self, selected_key):
        self.load_site_override_form(selected_key)

    def load_site_override_form(self, selected_key=None):
        key = selected_key or self.site_override_var.get().strip()
        if not key:
            self.site_override_workers_entry.delete(0, tk.END)
            self.site_override_retries_entry.delete(0, tk.END)
            self.site_override_delay_entry.delete(0, tk.END)
            self.site_override_timeout_entry.delete(0, tk.END)
            self.site_failure_policy_var.set(self.get_chapter_failure_policy_label("continue"))
            self.site_override_status_label.configure(text="没有可配置的站点")
            return

        site_info = self.comic_dl_downloader.describe_site_by_key(key)
        if not site_info:
            self.site_override_status_label.configure(text=f"未找到站点配置: {key}")
            return

        self.site_override_var.set(site_info["key"])
        self.site_override_workers_entry.delete(0, tk.END)
        self.site_override_workers_entry.insert(0, str(site_info["max_workers"]))
        self.site_override_retries_entry.delete(0, tk.END)
        self.site_override_retries_entry.insert(0, str(site_info["max_retries"]))
        self.site_override_delay_entry.delete(0, tk.END)
        self.site_override_delay_entry.insert(0, f"{site_info['download_delay']:.2f}")
        self.site_override_timeout_entry.delete(0, tk.END)
        self.site_override_timeout_entry.insert(0, f"{site_info['request_timeout']:.1f}")
        self.site_failure_policy_var.set(
            self.get_chapter_failure_policy_label(site_info["chapter_failure_policy"])
        )
        failure_policy_label = self.get_chapter_failure_policy_label(site_info["chapter_failure_policy"])
        if site_info["has_override"]:
            status = (
                f"{site_info['display_name']} 当前使用覆盖配置: "
                f"并发 {site_info['max_workers']} / 重试 {site_info['max_retries']} / 间隔 {site_info['download_delay']:.2f}s / "
                f"超时 {site_info['request_timeout']:.1f}s / 失败策略 {failure_policy_label}；"
                f"默认值为 并发 {site_info['default_max_workers']} / 重试 {site_info['default_max_retries']} / "
                f"间隔 {site_info['default_download_delay']:.2f}s / 超时 {site_info['default_request_timeout']:.1f}s / "
                f"失败策略 {self.get_chapter_failure_policy_label(site_info['default_chapter_failure_policy'])}"
            )
        else:
            status = (
                f"{site_info['display_name']} 当前使用默认配置: "
                f"并发 {site_info['default_max_workers']} / 重试 {site_info['default_max_retries']} / "
                f"间隔 {site_info['default_download_delay']:.2f}s / 超时 {site_info['default_request_timeout']:.1f}s / "
                f"失败策略 {self.get_chapter_failure_policy_label(site_info['default_chapter_failure_policy'])}"
            )
        self.site_override_status_label.configure(text=status)

    def save_site_override_settings(self):
        key = self.site_override_var.get().strip()
        workers_value = self.site_override_workers_entry.get().strip()
        retries_value = self.site_override_retries_entry.get().strip()
        delay_value = self.site_override_delay_entry.get().strip()
        timeout_value = self.site_override_timeout_entry.get().strip()
        failure_policy = self.get_chapter_failure_policy_value(self.site_failure_policy_var.get().strip())
        if not key:
            messagebox.showerror("错误", "请选择要配置的站点")
            return

        try:
            max_workers = int(workers_value)
            if max_workers < 1 or max_workers > 32:
                raise ValueError
        except ValueError:
            messagebox.showerror("错误", "并发数必须是 1 到 32 之间的整数")
            return

        try:
            max_retries = int(retries_value)
            if max_retries < 1 or max_retries > 10:
                raise ValueError
        except ValueError:
            messagebox.showerror("错误", "重试次数必须是 1 到 10 之间的整数")
            return

        try:
            download_delay = float(delay_value)
            if download_delay < 0 or download_delay > 5:
                raise ValueError
        except ValueError:
            messagebox.showerror("错误", "下载间隔必须是 0 到 5 之间的数字")
            return

        try:
            request_timeout = float(timeout_value)
            if request_timeout < 5 or request_timeout > 300:
                raise ValueError
        except ValueError:
            messagebox.showerror("错误", "请求超时必须是 5 到 300 之间的数字")
            return

        try:
            site_info = self.comic_dl_downloader.set_site_override(
                key,
                max_workers=max_workers,
                max_retries=max_retries,
                download_delay=download_delay,
                request_timeout=request_timeout,
                chapter_failure_policy=failure_policy,
            )
        except Exception as exc:
            messagebox.showerror("错误", f"保存站点配置失败: {exc}")
            return

        self.refresh_supported_sites_summary()
        self.load_site_override_form(key)
        self.update_site_status()
        self.log(
            f"已保存站点配置: {site_info['display_name']} -> "
            f"并发 {site_info['max_workers']} / 重试 {site_info['max_retries']} / 间隔 {site_info['download_delay']:.2f}s / "
            f"超时 {site_info['request_timeout']:.1f}s / 失败策略 {self.get_chapter_failure_policy_label(site_info['chapter_failure_policy'])}"
        )

    def reset_site_override_settings(self):
        key = self.site_override_var.get().strip()
        if not key:
            messagebox.showerror("错误", "请选择要恢复默认的站点")
            return

        try:
            site_info = self.comic_dl_downloader.reset_site_override(key)
        except Exception as exc:
            messagebox.showerror("错误", f"恢复默认配置失败: {exc}")
            return

        self.refresh_supported_sites_summary()
        self.load_site_override_form(key)
        self.update_site_status()
        if site_info:
            self.log(f"已恢复站点默认配置: {site_info['display_name']}")

    def update_site_status(self, event=None):
        url = self.url_entry.get().strip()
        if not url:
            self.site_status_label.configure(text="等待输入 URL")
            return

        site_info = self.comic_dl_downloader.describe_site(url)
        if site_info:
            self.site_override_var.set(site_info["key"])
            self.load_site_override_form(site_info["key"])
            domains = ", ".join(site_info["domains"]) if site_info["domains"] else site_info["key"]
            browser_text = "是" if site_info["requires_browser"] else "否"
            notes = site_info["notes"] or "无"
            worker_text = str(site_info["max_workers"])
            if site_info["has_override"]:
                worker_text += f"（已覆盖默认 {site_info['default_max_workers']}）"
            retry_text = str(site_info["max_retries"])
            if site_info["override_max_retries"] is not None:
                retry_text += f"（已覆盖默认 {site_info['default_max_retries']}）"
            delay_text = f"{site_info['download_delay']:.2f}s"
            if site_info["override_download_delay"] is not None:
                delay_text += f"（已覆盖默认 {site_info['default_download_delay']:.2f}s）"
            timeout_text = f"{site_info['request_timeout']:.1f}s"
            if site_info["override_request_timeout"] is not None:
                timeout_text += f"（已覆盖默认 {site_info['default_request_timeout']:.1f}s）"
            failure_policy_text = self.get_chapter_failure_policy_label(site_info["chapter_failure_policy"])
            if site_info["override_chapter_failure_policy"] is not None:
                failure_policy_text += (
                    f"（已覆盖默认 {self.get_chapter_failure_policy_label(site_info['default_chapter_failure_policy'])}）"
                )
            self.site_status_label.configure(
                text=(
                    f"已识别为 {site_info['display_name']} 模块\n"
                    f"域名: {domains}\n"
                    f"当前并发: {worker_text}\n"
                    f"当前重试: {retry_text}\n"
                    f"下载间隔: {delay_text}\n"
                    f"请求超时: {timeout_text}\n"
                    f"失败策略: {failure_policy_text}\n"
                    f"浏览器辅助: {browser_text}\n"
                    f"备注: {notes}"
                )
            )
        else:
            self.site_status_label.configure(text="未识别到匹配模块，请确认链接域名是否受支持")

    def fetch_comic_info(self):
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showerror("错误", "请输入漫画链接")
            return
        self.update_site_status()
        
        self.show_progress()
        self.log(f"正在获取漫画信息...")
        self.fetch_button.configure(state="disabled")
        self.reset_progress()
        self.progress_bar.configure(mode="indeterminate")
        self.progress_bar.start()
        
        def fetch_thread():
            parser = None
            try:
                parser = self.comic_dl_downloader.get_parser(url)
                if not parser:
                    self.queue.put(("error", self.get_supported_sites_error_message()))
                    return
                
                comic_title, chapter_links = parser.get_comic_info(url)
                if not comic_title:
                    self.queue.put(("error", "无法获取漫画信息"))
                    return
                
                self.queue.put(("success", (comic_title, chapter_links)))
            except Exception as e:
                self.queue.put(("error", f"获取信息失败: {str(e)}"))
            finally:
                close_method = getattr(parser, "close", None)
                if callable(close_method):
                    try:
                        close_method()
                    except Exception:
                        pass
                self.queue.put(("fetch_done", None))
        
        threading.Thread(target=fetch_thread, daemon=True).start()

    def start_comic_dl_download(self):
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showerror("错误", "请输入漫画链接")
            return
        self.update_site_status()
        
        selected_indices = self.chapter_listbox.curselection()
        if not selected_indices:
            messagebox.showerror("错误", "请选择要下载的章节")
            return
        
        chapter_links = []
        for i in selected_indices:
            chapter_links.append(self.chapter_data[i])
        
        self.is_cancelled = False
        self.download_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.reset_progress()
        
        def download_thread():
            parser = None
            stopped_due_to_failure = False
            try:
                parser = self.comic_dl_downloader.get_parser(url)
                if not parser:
                    self.queue.put(("error", self.get_supported_sites_error_message()))
                    return
                
                total_chapters = len(chapter_links)
                for i, (chapter_name, chapter_url) in enumerate(chapter_links):
                    if self.is_cancelled:
                        break
                    
                    progress = (i / total_chapters) * 100
                    self.enqueue_progress_update(progress, force=True)
                    self.queue.put(("info", f"正在下载章节 {i+1}/{total_chapters}: {chapter_name}"))
                    
                    chapter_url = self.comic_dl_downloader.resolve_chapter_url(url, chapter_url)
                    
                    self.queue.put(("info", f"开始下载章节: {chapter_name}"))
                    
                    def chapter_progress_callback(msg):
                        if "下载图片" in msg:
                            match = re.search(r"(\d+)/(\d+)", msg)
                            if match:
                                curr, total = map(int, match.groups())
                                chapter_progress = (curr / total) * (100 / total_chapters)
                                total_progress = (i / total_chapters) * 100 + chapter_progress
                                self.enqueue_progress_update(total_progress)
                        self.queue.put(("info", msg))
                    
                    result = self.comic_dl_downloader.download_chapter(self.comic_title, chapter_name, chapter_url, parser, chapter_progress_callback)
                    
                    if result:
                        self.queue.put(("info", f"章节 {chapter_name} 下载完成"))
                    else:
                        self.queue.put(("error", f"章节 {chapter_name} 下载失败"))
                        if self.comic_dl_downloader.get_default_chapter_failure_policy(chapter_url) == "stop":
                            stopped_due_to_failure = True
                            self.queue.put(("info", "站点策略要求在章节失败后停止剩余下载"))
                            break
                
                if not self.is_cancelled and not stopped_due_to_failure:
                    self.queue.put(("info", "所有章节下载完成"))
                    self.queue.put(("complete", "Comic-DL 下载完成"))
            except Exception as e:
                self.queue.put(("error", f"下载失败: {str(e)}"))
            finally:
                close_method = getattr(parser, "close", None)
                if callable(close_method):
                    try:
                        close_method()
                    except Exception:
                        pass
                self.queue.put(("done", None))
        
        self.download_thread = threading.Thread(target=download_thread, daemon=True)
        self.download_thread.start()

    def cancel_download(self):
        self.is_cancelled = True
        self.queue.put(("info", "取消下载..."))

    def update_getcomics_history_controls(self):
        labels = [build_getcomics_history_label(item) for item in self.getcomics_recent_searches]
        self.getcomics_recent_search_map = dict(zip(labels, self.getcomics_recent_searches))

        self.is_updating_getcomics_history_menu = True
        try:
            if labels:
                self.getcomics_recent_menu.configure(values=labels, state="normal")
                self.getcomics_recent_var.set(labels[0])
                self.getcomics_recent_clear_button.configure(state="normal")
            else:
                self.getcomics_recent_menu.configure(values=["最近搜索"], state="disabled")
                self.getcomics_recent_var.set("最近搜索")
                self.getcomics_recent_clear_button.configure(state="disabled")
        finally:
            self.is_updating_getcomics_history_menu = False

    def apply_recent_getcomics_search(self, selection):
        if self.is_updating_getcomics_history_menu:
            return

        item = self.getcomics_recent_search_map.get(selection)
        if not item:
            return

        self.getcomics_query_entry.delete(0, tk.END)
        self.getcomics_query_entry.insert(0, item["query"])
        self.getcomics_date_entry.delete(0, tk.END)
        self.getcomics_date_entry.insert(0, item["date"])
        self.getcomics_results_var.set(item["results"])
        self.persist_gui_state_snapshot()

    def clear_getcomics_history(self):
        self.getcomics_recent_searches = []
        self.update_getcomics_history_controls()
        self.persist_gui_state_snapshot()

    def get_selected_getcomics_results(self, selected_indices=None):
        if selected_indices is None:
            selected_indices = self.getcomics_listbox.curselection()
        return collect_selected_getcomics_results(self.getcomics_results_data, selected_indices)

    def get_getcomics_favorite_urls(self):
        return {url for url, _ in self.getcomics_favorites}

    def get_getcomics_queue_urls(self):
        return {url for url, _ in self.getcomics_download_queue}

    def update_getcomics_view_toggle_button(self):
        if self.getcomics_view_mode == "favorites":
            self.getcomics_toggle_view_button.configure(text="返回搜索", state="normal")
        else:
            self.getcomics_toggle_view_button.configure(
                text="查看收藏",
                state="normal" if self.getcomics_favorites else "disabled",
            )
        if self.getcomics_view_mode == "queue":
            self.getcomics_toggle_queue_button.configure(text="返回搜索", state="normal")
        else:
            self.getcomics_toggle_queue_button.configure(
                text="查看队列",
                state="normal" if self.getcomics_download_queue else "disabled",
            )
        self.getcomics_export_favorites_button.configure(
            state="normal" if self.getcomics_favorites else "disabled"
        )
        self.getcomics_download_queue_button.configure(
            state="normal" if self.getcomics_download_queue else "disabled"
        )
        self.getcomics_clear_queue_button.configure(
            state="normal" if self.getcomics_download_queue else "disabled"
        )

    def set_getcomics_view_mode(self, mode, persist=True):
        normalized_mode = str(mode or "").strip().lower()
        if normalized_mode == "favorites" and self.getcomics_favorites:
            self.getcomics_view_mode = "favorites"
            visible_results = list(self.getcomics_favorites)
        elif normalized_mode == "queue" and self.getcomics_download_queue:
            self.getcomics_view_mode = "queue"
            visible_results = list(self.getcomics_download_queue)
        else:
            self.getcomics_view_mode = "search"
            visible_results = list(self.getcomics_search_results_data)

        self.populate_getcomics_results_list(visible_results)
        self.update_getcomics_view_toggle_button()
        self.update_getcomics_page_status(
            self.getcomics_search_current_page if self.getcomics_view_mode == "search" else 0
        )
        self.update_getcomics_pagination_controls(searching=False)

        if persist:
            self.persist_gui_state_snapshot()

    def toggle_getcomics_view_mode(self):
        if self.getcomics_view_mode == "favorites":
            self.set_getcomics_view_mode("search")
            return

        if not self.getcomics_favorites:
            messagebox.showinfo("提示", "收藏夹还是空的，先从搜索结果里添加一些吧")
            return

        self.set_getcomics_view_mode("favorites")

    def toggle_getcomics_queue_view(self):
        if self.getcomics_view_mode == "queue":
            self.set_getcomics_view_mode("search")
            return

        if not self.getcomics_download_queue:
            messagebox.showinfo("提示", "下载队列还是空的，先把结果加入队列吧")
            return

        self.set_getcomics_view_mode("queue")

    def update_getcomics_result_actions(self):
        has_results = bool(self.getcomics_results_data)
        selected_results = self.get_selected_getcomics_results() if has_results else []
        has_selection = bool(selected_results)
        favorite_urls = self.get_getcomics_favorite_urls()
        queue_urls = self.get_getcomics_queue_urls()
        has_selected_unfavorited = any(url not in favorite_urls for url, _ in selected_results)
        has_selected_favorited = any(url in favorite_urls for url, _ in selected_results)
        has_selected_unqueued = any(url not in queue_urls for url, _ in selected_results)
        has_selected_queued = any(url in queue_urls for url, _ in selected_results)

        self.getcomics_open_result_button.configure(state="normal" if has_selection else "disabled")
        self.getcomics_copy_links_button.configure(state="normal" if has_selection else "disabled")
        self.getcomics_select_all_button.configure(state="normal" if has_results else "disabled")
        self.getcomics_add_favorite_button.configure(
            state="normal" if has_selected_unfavorited else "disabled"
        )
        self.getcomics_remove_favorite_button.configure(
            state="normal" if has_selected_favorited else "disabled"
        )
        self.getcomics_add_queue_button.configure(
            state="normal" if has_selected_unqueued else "disabled"
        )
        self.getcomics_remove_queue_button.configure(
            state="normal" if has_selected_queued else "disabled"
        )
        self.update_getcomics_view_toggle_button()

    def select_all_getcomics_results(self):
        if not self.getcomics_results_data:
            return

        self.getcomics_listbox.select_set(0, tk.END)
        self.update_getcomics_result_actions()

    def add_selected_getcomics_to_favorites(self):
        selected_results = self.get_selected_getcomics_results()
        if not selected_results:
            messagebox.showerror("错误", "请先选择漫画结果")
            return

        before_urls = self.get_getcomics_favorite_urls()
        self.getcomics_favorites = upsert_getcomics_results(self.getcomics_favorites, selected_results)
        added_count = len(self.get_getcomics_favorite_urls() - before_urls)

        if added_count <= 0:
            self.log("所选 GetComics 结果已在收藏夹中")
            self.status_label.configure(text="所选结果已在收藏夹中")
            self.update_getcomics_result_actions()
            return

        if self.getcomics_view_mode == "favorites":
            self.set_getcomics_view_mode("favorites", persist=False)
        else:
            self.update_getcomics_result_actions()

        self.persist_gui_state_snapshot()
        self.log(f"已添加 {added_count} 个 GetComics 结果到收藏夹")
        self.status_label.configure(text=f"已添加 {added_count} 个收藏")

    def remove_selected_getcomics_from_favorites(self):
        selected_results = self.get_selected_getcomics_results()
        if not selected_results:
            messagebox.showerror("错误", "请先选择漫画结果")
            return

        before_count = len(self.getcomics_favorites)
        self.getcomics_favorites = remove_getcomics_results(self.getcomics_favorites, selected_results)
        removed_count = before_count - len(self.getcomics_favorites)

        if removed_count <= 0:
            self.log("所选 GetComics 结果不在收藏夹中")
            self.status_label.configure(text="所选结果不在收藏夹中")
            self.update_getcomics_result_actions()
            return

        if self.getcomics_view_mode == "favorites":
            self.set_getcomics_view_mode("favorites", persist=False)
        else:
            self.update_getcomics_result_actions()

        self.persist_gui_state_snapshot()
        self.log(f"已从收藏夹移除 {removed_count} 个 GetComics 结果")
        self.status_label.configure(text=f"已移除 {removed_count} 个收藏")

    def add_selected_getcomics_to_queue(self):
        selected_results = self.get_selected_getcomics_results()
        if not selected_results:
            messagebox.showerror("错误", "请先选择漫画结果")
            return

        before_urls = self.get_getcomics_queue_urls()
        self.getcomics_download_queue = upsert_getcomics_results(self.getcomics_download_queue, selected_results)
        added_count = len(self.get_getcomics_queue_urls() - before_urls)

        if added_count <= 0:
            self.log("所选 GetComics 结果已在下载队列中")
            self.status_label.configure(text="所选结果已在下载队列中")
            self.update_getcomics_result_actions()
            return

        if self.getcomics_view_mode == "queue":
            self.set_getcomics_view_mode("queue", persist=False)
        else:
            self.update_getcomics_result_actions()

        self.persist_gui_state_snapshot()
        self.log(f"已添加 {added_count} 个 GetComics 结果到下载队列")
        self.status_label.configure(text=f"已添加 {added_count} 个到下载队列")

    def remove_selected_getcomics_from_queue(self):
        selected_results = self.get_selected_getcomics_results()
        if not selected_results:
            messagebox.showerror("错误", "请先选择漫画结果")
            return

        before_count = len(self.getcomics_download_queue)
        self.getcomics_download_queue = remove_getcomics_results(self.getcomics_download_queue, selected_results)
        removed_count = before_count - len(self.getcomics_download_queue)

        if removed_count <= 0:
            self.log("所选 GetComics 结果不在下载队列中")
            self.status_label.configure(text="所选结果不在下载队列中")
            self.update_getcomics_result_actions()
            return

        if self.getcomics_view_mode == "queue":
            self.set_getcomics_view_mode("queue", persist=False)
        else:
            self.update_getcomics_result_actions()

        self.persist_gui_state_snapshot()
        self.log(f"已从下载队列移除 {removed_count} 个 GetComics 结果")
        self.status_label.configure(text=f"已移除 {removed_count} 个队列项")

    def clear_getcomics_queue(self):
        if not self.getcomics_download_queue:
            messagebox.showinfo("提示", "下载队列已经是空的")
            return

        if not messagebox.askyesno("确认", f"将清空 {len(self.getcomics_download_queue)} 个队列项，是否继续？"):
            return

        self.getcomics_download_queue = []
        if self.getcomics_view_mode == "queue":
            self.set_getcomics_view_mode("search", persist=False)
        else:
            self.update_getcomics_result_actions()

        self.persist_gui_state_snapshot()
        self.log("已清空 GetComics 下载队列")
        self.status_label.configure(text="已清空下载队列")

    def import_getcomics_favorites(self):
        file_path = filedialog.askopenfilename(
            title="导入 GetComics 收藏夹",
            filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")],
        )
        if not file_path:
            return

        imported_favorites = [
            (item["url"], item["title"])
            for item in load_getcomics_favorites_file(file_path)
        ]
        if not imported_favorites:
            messagebox.showerror("错误", "未从文件中读取到有效的收藏数据")
            return

        before_urls = self.get_getcomics_favorite_urls()
        self.getcomics_favorites = upsert_getcomics_results(self.getcomics_favorites, imported_favorites)
        added_count = len(self.get_getcomics_favorite_urls() - before_urls)

        if self.getcomics_view_mode == "favorites":
            self.set_getcomics_view_mode("favorites", persist=False)
        else:
            self.update_getcomics_result_actions()

        self.persist_gui_state_snapshot()
        self.log(f"已从文件导入 {len(imported_favorites)} 个收藏，新增 {added_count} 个")
        self.status_label.configure(text=f"已导入收藏，新增 {added_count} 个")

    def export_getcomics_favorites(self):
        if not self.getcomics_favorites:
            messagebox.showerror("错误", "收藏夹还是空的，暂时没有可导出的内容")
            return

        file_path = filedialog.asksaveasfilename(
            title="导出 GetComics 收藏夹",
            defaultextension=".json",
            initialfile="getcomics-favorites.json",
            filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")],
        )
        if not file_path:
            return

        if not save_getcomics_favorites_file(
            file_path,
            [
                {"url": url, "title": title}
                for url, title in self.getcomics_favorites
            ],
        ):
            messagebox.showerror("错误", "导出收藏夹失败")
            return

        self.log(f"已导出 {len(self.getcomics_favorites)} 个收藏到: {file_path}")
        self.status_label.configure(text=f"已导出 {len(self.getcomics_favorites)} 个收藏")

    def copy_selected_getcomics_links(self):
        selected_results = self.get_selected_getcomics_results()
        if not selected_results:
            messagebox.showerror("错误", "请先选择漫画结果")
            return

        clipboard_text = format_getcomics_results_for_clipboard(selected_results)
        if not clipboard_text:
            messagebox.showerror("错误", "没有可复制的链接")
            return

        self.clipboard_clear()
        self.clipboard_append(clipboard_text)
        self.update()
        self.log(f"已复制 {len(selected_results)} 个 GetComics 链接到剪贴板")
        self.status_label.configure(text=f"已复制 {len(selected_results)} 个链接")

    def open_selected_getcomics_results(self):
        selected_results = self.get_selected_getcomics_results()
        if not selected_results:
            messagebox.showerror("错误", "请先选择漫画结果")
            return

        if len(selected_results) > 5:
            if not messagebox.askyesno("确认", f"将打开 {len(selected_results)} 个详情页，是否继续？"):
                return

        opened_count = 0
        for url, _ in selected_results:
            try:
                webbrowser.open_new_tab(url)
                opened_count += 1
            except Exception as exc:
                self.log(f"打开详情页失败: {url} - {exc}")

        if opened_count:
            self.log(f"已打开 {opened_count} 个 GetComics 详情页")
            self.status_label.configure(text=f"已打开 {opened_count} 个详情页")

    def show_getcomics_results_menu(self, event):
        if not self.getcomics_results_data:
            return

        try:
            target_index = self.getcomics_listbox.nearest(event.y)
        except tk.TclError:
            return

        if target_index >= 0 and target_index not in self.getcomics_listbox.curselection():
            self.getcomics_listbox.selection_clear(0, tk.END)
            self.getcomics_listbox.selection_set(target_index)
            self.update_getcomics_result_actions()

        selected_results = self.get_selected_getcomics_results()
        favorite_urls = self.get_getcomics_favorite_urls()
        queue_urls = self.get_getcomics_queue_urls()

        self.getcomics_results_menu.entryconfigure(
            0,
            state="normal" if selected_results else "disabled",
        )
        self.getcomics_results_menu.entryconfigure(
            1,
            state="normal" if selected_results else "disabled",
        )
        self.getcomics_results_menu.entryconfigure(
            3,
            state="normal" if any(url not in favorite_urls for url, _ in selected_results) else "disabled",
        )
        self.getcomics_results_menu.entryconfigure(
            4,
            state="normal" if any(url in favorite_urls for url, _ in selected_results) else "disabled",
        )
        self.getcomics_results_menu.entryconfigure(
            5,
            label="返回搜索" if self.getcomics_view_mode == "favorites" else "查看收藏",
            state="normal" if self.getcomics_favorites or self.getcomics_view_mode == "favorites" else "disabled",
        )
        self.getcomics_results_menu.entryconfigure(
            7,
            state="normal" if any(url not in queue_urls for url, _ in selected_results) else "disabled",
        )
        self.getcomics_results_menu.entryconfigure(
            8,
            state="normal" if any(url in queue_urls for url, _ in selected_results) else "disabled",
        )
        self.getcomics_results_menu.entryconfigure(
            9,
            label="返回搜索" if self.getcomics_view_mode == "queue" else "查看队列",
            state="normal" if self.getcomics_download_queue or self.getcomics_view_mode == "queue" else "disabled",
        )
        self.getcomics_results_menu.entryconfigure(
            11,
            state="normal" if self.getcomics_results_data else "disabled",
        )

        try:
            self.getcomics_results_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.getcomics_results_menu.grab_release()

    def populate_getcomics_results_list(self, results_data):
        self.getcomics_results_data = list(results_data)
        self.getcomics_listbox.delete(0, tk.END)
        for _, comic_title in self.getcomics_results_data:
            self.getcomics_listbox.insert(tk.END, comic_title)
        self.getcomics_listbox.selection_clear(0, tk.END)
        self.update_getcomics_result_actions()

    def restore_cached_getcomics_results(self, getcomics_state):
        cached_results = [
            (item["url"], item["title"])
            for item in getcomics_state.get("last_results", [])
        ]
        self.getcomics_search_results_data = list(cached_results)
        self.getcomics_search_current_page = getcomics_state.get("last_page", 0) if cached_results else 0
        self.getcomics_results_restored_from_cache = bool(cached_results)
        self.set_getcomics_view_mode(getcomics_state.get("view_mode", "search"), persist=False)

    def restore_getcomics_state(self):
        getcomics_state = self.gui_state.get("getcomics", {})

        query = getcomics_state.get("query", "")
        if query:
            self.getcomics_query_entry.delete(0, tk.END)
            self.getcomics_query_entry.insert(0, query)

        date = getcomics_state.get("date", "")
        if date:
            self.getcomics_date_entry.delete(0, tk.END)
            self.getcomics_date_entry.insert(0, date)

        self.getcomics_results_var.set(getcomics_state.get("results", DEFAULT_GETCOMICS_RESULTS))

        save_dir = getcomics_state.get("save_dir", self.default_getcomics_save_dir)
        if save_dir:
            self.getcomics_save_entry.delete(0, tk.END)
            self.getcomics_save_entry.insert(0, save_dir)

        self.update_getcomics_history_controls()
        self.restore_cached_getcomics_results(getcomics_state)

    def restore_reader_state(self):
        reader_state = self.gui_state.get("reader", {})
        source_path = reader_state.get("source_path", self.default_getcomics_save_dir)
        active_path = str(reader_state.get("active_path") or "").strip()
        active_page = reader_state.get("active_page", 0)
        if active_path and active_page:
            self.reader_scroll_positions[(active_path, max(int(active_page) - 1, 0))] = (
                normalize_reader_scroll_fraction(reader_state.get("scroll_x")),
                normalize_reader_scroll_fraction(reader_state.get("scroll_y")),
            )
        self.refresh_reader_library(initial_path=source_path, select_first=False)

        target_path = reader_state.get("active_path") or reader_state.get("selected_path")
        if not target_path:
            return

        entry = self.select_reader_entry_by_path(target_path)
        if not entry:
            return

        active_path = reader_state.get("active_path", "")
        active_page = reader_state.get("active_page", 0)
        if active_path and entry["path"] == active_path and active_page > 0:
            self.open_reader_entry(
                entry,
                target_page=active_page,
                persist=False,
                announce=False,
            )

    def collect_gui_state(self):
        selected_reader_entry = self.get_selected_reader_entry()
        active_scroll_x, active_scroll_y = self.get_reader_canvas_scroll_position()
        return {
            "getcomics": {
                "query": self.getcomics_query_entry.get().strip(),
                "date": self.getcomics_date_entry.get().strip(),
                "results": self.getcomics_results_var.get().strip(),
                "save_dir": self.getcomics_save_entry.get().strip(),
                "recent_searches": list(self.getcomics_recent_searches),
                "view_mode": self.getcomics_view_mode,
                "favorites": normalize_cached_getcomics_results(
                    [
                        {"url": url, "title": title}
                        for url, title in self.getcomics_favorites
                    ]
                ),
                "queue_items": normalize_cached_getcomics_results(
                    [
                        {"url": url, "title": title}
                        for url, title in self.getcomics_download_queue
                    ]
                ),
                "last_page": self.getcomics_search_current_page if self.getcomics_search_results_data else 0,
                "last_results": normalize_cached_getcomics_results(
                    [
                        {"url": url, "title": title}
                        for url, title in self.getcomics_search_results_data
                    ]
                ),
            },
            "reader": {
                "source_path": self.reader_source_entry.get().strip(),
                "selected_path": selected_reader_entry["path"] if selected_reader_entry else "",
                "active_path": self.reader_current_entry["path"] if self.reader_current_entry else "",
                "active_page": self.reader_current_page_index + 1 if self.reader_current_page_index >= 0 else 0,
                "zoom_mode": self.reader_zoom_mode,
                "zoom_percent": self.reader_zoom_percent,
                "focus_mode": self.reader_focus_mode,
                "scroll_x": active_scroll_x,
                "scroll_y": active_scroll_y,
            },
            "settings": {
                "appearance_mode": self.appearance_mode,
                "reader_windows_fullscreen_mode": self.reader_windows_fullscreen_mode,
                "rename_api_key": self.rename_api_key,
                "rename_api_url": self.rename_api_url,
                "rename_api_model": self.rename_api_model,
                "rename_api_timeout": self.rename_api_timeout,
            },
        }

    def persist_gui_state_snapshot(self):
        self.gui_state = self.collect_gui_state()
        if not save_gui_state(
            self.gui_state_path,
            self.gui_state,
            default_save_dir=self.default_getcomics_save_dir,
        ):
            main_logger.warning("Failed to save GUI state to %s", self.gui_state_path)

    def remember_getcomics_search(self):
        self.getcomics_recent_searches = upsert_recent_getcomics_search(
            self.getcomics_recent_searches,
            {
                "query": self.getcomics_query_entry.get().strip(),
                "date": self.getcomics_date_entry.get().strip(),
                "results": self.getcomics_results_var.get().strip(),
            },
        )
        self.update_getcomics_history_controls()

    def search_getcomics(self):
        self.start_getcomics_search(mode="new")

    def load_previous_getcomics_page(self):
        self.start_getcomics_search(mode="previous")

    def load_next_getcomics_page(self):
        self.start_getcomics_search(mode="next")

    def jump_to_getcomics_page(self):
        raw_value = self.getcomics_jump_entry.get().strip()
        try:
            target_page = int(raw_value)
        except ValueError:
            messagebox.showerror("错误", "请输入有效的页码")
            return

        if target_page < 1:
            messagebox.showerror("错误", "页码必须大于或等于 1")
            return

        self.start_getcomics_search(mode="jump", target_page=target_page)

    def get_loaded_getcomics_page(self):
        downloader = getattr(self, "getcomics_downloader", None)
        if not downloader:
            return 0
        loaded_page_getter = getattr(downloader, "get_loaded_page", None)
        if callable(loaded_page_getter):
            return loaded_page_getter()
        try:
            return max(0, int(getattr(downloader, "page", 1)) - 1)
        except (TypeError, ValueError):
            return 0

    def update_getcomics_page_status(self, current_page=None):
        if self.getcomics_view_mode == "favorites":
            jump_entry_state = self.getcomics_jump_entry.cget("state")
            if jump_entry_state == "disabled":
                self.getcomics_jump_entry.configure(state="normal")
            self.getcomics_page_label.configure(text=f"收藏夹: {len(self.getcomics_favorites)} 项")
            self.getcomics_jump_entry.delete(0, tk.END)
            if jump_entry_state == "disabled":
                self.getcomics_jump_entry.configure(state="disabled")
            return
        if self.getcomics_view_mode == "queue":
            jump_entry_state = self.getcomics_jump_entry.cget("state")
            if jump_entry_state == "disabled":
                self.getcomics_jump_entry.configure(state="normal")
            self.getcomics_page_label.configure(text=f"下载队列: {len(self.getcomics_download_queue)} 项")
            self.getcomics_jump_entry.delete(0, tk.END)
            if jump_entry_state == "disabled":
                self.getcomics_jump_entry.configure(state="disabled")
            return

        if current_page is None:
            current_page = self.get_loaded_getcomics_page()

        try:
            self.getcomics_current_page = max(0, int(current_page))
        except (TypeError, ValueError):
            self.getcomics_current_page = 0
        self.getcomics_search_current_page = self.getcomics_current_page

        jump_entry_state = self.getcomics_jump_entry.cget("state")
        if jump_entry_state == "disabled":
            self.getcomics_jump_entry.configure(state="normal")

        if self.getcomics_current_page > 0:
            page_label = f"当前页: 第 {self.getcomics_current_page} 页"
            if self.getcomics_results_restored_from_cache and not self.getcomics_downloader:
                page_label = f"{page_label} (缓存)"
            self.getcomics_page_label.configure(text=page_label)
            self.getcomics_jump_entry.delete(0, tk.END)
            self.getcomics_jump_entry.insert(0, str(self.getcomics_current_page))
        else:
            self.getcomics_page_label.configure(text="当前页: 未搜索")
            self.getcomics_jump_entry.delete(0, tk.END)

        if jump_entry_state == "disabled":
            self.getcomics_jump_entry.configure(state="disabled")

    def update_getcomics_pagination_controls(self, searching=False):
        self.getcomics_search_button.configure(state="disabled" if searching else "normal")
        has_pagination_context = (
            self.getcomics_view_mode == "search"
            and bool(self.getcomics_downloader)
            and self.getcomics_search_current_page > 0
        )
        self.getcomics_prev_button.configure(
            state="disabled" if searching or self.getcomics_view_mode != "search" or self.getcomics_search_current_page <= 1 else "normal"
        )
        self.getcomics_jump_button.configure(
            state="disabled" if searching or not has_pagination_context else "normal"
        )
        self.getcomics_jump_entry.configure(
            state="normal" if has_pagination_context and not searching else "disabled"
        )
        self.getcomics_next_button.configure(
            state="disabled" if searching or not has_pagination_context else "normal"
        )

    def start_getcomics_search(self, mode="new", target_page=None):
        query = self.getcomics_query_entry.get().strip()
        load_next = mode == "next"
        load_previous = mode == "previous"
        jump_to_page = mode == "jump"
        is_new_search = mode == "new"

        if not is_new_search and self.getcomics_view_mode != "search":
            messagebox.showerror("错误", "当前正在查看收藏夹，请先返回搜索结果")
            return

        if not is_new_search and not self.getcomics_downloader:
            messagebox.showerror("错误", "请先执行一次搜索")
            return

        if not is_new_search and self.getcomics_current_page <= 0:
            messagebox.showerror("错误", "当前没有可翻页的搜索结果")
            return

        if load_previous and self.getcomics_current_page <= 1:
            messagebox.showinfo("提示", "已经是第一页")
            return

        if jump_to_page:
            if target_page is None:
                messagebox.showerror("错误", "缺少目标页码")
                return
            if target_page == self.getcomics_current_page:
                self.log(f"已经位于 GetComics 第 {target_page} 页")
                return

        if is_new_search and not query:
            messagebox.showerror("错误", "请输入搜索内容")
            return

        if load_next:
            query = self.getcomics_downloader.query
            target_page = max(1, int(getattr(self.getcomics_downloader, "page", 1)))
            self.log(f"正在加载 GetComics 第 {target_page} 页: {query}")
        elif load_previous:
            query = self.getcomics_downloader.query
            target_page = max(1, self.getcomics_current_page - 1)
            self.log(f"正在返回 GetComics 第 {target_page} 页: {query}")
        elif jump_to_page:
            query = self.getcomics_downloader.query
            target_page = max(1, int(target_page))
            self.log(f"正在跳转到 GetComics 第 {target_page} 页: {query}")
        else:
            self.getcomics_results_restored_from_cache = False
            self.getcomics_search_results_data = []
            self.getcomics_search_current_page = 0
            self.set_getcomics_view_mode("search", persist=False)

        self.show_progress()
        date = self.getcomics_date_entry.get().strip()
        results = int(self.getcomics_results_var.get())

        if is_new_search:
            self.log(f"正在搜索 GetComics: {query}")
        self.update_getcomics_pagination_controls(searching=True)
        self.reset_progress()
        self.progress_bar.configure(mode="indeterminate")
        self.progress_bar.start()

        def search_thread():
            target_page = 1
            try:
                if not is_new_search:
                    if load_next:
                        target_page = max(1, int(getattr(self.getcomics_downloader, "page", 1)))
                    elif load_previous:
                        target_page = max(1, self.getcomics_current_page - 1)
                    elif jump_to_page:
                        target_page = max(1, int(target_page))
                    self.getcomics_downloader.page = target_page
                    self.getcomics_downloader.page_links.clear()
                    self.getcomics_downloader.comic_links.clear()
                else:
                    self.getcomics_downloader = GetComics(query, results, True, date=date or None)
                    target_page = 1

                async def search_async():
                    await self.getcomics_downloader.find_pages()
                    await self.getcomics_downloader.get_download_links()
                asyncio.run(search_async())

                if not self.getcomics_downloader.comic_links:
                    if not is_new_search:
                        self.queue.put(("info", f"第 {target_page} 页没有可下载结果，请继续尝试下一页或调整筛选条件"))
                    else:
                        self.queue.put(("error", "未找到搜索结果"))
                    return

                self.queue.put(
                    (
                        "getcomics_success",
                        {
                            "comic_links": dict(self.getcomics_downloader.comic_links),
                            "page": target_page,
                        },
                    )
                )
            except Exception as e:
                self.queue.put(("error", f"搜索失败: {str(e)}"))
            finally:
                self.queue.put(("search_getcomics_done", None))

        self.getcomics_thread = threading.Thread(target=search_thread, daemon=True)
        self.getcomics_thread.start()

    def start_getcomics_download_for_results(self, selected_results, task_label="GetComics 下载完成"):
        if self.getcomics_thread and self.getcomics_thread.is_alive():
            messagebox.showinfo("提示", "请等待当前 GetComics 任务完成后再继续")
            return

        selected_comics = {
            url: title
            for url, title in selected_results
        }
        if not selected_comics:
            messagebox.showerror("错误", "请选择有效的漫画结果")
            return
        
        save_dir_input = self.getcomics_save_entry.get().strip()
        if not save_dir_input:
            messagebox.showerror("错误", "请选择保存目录")
            return
        
        save_dir = Path(save_dir_input).expanduser()
        save_dir.mkdir(parents=True, exist_ok=True)
        
        self.is_getcomics_cancelled = False
        self.getcomics_download_button.configure(state="disabled")
        self.getcomics_download_queue_button.configure(state="disabled")
        self.getcomics_cancel_button.configure(state="normal")
        self.reset_progress()
        
        def download_thread():
            try:
                def progress_callback(msg):
                    if isinstance(msg, tuple) and msg[0] == "progress":
                        enqueue_progress = getattr(self, "enqueue_progress_update", None)
                        if callable(enqueue_progress):
                            enqueue_progress(msg[1])
                        else:
                            self.queue.put(("progress", msg[1]))
                    else:
                        self.queue.put(("info", msg))
                
                download_comics(
                    selected_comics,
                    save_dir,
                    True,
                    prompt=False,
                    use_aria2c=True,
                    progress_callback=progress_callback,
                    rename_downloaded_files=False,
                    cancel_callback=lambda: self.is_getcomics_cancelled,
                )
                
                if not self.is_getcomics_cancelled:
                    enqueue_progress = getattr(self, "enqueue_progress_update", None)
                    if callable(enqueue_progress):
                        enqueue_progress(100, force=True)
                    else:
                        self.queue.put(("progress", 100))
                    self.queue.put(("info", "所有漫画下载完成"))
                    self.queue.put(("complete", task_label))
            except Exception as e:
                self.queue.put(("error", f"下载失败: {str(e)}"))
            finally:
                self.queue.put(("getcomics_done", None))
        
        self.getcomics_thread = threading.Thread(target=download_thread, daemon=True)
        self.getcomics_thread.start()

    def start_getcomics_download(self):
        selected_results = self.get_selected_getcomics_results()
        if not selected_results:
            messagebox.showerror("错误", "请选择要下载的漫画")
            return

        if not self.getcomics_downloader and not self.getcomics_results_data:
            messagebox.showerror("错误", "请先搜索漫画")
            return

        self.start_getcomics_download_for_results(selected_results, task_label="GetComics 下载完成")

    def start_getcomics_queue_download(self):
        if not self.getcomics_download_queue:
            messagebox.showerror("错误", "下载队列还是空的")
            return

        self.start_getcomics_download_for_results(
            list(self.getcomics_download_queue),
            task_label="GetComics 队列下载完成",
        )

    def cancel_getcomics_download(self):
        self.is_getcomics_cancelled = True
        self.queue.put(("info", "取消下载..."))

    def browse_getcomics_save_dir(self):
        directory = filedialog.askdirectory(title="选择保存目录")
        if directory:
            self.getcomics_save_entry.delete(0, tk.END)
            self.getcomics_save_entry.insert(0, directory)
            self.persist_gui_state_snapshot()

    def enqueue_progress_update(self, progress_value, force=False):
        try:
            progress = float(progress_value)
        except (TypeError, ValueError):
            return

        progress = max(0.0, min(100.0, progress))
        with self.queue_throttle_lock:
            now = time.monotonic()
            last_time = self._queued_progress_state["timestamp"]
            last_value = self._queued_progress_state["value"]
            if (
                not force
                and last_value is not None
                and abs(progress - last_value) < QUEUE_PROGRESS_MIN_DELTA
                and (now - last_time) < QUEUE_PROGRESS_MIN_INTERVAL
            ):
                return
            self._queued_progress_state = {"timestamp": now, "value": progress}

        self.queue.put(("progress", progress))

    def append_log_lines(self, lines):
        entries = [str(line) for line in lines if str(line).strip()]
        if not entries:
            return

        self.log_textbox.configure(state="normal")
        self.log_textbox.insert("end", "\n".join(entries) + "\n")
        self.log_textbox.see("end")
        self.log_textbox.configure(state="disabled")

    def set_progress_value(self, progress_value):
        try:
            progress = max(0.0, min(100.0, float(progress_value)))
        except (TypeError, ValueError):
            return

        self.progress_bar.set(progress / 100)
        self.percent_label.configure(text=f"{int(round(progress))}%")

    def set_latest_error_text(self, message=None):
        text = str(message or "").strip() or "暂无错误"
        self.logs_error_value_label.configure(text=text)

    def check_queue(self):
        pending_logs = []
        pending_status = None
        pending_progress = None
        queue_has_more = False

        def flush_pending():
            nonlocal pending_logs, pending_status, pending_progress

            if pending_logs:
                self.append_log_lines(pending_logs)
                pending_logs = []
            if pending_status is not None:
                self.status_label.configure(text=pending_status)
                pending_status = None
            if pending_progress is not None:
                self.set_progress_value(pending_progress)
                pending_progress = None

        try:
            processed = 0
            while processed < QUEUE_BATCH_LIMIT:
                try:
                    msg_type, msg_data = self.queue.get_nowait()
                except queue.Empty:
                    break

                processed += 1

                try:
                    if msg_type == "success":
                        comic_title, chapter_links = msg_data
                        self.comic_title = comic_title
                        self.chapter_data = chapter_links
                        self.chapter_listbox.delete(0, tk.END)
                        for chapter_name, _ in chapter_links:
                            self.chapter_listbox.insert(tk.END, chapter_name)
                        pending_logs.append(f"成功获取漫画信息: {comic_title}")
                        self.fetch_button.configure(state="normal")

                    elif msg_type == "getcomics_success":
                        comic_links = msg_data.get("comic_links", {}) if isinstance(msg_data, dict) else msg_data
                        current_page = msg_data.get("page", 0) if isinstance(msg_data, dict) else 0
                        self.getcomics_results_restored_from_cache = False
                        self.getcomics_search_results_data = list(comic_links.items())
                        self.getcomics_search_current_page = max(0, int(current_page or 0))
                        self.set_getcomics_view_mode("search", persist=False)
                        self.remember_getcomics_search()
                        self.persist_gui_state_snapshot()
                        pending_logs.append(
                            f"成功搜索到第 {self.getcomics_search_current_page} 页，共 {len(comic_links)} 个漫画"
                        )
                        self.update_getcomics_pagination_controls(searching=False)

                    elif msg_type == "error":
                        flush_pending()
                        error_text = str(msg_data)
                        self.append_log_lines([f"错误: {error_text}"])
                        self.set_latest_error_text(error_text)
                        messagebox.showerror("错误", error_text)
                        self.fetch_button.configure(state="normal")
                        self.getcomics_search_button.configure(state="normal")

                    elif msg_type == "log":
                        pending_logs.append(str(msg_data))

                    elif msg_type == "progress":
                        pending_progress = msg_data

                    elif msg_type == "info":
                        info_text = str(msg_data)
                        pending_logs.append(info_text)
                        pending_status = info_text

                    elif msg_type == "fetch_done":
                        flush_pending()
                        self.progress_bar.stop()
                        self.progress_bar.configure(mode="determinate")
                        self.fetch_button.configure(state="normal")
                        self.reset_progress()

                    elif msg_type == "search_getcomics_done":
                        flush_pending()
                        self.progress_bar.stop()
                        self.progress_bar.configure(mode="determinate")
                        self.update_getcomics_pagination_controls(searching=False)
                        self.reset_progress()

                    elif msg_type == "done":
                        flush_pending()
                        self.download_thread = None
                        self.download_button.configure(state="normal")
                        self.cancel_button.configure(state="disabled")
                        self.set_progress_value(100)

                    elif msg_type == "getcomics_done":
                        flush_pending()
                        self.getcomics_thread = None
                        self.getcomics_download_button.configure(state="normal")
                        self.update_getcomics_view_toggle_button()
                        self.getcomics_cancel_button.configure(state="disabled")
                        self.set_progress_value(100)

                    elif msg_type == "convert_done":
                        flush_pending()
                        self.convert_button.configure(state="normal")
                        self.set_progress_value(100)

                    elif msg_type == "complete":
                        flush_pending()
                        completion_text = str(msg_data)
                        self.append_log_lines([f"任务完成: {completion_text}"])
                        messagebox.showinfo("完成", completion_text)
                except Exception as e:
                    print(f"Error processing queue message: {e}")
                    continue

            flush_pending()
            queue_has_more = not self.queue.empty()
        finally:
            try:
                if self.winfo_exists():
                    interval = QUEUE_BUSY_POLL_MS if queue_has_more else QUEUE_EMPTY_POLL_MS
                    self.queue_check_after_id = self.after(interval, self.check_queue)
            except tk.TclError:
                self.queue_check_after_id = None

    def log(self, message):
        self.append_log_lines([message])

    def clear_logs(self):
        self.log_textbox.configure(state="normal")
        self.log_textbox.delete("1.0", "end")
        self.log_textbox.configure(state="disabled")

    def show_log_menu(self, event):
        self.log_menu.post(event.x_root, event.y_root)

    def copy_logs_to_clipboard(self):
        log_text = self.log_textbox.get("1.0", "end").strip()
        if not log_text:
            return
        self.clipboard_clear()
        self.clipboard_append(log_text)

    def open_log_file(self):
        log_path = Path(log_filename).resolve()
        try:
            os.startfile(str(log_path))
        except AttributeError:
            webbrowser.open(log_path.as_uri())
        except OSError as exc:
            messagebox.showerror("错误", f"无法打开日志文件: {exc}")

    def open_logs_folder(self):
        self.open_folder(str(Path(log_filename).resolve().parent))

    def reset_progress(self):
        with self.queue_throttle_lock:
            self._queued_progress_state = {"timestamp": 0.0, "value": None}
        self.set_progress_value(0)
        self.status_label.configure(text="准备就绪")

    def select_all(self):
        self.chapter_listbox.select_set(0, tk.END)

    def deselect_all(self):
        self.chapter_listbox.select_clear(0, tk.END)

    def browse_convert_input(self):
        input_path = filedialog.askopenfilename(
            title="选择漫画源文件",
            filetypes=[
                ("Comic Sources", "*.cbz *.zip *.cbr *.rar *.cb7 *.7z *.pdf"),
                ("CBZ Files", "*.cbz"),
                ("ZIP Files", "*.zip"),
                ("CBR Files", "*.cbr"),
                ("RAR Files", "*.rar"),
                ("CB7 Files", "*.cb7"),
                ("7z Files", "*.7z"),
                ("PDF Files", "*.pdf"),
                ("All Files", "*.*"),
            ],
        )
        if not input_path:
            input_path = filedialog.askdirectory(title="选择文件夹")
        if input_path:
            self.convert_input_entry.delete(0, tk.END)
            self.convert_input_entry.insert(0, input_path)

    def browse_convert_output(self):
        output_path = filedialog.asksaveasfilename(title="保存 CBZ 文件", defaultextension=".cbz")
        if output_path:
            self.convert_output_entry.delete(0, tk.END)
            self.convert_output_entry.insert(0, output_path)

    def start_convert(self):
        input_path = self.convert_input_entry.get().strip()
        output_path = self.convert_output_entry.get().strip()
        if not input_path or not output_path:
            messagebox.showerror("错误", "请选择输入和输出路径")
            return
        if self.show_comic_source_support_message(input_path, "转换"):
            return
        
        self.convert_button.configure(state="disabled")
        self.reset_progress()
        
        def convert_thread():
            try:
                def progress_callback(msg):
                    if isinstance(msg, tuple) and msg[0] == "progress":
                        self.enqueue_progress_update(msg[1])
                    elif "添加图片" in msg:
                        match = re.search(r"(\d+)/(\d+)", msg)
                        if match:
                            curr, total = map(int, match.groups())
                            self.enqueue_progress_update((curr / total) * 100)
                        self.queue.put(("info", msg))
                    else:
                        self.queue.put(("info", msg))
                
                result = self.comic_dl_downloader.convert_to_cbz(input_path, output_path, progress_callback)
                if result:
                    self.queue.put(("info", "转换完成"))
                    self.queue.put(("complete", "CBZ 转换完成"))
                else:
                    self.queue.put(("error", "转换失败"))
            except Exception as e:
                self.queue.put(("error", f"转换失败: {str(e)}"))
            finally:
                self.queue.put(("convert_done", None))
        
        threading.Thread(target=convert_thread, daemon=True).start()

    def open_folder(self, folder_path):
        """打开指定的文件夹"""
        if not folder_path or not os.path.exists(folder_path):
            messagebox.showwarning("警告", f"文件夹不存在: {folder_path}")
            return
        
        try:
            os.startfile(folder_path)
        except Exception as e:
            self.log(f"无法打开文件夹: {e}")
            # 跨平台备选方案
            import platform
            import subprocess
            if platform.system() == "Darwin":  # macOS
                subprocess.Popen(["open", folder_path])
            elif platform.system() == "Linux":  # Linux
                subprocess.Popen(["xdg-open", folder_path])
            else:
                messagebox.showerror("错误", f"无法打开文件夹: {e}")

    def open_current_download_folder(self):
        """根据当前所在的页面打开对应的下载目录"""
        path = ""
        if hasattr(self, "current_frame_name"):
            if self.current_frame_name == "comic_dl":
                path = self.save_entry.get()
            elif self.current_frame_name == "getcomics":
                path = self.getcomics_save_entry.get()
            elif self.current_frame_name == "convert":
                path = os.path.dirname(self.convert_output_entry.get())
            elif self.current_frame_name == "rename":
                path = self.rename_folder_path.get()
            elif self.current_frame_name == "reader":
                if self.reader_current_entry:
                    source_path = Path(self.reader_current_entry["path"])
                    path = str(source_path if source_path.is_dir() else source_path.parent)
                else:
                    path = self.reader_source_entry.get().strip()
        
        # 如果当前页面没有路径或路径不存在，尝试备选路径
        if not path or not os.path.exists(path):
            # 优先打开 Comic-DL 的保存路径，如果为空则尝试 GetComics 的
            path = self.save_entry.get()
            if not path or not os.path.exists(path):
                path = self.getcomics_save_entry.get()
            if (not path or not os.path.exists(path)) and hasattr(self, "reader_source_entry"):
                reader_path = self.reader_source_entry.get().strip()
                if reader_path and os.path.exists(reader_path):
                    path = reader_path
            
        if path and os.path.exists(path):
            self.open_folder(path)
        else:
            # 如果都不可用，尝试打开默认文档目录
            default_path = os.path.join(os.path.expanduser("~"), "Documents", "Comics")
            if os.path.exists(default_path):
                self.open_folder(default_path)
            else:
                messagebox.showinfo("提示", "未找到有效的下载目录")

    def on_closing(self):
        if self.queue_check_after_id:
            try:
                self.after_cancel(self.queue_check_after_id)
            except tk.TclError:
                pass
            self.queue_check_after_id = None

        self.cancel_reader_preview_refresh()
        self.cancel_reader_fullscreen_transition()

        if getattr(self, "reader_fullscreen_mode", False):
            try:
                self.attributes("-fullscreen", False)
            except tk.TclError:
                pass

        if (self.download_thread and self.download_thread.is_alive()) or (self.getcomics_thread and self.getcomics_thread.is_alive()):
            if messagebox.askokcancel("确认", "正在任务中，确定关闭吗？"):
                self.persist_gui_state_snapshot()
                self.comic_dl_downloader.close_parsers()
                self.destroy()
        else:
            self.persist_gui_state_snapshot()
            self.comic_dl_downloader.close_parsers()
            self.destroy()

    def rename_browse_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.rename_folder_path.set(folder)
            self.rename_refresh_files()

    def rename_refresh_files(self):
        folder = self.rename_folder_path.get()
        if not folder or not os.path.exists(folder):
            return
        for item in self.rename_tree.get_children():
            self.rename_tree.delete(item)
        self.rename_files = []
        for file in os.listdir(folder):
            if os.path.isfile(os.path.join(folder, file)):
                self.rename_files.append((file, file))
                self.rename_tree.insert("", tk.END, values=(file, file))

    def rename_analyze_with_ai(self):
        if not self.rename_files:
            return
        try:
            self.get_rename_api_request_settings()
        except ValueError as exc:
            messagebox.showerror("错误", str(exc))
            return
        custom_prompt = self.rename_prompt_text.get("1.0", "end").strip()
        folder_name = os.path.basename(self.rename_folder_path.get()) if self.rename_include_folder.get() else ""
        
        self.log("开始 AI 分析文件名...")
        self.reset_progress()
        total = len(self.rename_files)
        
        def analyze_thread():
            for i, (original, _) in enumerate(self.rename_files):
                try:
                    self.queue.put(("progress", (i / total) * 100))
                    self.queue.put(("info", f"正在分析: {original}"))
                    new_name = self.rename_analyze_with_deepseek(original, custom_prompt, folder_name)
                    self.rename_files[i] = (original, new_name)
                    self.after(0, lambda idx=i, o=original, n=new_name: self.rename_tree.item(self.rename_tree.get_children()[idx], values=(o, n)))
                except Exception as e:
                    self.log(f"分析失败: {original} - {e}")
            self.queue.put(("progress", 100))
            self.queue.put(("info", "AI 分析完成"))
        threading.Thread(target=analyze_thread, daemon=True).start()

    def rename_analyze_with_deepseek(self, filename, custom_prompt, folder_name):
        api_settings = self.get_rename_api_request_settings()
        extension = os.path.splitext(filename)[1]
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_settings['api_key']}",
        }
        user_prompt = f"分析并标准化文件名：{filename}"
        if folder_name:
            user_prompt += f"\n文件夹名：{folder_name}"
        payload = {
            "model": api_settings["api_model"],
            "messages": [{"role": "system", "content": custom_prompt}, {"role": "user", "content": user_prompt}],
            "temperature": 0.1
        }
        response = requests.post(
            api_settings["api_url"],
            headers=headers,
            json=payload,
            timeout=api_settings["api_timeout"],
        )
        response.raise_for_status()
        result = response.json()
        choices = result.get("choices") or []
        if not choices:
            error_message = result.get("error", {}).get("message") or "DeepSeek returned no choices."
            raise ValueError(error_message)
        new_name = choices[0]["message"]["content"].strip().strip('"')
        if not new_name:
            raise ValueError("DeepSeek returned an empty filename.")
        if not new_name.endswith(extension): new_name += extension
        return new_name

    def rename_execute_rename(self):
        folder = self.rename_folder_path.get()
        if not folder or not self.rename_files: return
        self.reset_progress()
        total = len(self.rename_files)
        def exec_thread():
            count = 0
            for i, (orig, new) in enumerate(self.rename_files):
                if orig != new:
                    try:
                        os.rename(os.path.join(folder, orig), os.path.join(folder, new))
                        count += 1
                        self.queue.put(("progress", (i / total) * 100))
                    except: pass
            self.queue.put(("progress", 100))
            self.queue.put(("complete", f"重命名完成: {count} 个文件"))
            self.after(0, self.rename_refresh_files)
        threading.Thread(target=exec_thread, daemon=True).start()

    def rename_log(self, message):
        self.log(f"[重命名] {message}")

if __name__ == "__main__":
    app = ComicDownloaderGUI()
    app.mainloop()
