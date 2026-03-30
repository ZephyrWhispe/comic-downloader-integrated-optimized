import os
import re
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox
import threading
import queue
import requests
import asyncio
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
from .getinfo import GetComics
from .download import download_comics
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
        self.sidebar_frame.grid_rowconfigure(6, weight=1)
        
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
        
        self.sidebar_button_6 = ctk.CTkButton(self.sidebar_frame, text="GUI 功能测试", command=self.test_gui_features, fg_color="gray", hover_color="#3d3d3d")
        self.sidebar_button_6.grid(row=6, column=0, padx=20, pady=10)
        
        self.appearance_mode_label = ctk.CTkLabel(self.sidebar_frame, text="外观模式:", anchor="w")
        self.appearance_mode_label.grid(row=7, column=0, padx=20, pady=(10, 0))
        self.appearance_mode_optionemenu = ctk.CTkOptionMenu(self.sidebar_frame, values=["Light", "Dark", "System"],
                                                                       command=self.change_appearance_mode_event)
        self.appearance_mode_optionemenu.grid(row=8, column=0, padx=20, pady=(10, 20))
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

        # ========== 底部进度和日志 (Bottom Panel) ==========
        self.bottom_frame = ctk.CTkFrame(self, height=200, corner_radius=10)
        # 初始不显示 grid
        self.bottom_frame.grid_columnconfigure(0, weight=1)
        self.bottom_frame.grid_rowconfigure(2, weight=1)
        
        self.status_label = ctk.CTkLabel(self.bottom_frame, text="准备就绪", anchor="w")
        self.status_label.grid(row=0, column=0, padx=20, pady=(10, 0), sticky="ew")
        
        self.open_folder_button = ctk.CTkButton(self.bottom_frame, text="打开下载目录", command=self.open_current_download_folder, width=120, height=24)
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
        
        # 定期检查队列
        self.check_queue()
        
        # 初始日志
        main_logger.info("现代版 GUI 已经启动，基于 CustomTkinter")
        self.log("提示: 下载过程中可以在下方实时看到进度和日志")

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
        self.getcomics_results_var = tk.StringVar(value="10")
        self.getcomics_results_combo = ctk.CTkOptionMenu(search_group, values=["5", "10", "20", "50"], variable=self.getcomics_results_var)
        self.getcomics_results_combo.grid(row=2, column=1, padx=10, pady=5, sticky="w")
        
        self.getcomics_search_button = ctk.CTkButton(search_group, text="搜索漫画", command=self.search_getcomics)
        self.getcomics_search_button.grid(row=3, column=0, columnspan=2, padx=10, pady=10, sticky="ew")
        
        # 结果列表
        self.getcomics_listbox = tk.Listbox(self.getcomics_frame, selectmode=tk.MULTIPLE, bg="#2b2b2b", fg="white", 
                                          borderwidth=0, highlightthickness=0, font=("Arial", 10))
        self.getcomics_listbox.grid(row=1, column=0, padx=20, pady=10, sticky="nsew")
        self.getcomics_frame.grid_rowconfigure(1, weight=1)
        
        # 保存位置
        save_group = ctk.CTkFrame(self.getcomics_frame)
        save_group.grid(row=2, column=0, padx=20, pady=10, sticky="ew")
        save_group.grid_columnconfigure(1, weight=1)
        
        ctk.CTkLabel(save_group, text="保存位置:").grid(row=0, column=0, padx=10, pady=10)
        self.getcomics_save_entry = ctk.CTkEntry(save_group)
        self.getcomics_save_entry.grid(row=0, column=1, padx=10, pady=10, sticky="ew")
        self.getcomics_save_entry.insert(0, os.path.join(os.path.expanduser("~"), "Documents", "Comics"))
        ctk.CTkButton(save_group, text="浏览", command=self.browse_getcomics_save_dir, width=80).grid(row=0, column=2, padx=5, pady=10)
        ctk.CTkButton(save_group, text="打开", command=lambda: self.open_folder(self.getcomics_save_entry.get()), width=80).grid(row=0, column=3, padx=5, pady=10)
        
        # 控制
        ctrl_group = ctk.CTkFrame(self.getcomics_frame)
        ctrl_group.grid(row=3, column=0, padx=20, pady=10, sticky="ew")
        self.getcomics_download_button = ctk.CTkButton(ctrl_group, text="开始下载", command=self.start_getcomics_download, fg_color="green", hover_color="darkgreen")
        self.getcomics_download_button.grid(row=0, column=0, padx=10, pady=10)
        self.getcomics_cancel_button = ctk.CTkButton(ctrl_group, text="取消下载", command=self.cancel_getcomics_download, state="disabled", fg_color="red", hover_color="darkred")
        self.getcomics_cancel_button.grid(row=0, column=1, padx=10, pady=10)

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

    def search_getcomics(self):
        query = self.getcomics_query_entry.get().strip()
        if not query:
            messagebox.showerror("错误", "请输入搜索内容")
            return
        
        self.getcomics_results_data = []
        self.getcomics_listbox.delete(0, tk.END)
        self.show_progress()
        date = self.getcomics_date_entry.get().strip()
        results = int(self.getcomics_results_var.get())
        
        self.log(f"正在搜索 GetComics: {query}")
        self.getcomics_search_button.configure(state="disabled")
        self.reset_progress()
        self.progress_bar.configure(mode="indeterminate")
        self.progress_bar.start()
        
        def search_thread():
            try:
                self.getcomics_downloader = GetComics(query, results, True, date=date or None)
                async def search_async():
                    await self.getcomics_downloader.find_pages()
                    await self.getcomics_downloader.get_download_links()
                asyncio.run(search_async())
                
                if not self.getcomics_downloader.comic_links:
                    self.queue.put(("error", "未找到搜索结果"))
                    return
                
                self.queue.put(("getcomics_success", self.getcomics_downloader.comic_links))
            except Exception as e:
                self.queue.put(("error", f"搜索失败: {str(e)}"))
            finally:
                self.queue.put(("search_getcomics_done", None))
        
        self.getcomics_thread = threading.Thread(target=search_thread, daemon=True)
        self.getcomics_thread.start()

    def start_getcomics_download(self):
        selected_indices = self.getcomics_listbox.curselection()
        if not selected_indices:
            messagebox.showerror("错误", "请选择要下载的漫画")
            return
        
        if not self.getcomics_downloader:
            messagebox.showerror("错误", "请先搜索漫画")
            return
        
        selected_comics = {}
        for i in selected_indices:
            if i < len(self.getcomics_results_data):
                url, title = self.getcomics_results_data[i]
                selected_comics[url] = title
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
                    self.queue.put(("complete", "GetComics 下载完成"))
            except Exception as e:
                self.queue.put(("error", f"下载失败: {str(e)}"))
            finally:
                self.queue.put(("getcomics_done", None))
        
        self.getcomics_thread = threading.Thread(target=download_thread, daemon=True)
        self.getcomics_thread.start()

    def cancel_getcomics_download(self):
        self.is_getcomics_cancelled = True
        self.queue.put(("info", "取消下载..."))

    def browse_getcomics_save_dir(self):
        directory = filedialog.askdirectory(title="选择保存目录")
        if directory:
            self.getcomics_save_entry.delete(0, tk.END)
            self.getcomics_save_entry.insert(0, directory)

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
                        comic_links = msg_data
                        self.getcomics_results_data = list(comic_links.items())
                        self.getcomics_listbox.delete(0, tk.END)
                        for _, comic_title in self.getcomics_results_data:
                            self.getcomics_listbox.insert(tk.END, comic_title)
                        self.log(f"成功搜索到 {len(comic_links)} 个漫画")
                        self.getcomics_search_button.configure(state="normal")
                    
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
                        self.getcomics_search_button.configure(state="normal")
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
            self.after(100, self.check_queue)

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

    def test_gui_features(self):
        self.show_progress()
        self.reset_progress()
        self.log("开始测试 GUI 功能...")
        def test_thread():
            import time
            for i in range(1, 101):
                self.queue.put(("progress", i))
                self.queue.put(("info", f"正在模拟处理... {i}%"))
                time.sleep(0.02)
            self.queue.put(("info", "测试完成!"))
        threading.Thread(target=test_thread, daemon=True).start()

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
        
        # 如果当前页面没有路径或路径不存在，尝试备选路径
        if not path or not os.path.exists(path):
            # 优先打开 Comic-DL 的保存路径，如果为空则尝试 GetComics 的
            path = self.save_entry.get()
            if not path or not os.path.exists(path):
                path = self.getcomics_save_entry.get()
            
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
        if (self.download_thread and self.download_thread.is_alive()) or (self.getcomics_thread and self.getcomics_thread.is_alive()):
            if messagebox.askokcancel("确认", "正在任务中，确定关闭吗？"):
                self.comic_dl_downloader.close_parsers()
                self.destroy()
        else:
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
