import os
import re
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox
import threading
import queue
import requests
import asyncio
import webbrowser
try:
    import customtkinter as ctk
except ModuleNotFoundError as exc:
    raise ModuleNotFoundError("Missing GUI dependency 'customtkinter'. Run install.bat first.") from exc

try:
    from PIL import Image
except ModuleNotFoundError as exc:
    raise ModuleNotFoundError("Missing GUI dependency 'Pillow'. Run install.bat first.") from exc

# 导入下载器模块
from .comic_downloader import ComicDownloader
from .comic_reader import (
    discover_comics,
    format_bytes,
    list_comic_pages,
    load_comic_page_image,
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
    DEFAULT_GETCOMICS_RESULTS,
    build_getcomics_history_label,
    load_gui_state,
    load_getcomics_favorites_file,
    normalize_cached_getcomics_results,
    save_getcomics_favorites_file,
    save_gui_state,
    upsert_recent_getcomics_search,
)
from .logger import main_logger, setup_gui_logging

# DeepSeek API配置
DEFAULT_DEEPSEEK_API_KEY = "sk-40f91a96560c4b91a78b88091b3a07ea"
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", DEFAULT_DEEPSEEK_API_KEY).strip()
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_TIMEOUT = 20

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

class ComicDownloaderGUI(ctk.CTk):
    def __init__(self):
        super().__init__()

        # 窗口基本设置
        self.title("漫画下载器整合版 - Modern UI")
        self.geometry("1100x700")
        
        # 下载器实例
        self.comic_dl_downloader = ComicDownloader()
        self.getcomics_downloader = None
        self.getcomics_results_data = []
        self.getcomics_current_page = 0
        self.default_getcomics_save_dir = os.path.join(os.path.expanduser("~"), "Documents", "Comics")
        self.gui_state_path = Path(__file__).resolve().parent.parent / ".gui_state.json"
        self.gui_state = load_gui_state(self.gui_state_path, default_save_dir=self.default_getcomics_save_dir)
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
        self.reader_preview_image = None
        self.queue_check_after_id = None
        
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
        self.sidebar_frame.grid_rowconfigure(7, weight=1)
        
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
        
        self.appearance_mode_label = ctk.CTkLabel(self.sidebar_frame, text="外观模式:", anchor="w")
        self.appearance_mode_label.grid(row=8, column=0, padx=20, pady=(10, 0))
        self.appearance_mode_optionemenu = ctk.CTkOptionMenu(self.sidebar_frame, values=["Light", "Dark", "System"],
                                                                       command=self.change_appearance_mode_event)
        self.appearance_mode_optionemenu.grid(row=9, column=0, padx=20, pady=(10, 20))
        self.appearance_mode_optionemenu.set("Dark")

        # ========== 内容区域 (Content Frames) ==========
        # 1. 主菜单 (Home)
        self.home_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.home_frame.grid_columnconfigure((0, 1), weight=1)
        
        self.home_title = ctk.CTkLabel(self.home_frame, text="漫画下载器整合版", font=ctk.CTkFont(size=28, weight="bold"))
        self.home_title.grid(row=0, column=0, columnspan=2, padx=20, pady=(40, 20))
        
        self.home_subtitle = ctk.CTkLabel(self.home_frame, text="选择左侧菜单开始使用您的下载任务", font=ctk.CTkFont(size=16))
        self.home_subtitle.grid(row=1, column=0, columnspan=2, padx=20, pady=(0, 40))

        # 功能卡片
        self.card_1 = self.create_feature_card(self.home_frame, "Comic-DL 下载", "支持多种在线漫画网站的爬取和下载，\n包括章节选择和图片自动打包。", 2, 0)
        self.card_2 = self.create_feature_card(self.home_frame, "GetComics 下载", "强大的搜索功能，支持在 GetComics \n上查找并下载美漫，集成 aria2c 加速。", 2, 1)
        self.card_3 = self.create_feature_card(self.home_frame, "转换为 CBZ", "将本地图片文件夹或 ZIP 压缩包\n一键转换为标准的 CBZ 漫画格式。", 3, 0)
        self.card_4 = self.create_feature_card(self.home_frame, "AI 漫画重命名", "利用 DeepSeek AI 智能分析文件名，\n将混乱的文件重构为标准的标题和期号。", 3, 1)
        
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
        self.restore_getcomics_state()

        # ========== 底部进度和日志 (Bottom Panel) ==========
        self.bottom_frame = ctk.CTkFrame(self, height=200, corner_radius=10)
        # 初始不显示 grid
        self.bottom_frame.grid_columnconfigure(0, weight=1)
        self.bottom_frame.grid_rowconfigure(2, weight=1)
        
        self.status_label = ctk.CTkLabel(self.bottom_frame, text="准备就绪", anchor="w")
        self.status_label.grid(row=0, column=0, padx=20, pady=(10, 0), sticky="ew")
        
        self.open_folder_button = ctk.CTkButton(self.bottom_frame, text="打开当前目录", command=self.open_current_download_folder, width=120, height=24)
        self.open_folder_button.grid(row=0, column=1, padx=20, pady=(10, 0))
        
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ctk.CTkProgressBar(self.bottom_frame)
        self.progress_bar.grid(row=1, column=0, padx=20, pady=10, sticky="ew")
        self.progress_bar.set(0)
        
        self.percent_label = ctk.CTkLabel(self.bottom_frame, text="0%")
        self.percent_label.grid(row=1, column=1, padx=(0, 20), pady=10)
        
        self.log_textbox = ctk.CTkTextbox(self.bottom_frame, height=120)
        self.log_textbox.grid(row=2, column=0, columnspan=2, padx=20, pady=(0, 10), sticky="nsew")
        self.log_textbox.configure(state="disabled")
        
        # 添加右键菜单 (Tkinter 原生菜单)
        self.log_menu = tk.Menu(self.log_textbox, tearoff=0)
        self.log_menu.add_command(label="清空日志", command=self.clear_logs)
        self.log_textbox.bind("<Button-3>", self.show_log_menu)

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
        self.restore_reader_state()
        
        # 定期检查队列
        self.check_queue()
        
        # 初始日志
        main_logger.info("现代版 GUI 已经启动，基于 CustomTkinter")
        self.log("提示: 下载过程中可以在下方实时看到进度和日志")
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
        
        ctk.CTkLabel(group, text="输入路径 (文件夹/ZIP):").grid(row=0, column=0, padx=10, pady=10)
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
        self.reader_frame.grid_rowconfigure(0, weight=1)

        left_panel = ctk.CTkFrame(self.reader_frame, width=320)
        left_panel.grid(row=0, column=0, padx=(20, 10), pady=20, sticky="nsew")
        left_panel.grid_columnconfigure(0, weight=1)
        left_panel.grid_rowconfigure(4, weight=1)

        ctk.CTkLabel(
            left_panel,
            text="本地漫画文件",
            font=ctk.CTkFont(size=20, weight="bold"),
        ).grid(row=0, column=0, padx=15, pady=(15, 10), sticky="w")

        self.reader_source_entry = ctk.CTkEntry(
            left_panel,
            placeholder_text="选择漫画目录或单个 CBZ/ZIP 文件",
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
        right_panel.grid(row=0, column=1, padx=(10, 20), pady=20, sticky="nsew")
        right_panel.grid_columnconfigure(0, weight=1)
        right_panel.grid_rowconfigure(2, weight=1)

        self.reader_title_label = ctk.CTkLabel(
            right_panel,
            text="漫画阅读器",
            font=ctk.CTkFont(size=20, weight="bold"),
            anchor="w",
        )
        self.reader_title_label.grid(row=0, column=0, padx=20, pady=(15, 5), sticky="ew")

        self.reader_info_textbox = ctk.CTkTextbox(right_panel, height=110)
        self.reader_info_textbox.grid(row=1, column=0, padx=20, pady=(0, 10), sticky="ew")
        self.reader_info_textbox.configure(state="disabled")

        preview_frame = ctk.CTkFrame(right_panel)
        preview_frame.grid(row=2, column=0, padx=20, pady=(0, 10), sticky="nsew")
        preview_frame.grid_columnconfigure(0, weight=1)
        preview_frame.grid_rowconfigure(0, weight=1)

        self.reader_preview_label = ctk.CTkLabel(
            preview_frame,
            text="从左侧选择漫画后即可在这里翻页阅读",
            anchor="center",
            justify="center",
        )
        self.reader_preview_label.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        self.reader_preview_label.bind("<Configure>", lambda event: self.refresh_reader_preview())

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

        self.set_reader_info_text("漫画列表会显示目录下的图片文件夹和 CBZ/ZIP 文件。")
        self.refresh_reader_library(initial_path=self.default_getcomics_save_dir, select_first=False)

    def show_progress(self):
        """显示进度和日志面板"""
        self.bottom_frame.grid(row=1, column=1, padx=20, pady=10, sticky="nsew")

    def hide_progress(self):
        """隐藏进度和日志面板"""
        self.bottom_frame.grid_forget()

    def select_frame_by_name(self, name):
        self.current_frame_name = name
        # 隐藏所有 frame
        self.home_frame.grid_forget()
        self.comic_dl_frame.grid_forget()
        self.getcomics_frame.grid_forget()
        self.convert_frame.grid_forget()
        self.rename_frame.grid_forget()
        self.reader_frame.grid_forget()

        # 显示选中的 frame
        if name == "home":
            self.home_frame.grid(row=0, column=1, sticky="nsew")
            # 如果在首页且没有任务运行，隐藏底栏
            if not self.is_any_task_running():
                self.hide_progress()
        elif name == "comic_dl":
            self.comic_dl_frame.grid(row=0, column=1, sticky="nsew")
            self.show_progress()
        elif name == "getcomics":
            self.getcomics_frame.grid(row=0, column=1, sticky="nsew")
            self.show_progress()
        elif name == "convert":
            self.convert_frame.grid(row=0, column=1, sticky="nsew")
            self.show_progress()
        elif name == "rename":
            self.rename_frame.grid(row=0, column=1, sticky="nsew")
            self.show_progress()
        elif name == "reader":
            self.reader_frame.grid(row=0, column=1, sticky="nsew")
            self.show_progress()

    def is_any_task_running(self):
        """检查是否有任何后台任务正在运行"""
        # 这里可以通过检查线程状态或进度条状态来判断
        # 简单起见，如果进度条不是 0 且不是 100%，或者状态不是"准备就绪"，就认为在运行
        return self.status_label.cget("text") != "准备就绪" and self.progress_bar.get() < 1.0

    def change_appearance_mode_event(self, new_appearance_mode: str):
        ctk.set_appearance_mode(new_appearance_mode)

    def create_feature_card(self, parent, title, desc, row, col):
        """创建一个首页功能介绍卡片"""
        card = ctk.CTkFrame(parent, corner_radius=15, border_width=1, border_color="#3d3d3d")
        card.grid(row=row, column=col, padx=15, pady=15, sticky="nsew")
        
        card_title = ctk.CTkLabel(card, text=title, font=ctk.CTkFont(size=18, weight="bold"))
        card_title.pack(padx=20, pady=(20, 10))
        
        card_desc = ctk.CTkLabel(card, text=desc, font=ctk.CTkFont(size=13), justify="center")
        card_desc.pack(padx=20, pady=(0, 20))
        return card

    def set_reader_info_text(self, text):
        self.reader_info_textbox.configure(state="normal")
        self.reader_info_textbox.delete("1.0", "end")
        self.reader_info_textbox.insert("1.0", text)
        self.reader_info_textbox.configure(state="disabled")

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
                ("Comic Archives", "*.cbz *.zip"),
                ("CBZ Files", "*.cbz"),
                ("ZIP Files", "*.zip"),
                ("All Files", "*.*"),
            ],
        )
        if not file_path:
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

        kind_label = "文件夹" if entry["kind"] == "folder" else "压缩包"
        modified_text = datetime.fromtimestamp(entry["modified_ts"]).strftime("%Y-%m-%d %H:%M:%S")
        info_text = "\n".join(
            [
                f"名称: {entry['name']}",
                f"类型: {kind_label}",
                f"页数: {entry['page_count']}",
                f"大小: {format_bytes(entry['size_bytes'])}",
                f"修改时间: {modified_text}",
                f"路径: {entry['path']}",
            ]
        )
        self.reader_title_label.configure(text=entry["name"])
        self.set_reader_info_text(info_text)
        self.update_reader_file_actions(entry)

    def reset_reader_session(self, placeholder="从左侧选择漫画后即可在这里翻页阅读"):
        self.reader_current_entry = None
        self.reader_current_pages = []
        self.reader_current_page_index = -1
        self.reader_source_image = None
        self.reader_preview_image = None
        self.reader_preview_label.configure(text=placeholder, image=None)
        self.update_reader_page_controls()

    def refresh_reader_library(self, initial_path=None, select_first=True):
        if initial_path is not None:
            self.reader_source_entry.delete(0, tk.END)
            self.reader_source_entry.insert(0, initial_path)

        source_path = self.reader_source_entry.get().strip()
        if not source_path:
            self.reader_listbox.delete(0, tk.END)
            self.reader_library_entries = []
            self.update_reader_details(None)
            self.reset_reader_session("请先选择漫画目录或 CBZ/ZIP 文件")
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
            kind_text = "文件夹" if item["kind"] == "folder" else "CBZ/ZIP"
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

        self.reader_current_entry = entry
        self.reader_current_pages = pages
        self.reader_current_page_index = -1
        self.set_reader_page(
            min(max(1, target_page_number), len(pages)) - 1,
            persist=persist,
        )
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

    def set_reader_page(self, index, persist=True):
        if not self.reader_current_entry or not self.reader_current_pages:
            return

        if index < 0 or index >= len(self.reader_current_pages):
            return

        page_name = self.reader_current_pages[index]
        try:
            self.reader_source_image = load_comic_page_image(self.reader_current_entry["path"], page_name)
        except Exception as exc:
            messagebox.showerror("错误", f"读取漫画页面失败: {exc}")
            return

        self.reader_current_page_index = index
        self.update_reader_page_controls()
        self.refresh_reader_preview()
        self.status_label.configure(
            text=f"正在阅读 {self.reader_current_entry['name']} - 第 {index + 1}/{len(self.reader_current_pages)} 页"
        )
        if persist:
            self.persist_gui_state_snapshot()

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
        if getattr(self, "current_frame_name", "") != "reader" or not self.reader_current_pages:
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

    def refresh_reader_preview(self):
        if self.reader_source_image is None:
            return

        preview_width = max(self.reader_preview_label.winfo_width() - 20, 240)
        preview_height = max(self.reader_preview_label.winfo_height() - 20, 240)
        preview_image = self.reader_source_image.copy()
        preview_image.thumbnail((preview_width, preview_height), Image.LANCZOS)
        self.reader_preview_image = ctk.CTkImage(
            light_image=preview_image,
            dark_image=preview_image,
            size=preview_image.size,
        )
        self.reader_preview_label.configure(image=self.reader_preview_image, text="")

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
                    self.queue.put(("progress", progress))
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
                                self.queue.put(("progress", total_progress))
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
                        self.queue.put(msg)
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

    def check_queue(self):
        try:
            while not self.queue.empty():
                try:
                    message = self.queue.get_nowait()
                    msg_type, msg_data = message
                    
                    if msg_type == "success":
                        comic_title, chapter_links = msg_data
                        self.comic_title = comic_title
                        self.chapter_data = chapter_links
                        self.chapter_listbox.delete(0, tk.END)
                        for chapter_name, _ in chapter_links:
                            self.chapter_listbox.insert(tk.END, chapter_name)
                        self.log(f"成功获取漫画信息: {comic_title}")
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
                        self.log(f"成功搜索到第 {self.getcomics_search_current_page} 页，共 {len(comic_links)} 个漫画")
                        self.update_getcomics_pagination_controls(searching=False)
                    
                    elif msg_type == "error":
                        self.log(f"错误: {msg_data}")
                        messagebox.showerror("错误", msg_data)
                        self.fetch_button.configure(state="normal")
                        self.getcomics_search_button.configure(state="normal")
                    
                    elif msg_type == "log":
                        self.log(msg_data)
                    
                    elif msg_type == "progress":
                        progress_val = msg_data / 100
                        self.progress_bar.set(progress_val)
                        self.percent_label.configure(text=f"{int(msg_data)}%")
                    
                    elif msg_type == "info":
                        self.log(msg_data)
                        self.status_label.configure(text=msg_data)
                    
                    elif msg_type == "fetch_done":
                        self.progress_bar.stop()
                        self.progress_bar.configure(mode="determinate")
                        self.fetch_button.configure(state="normal")
                        self.reset_progress()
                    elif msg_type == "search_getcomics_done":
                        self.progress_bar.stop()
                        self.progress_bar.configure(mode="determinate")
                        self.update_getcomics_pagination_controls(searching=False)
                        self.reset_progress()
                    elif msg_type == "done":
                        self.download_thread = None
                        self.download_button.configure(state="normal")
                        self.cancel_button.configure(state="disabled")
                        self.progress_bar.set(1)
                        self.percent_label.configure(text="100%")
                    elif msg_type == "getcomics_done":
                        self.getcomics_thread = None
                        self.getcomics_download_button.configure(state="normal")
                        self.update_getcomics_view_toggle_button()
                        self.getcomics_cancel_button.configure(state="disabled")
                        self.progress_bar.set(1)
                        self.percent_label.configure(text="100%")
                    elif msg_type == "convert_done":
                        self.convert_button.configure(state="normal")
                        self.progress_bar.set(1)
                        self.percent_label.configure(text="100%")
                    elif msg_type == "complete":
                        messagebox.showinfo("完成", msg_data)
                        self.log(f"任务完成: {msg_data}")
                except queue.Empty:
                    break
                except Exception as e:
                    print(f"Error processing queue message: {e}")
                    continue
        finally:
            try:
                if self.winfo_exists():
                    self.queue_check_after_id = self.after(100, self.check_queue)
            except tk.TclError:
                self.queue_check_after_id = None

    def log(self, message):
        self.log_textbox.configure(state="normal")
        self.log_textbox.insert("end", message + "\n")
        self.log_textbox.see("end")
        self.log_textbox.configure(state="disabled")

    def clear_logs(self):
        self.log_textbox.configure(state="normal")
        self.log_textbox.delete("1.0", "end")
        self.log_textbox.configure(state="disabled")

    def show_log_menu(self, event):
        self.log_menu.post(event.x_root, event.y_root)
    
    def reset_progress(self):
        self.progress_bar.set(0)
        self.percent_label.configure(text="0%")
        self.status_label.configure(text="准备就绪")

    def select_all(self):
        self.chapter_listbox.select_set(0, tk.END)

    def deselect_all(self):
        self.chapter_listbox.select_clear(0, tk.END)

    def browse_convert_input(self):
        input_path = filedialog.askopenfilename(title="选择文件夹或 ZIP 文件")
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
        
        self.convert_button.configure(state="disabled")
        self.reset_progress()
        
        def convert_thread():
            try:
                def progress_callback(msg):
                    if isinstance(msg, tuple) and msg[0] == "progress":
                        self.queue.put(msg)
                    elif "添加图片" in msg:
                        match = re.search(r"(\d+)/(\d+)", msg)
                        if match:
                            curr, total = map(int, match.groups())
                            self.queue.put(("progress", (curr / total) * 100))
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
        if not DEEPSEEK_API_KEY:
            raise ValueError("DeepSeek API key is not configured. Set DEEPSEEK_API_KEY before using AI rename.")
        extension = os.path.splitext(filename)[1]
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {DEEPSEEK_API_KEY}"}
        user_prompt = f"分析并标准化文件名：{filename}"
        if folder_name: user_prompt += f"\n文件夹名：{folder_name}"
        payload = {
            "model": "deepseek-chat",
            "messages": [{"role": "system", "content": custom_prompt}, {"role": "user", "content": user_prompt}],
            "temperature": 0.1
        }
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=DEEPSEEK_TIMEOUT)
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
