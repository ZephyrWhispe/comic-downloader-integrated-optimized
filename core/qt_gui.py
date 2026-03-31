import asyncio
import logging
import os
import re
import sys
import threading
import webbrowser
from dataclasses import dataclass
from pathlib import Path

import requests
from PIL import Image
from PySide6.QtCore import QObject, QSize, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QCloseEvent, QImage, QKeySequence, QPalette, QPixmap, QShortcut, QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QStyle,
    QStyleOptionTab,
    QStylePainter,
    QTabBar,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .comic_downloader import ComicDownloader
from .comic_reader import (
    DEFAULT_READER_ZOOM_MODE,
    calculate_reader_image_size,
    clamp_reader_zoom_percent,
    discover_comics,
    format_bytes,
    get_comic_source_requirement_message,
    get_format_support_notice_lines,
    list_comic_pages,
    load_comic_page_image,
    normalize_reader_zoom_mode,
)
from .download import download_comics
from .getcomics_gui_helpers import (
    collect_selected_getcomics_results,
    format_getcomics_results_for_clipboard,
    remove_getcomics_results,
    upsert_getcomics_results,
)
from .getinfo import GetComics
from .gui_state import (
    DEFAULT_APPEARANCE_MODE,
    DEFAULT_GETCOMICS_RESULTS,
    DEFAULT_RENAME_API_MODEL,
    DEFAULT_RENAME_API_TIMEOUT,
    DEFAULT_RENAME_API_URL,
    DEFAULT_WINDOWS_READER_FULLSCREEN_MODE,
    build_getcomics_history_label,
    load_gui_state,
    normalize_cached_getcomics_results,
    normalize_reader_scroll_fraction,
    save_gui_state,
    upsert_recent_getcomics_search,
)
from .logger import log_filename, main_logger


ENV_DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
WINDOWS_READER_FULLSCREEN_MODE_LABELS = {
    "smooth": "顺滑全屏（推荐）",
    "exclusive": "真全屏（隐藏任务栏）",
}
WINDOWS_READER_FULLSCREEN_MODE_VALUES = {
    label: value for value, label in WINDOWS_READER_FULLSCREEN_MODE_LABELS.items()
}
READER_ZOOM_MODE_LABELS = {
    "fit_window": "适应窗口",
    "fit_width": "适应宽度",
    "manual": "自定义缩放",
}
READER_ZOOM_MODE_VALUES = {
    label: value for value, label in READER_ZOOM_MODE_LABELS.items()
}
READER_ZOOM_STEP = 10
READER_RENDER_DELAY_MS = 90
READER_FULLSCREEN_TRANSITION_MS = 180


def pil_image_to_qpixmap(image):
    if image.mode != "RGBA":
        image = image.convert("RGBA")
    data = image.tobytes("raw", "RGBA")
    qimage = QImage(
        data,
        image.width,
        image.height,
        image.width * 4,
        QImage.Format.Format_RGBA8888,
    )
    return QPixmap.fromImage(qimage.copy())


def open_path(path):
    target_path = str(path or "").strip()
    if not target_path:
        return False
    if os.name == "nt":
        try:
            os.startfile(target_path)
            return True
        except OSError:
            return False
    return False


def build_support_notice_text():
    return "\n".join(get_format_support_notice_lines())


def build_reader_entry_description(entry):
    if not entry:
        return "请选择左侧漫画文件。"
    info_lines = [
        f"名称: {entry['name']}",
        f"格式: {entry.get('format') or '-'}",
        f"页数: {entry.get('page_count', 0)}",
        f"大小: {format_bytes(entry.get('size_bytes', 0))}",
        f"路径: {entry['path']}",
    ]
    support_message = get_comic_source_requirement_message(entry["path"], action="打开")
    if support_message:
        info_lines.extend(["", f"提示: {support_message}"])
    return "\n".join(info_lines)


def create_dark_palette():
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(24, 27, 32))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(240, 243, 247))
    palette.setColor(QPalette.ColorRole.Base, QColor(18, 21, 26))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(31, 35, 42))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(31, 35, 42))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(240, 243, 247))
    palette.setColor(QPalette.ColorRole.Text, QColor(240, 243, 247))
    palette.setColor(QPalette.ColorRole.Button, QColor(34, 39, 47))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(240, 243, 247))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(38, 120, 196))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    return palette


def build_app_stylesheet(dark_mode):
    if dark_mode:
        return """
QMainWindow, QWidget { font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif; font-size: 13px; }
QTabWidget::pane { border: 1px solid #2f3946; border-radius: 8px; background: #171a1f; }
QTabBar::tab { background: #232830; color: #d8dee6; padding: 8px 12px; margin-bottom: 3px; min-width: 128px; min-height: 18px; border-top-left-radius: 8px; border-bottom-left-radius: 8px; text-align: center; }
QTabBar::tab:selected { background: #2a5c93; color: #ffffff; }
QGroupBox { border: 1px solid #313845; border-radius: 10px; margin-top: 12px; font-weight: 600; padding-top: 10px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; }
QPlainTextEdit, QTextEdit, QListWidget, QLineEdit, QTableWidget, QComboBox, QSpinBox { background: #1b1f25; border: 1px solid #3a4452; border-radius: 7px; padding: 6px; selection-background-color: #2a5c93; }
QPushButton { background: #2a5c93; color: #ffffff; border: 0; border-radius: 7px; padding: 8px 14px; }
QPushButton:hover:!disabled { background: #3270b4; }
QPushButton:disabled { background: #474f59; color: #aab0b8; }
QHeaderView::section { background: #252a32; padding: 6px; border: 0; border-bottom: 1px solid #3a4452; }
"""
    return """
QMainWindow, QWidget { font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif; font-size: 13px; }
QTabWidget::pane { border: 1px solid #cdd6df; border-radius: 8px; background: #ffffff; }
QTabBar::tab { background: #eef3f8; color: #23313f; padding: 8px 12px; margin-bottom: 3px; min-width: 128px; min-height: 18px; border-top-left-radius: 8px; border-bottom-left-radius: 8px; text-align: center; }
QTabBar::tab:selected { background: #d5e7f8; color: #15304f; }
QGroupBox { border: 1px solid #d7dfe8; border-radius: 10px; margin-top: 12px; font-weight: 600; padding-top: 10px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; }
QPlainTextEdit, QTextEdit, QListWidget, QLineEdit, QTableWidget, QComboBox, QSpinBox { background: #ffffff; border: 1px solid #c9d5e1; border-radius: 7px; padding: 6px; selection-background-color: #cfe4fb; }
QPushButton { background: #2870b7; color: #ffffff; border: 0; border-radius: 7px; padding: 8px 14px; }
QPushButton:hover:!disabled { background: #3380ce; }
QPushButton:disabled { background: #d0d7df; color: #7b8794; }
QHeaderView::section { background: #eef4f9; padding: 6px; border: 0; border-bottom: 1px solid #d7dfe8; }
"""


@dataclass
class ReaderRenderRequest:
    reset_scroll: bool = False
    scroll_position: tuple[float, float] | None = None
    invalidate: bool = False


class TaskSignals(QObject):
    progress = Signal(float)
    info = Signal(str)
    error = Signal(str)
    result = Signal(object)
    finished = Signal()


class QtLogEmitter(QObject):
    message = Signal(str)


class QtLogHandler(logging.Handler):
    def __init__(self, emitter):
        super().__init__()
        self.emitter = emitter
        self.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))

    def emit(self, record):
        try:
            self.emitter.message.emit(self.format(record))
        except Exception:
            pass


class ReaderScrollArea(QScrollArea):
    resized = Signal()
    boundaryPageRequested = Signal(int)
    doubleClicked = Signal()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.resized.emit()

    def mouseDoubleClickEvent(self, event):
        super().mouseDoubleClickEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self.doubleClicked.emit()

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            super().wheelEvent(event)
            return
        delta = event.angleDelta().y()
        vertical_bar = self.verticalScrollBar()
        if delta < 0 and vertical_bar.value() >= vertical_bar.maximum():
            self.boundaryPageRequested.emit(1)
            event.accept()
            return
        if delta > 0 and vertical_bar.value() <= vertical_bar.minimum():
            self.boundaryPageRequested.emit(-1)
            event.accept()
            return
        super().wheelEvent(event)


class HorizontalWestTabBar(QTabBar):
    def tabSizeHint(self, index):
        text_width = self.fontMetrics().horizontalAdvance(self.tabText(index))
        target_width = min(max(text_width + 34, 104), 136)
        return QSize(target_width, 38)

    def paintEvent(self, event):
        painter = QStylePainter(self)
        option = QStyleOptionTab()
        for index in range(self.count()):
            self.initStyleOption(option, index)
            option.shape = QTabBar.Shape.RoundedNorth
            option.rect = self.tabRect(index)
            painter.drawControl(QStyle.ControlElement.CE_TabBarTabShape, option)
            painter.save()
            if option.state & QStyle.StateFlag.State_Selected:
                text_color = option.palette.color(QPalette.ColorRole.HighlightedText)
            else:
                text_color = option.palette.color(QPalette.ColorRole.ButtonText)
            painter.setPen(text_color)
            painter.drawText(option.rect, int(Qt.AlignmentFlag.AlignCenter), self.tabText(index))
            painter.restore()


class ComicDownloaderQtWindow(QMainWindow):
    TAB_NAMES = ("home", "comic_dl", "getcomics", "convert", "rename", "reader_library", "reader_view", "logs", "settings")

    def __init__(self):
        super().__init__()
        self.setWindowTitle("漫画下载器整合版 - Qt")
        self.resize(1480, 920)
        self.setMinimumSize(1220, 780)

        self.default_getcomics_save_dir = os.path.join(os.path.expanduser("~"), "Documents", "Comics")
        self.gui_state_path = Path(__file__).resolve().parent.parent / ".gui_state.json"
        self.gui_state = load_gui_state(self.gui_state_path, default_save_dir=self.default_getcomics_save_dir)

        app = QApplication.instance()
        self.default_palette = QPalette(app.palette()) if app else QPalette()

        settings_state = self.gui_state.get("settings", {})
        self.appearance_mode = str(settings_state.get("appearance_mode", DEFAULT_APPEARANCE_MODE) or DEFAULT_APPEARANCE_MODE)
        self.reader_windows_fullscreen_mode = str(
            settings_state.get("reader_windows_fullscreen_mode", DEFAULT_WINDOWS_READER_FULLSCREEN_MODE)
            or DEFAULT_WINDOWS_READER_FULLSCREEN_MODE
        )
        self.rename_api_key = str(settings_state.get("rename_api_key", "") or "").strip()
        self.rename_api_url = str(settings_state.get("rename_api_url", DEFAULT_RENAME_API_URL) or DEFAULT_RENAME_API_URL).strip()
        self.rename_api_model = str(settings_state.get("rename_api_model", DEFAULT_RENAME_API_MODEL) or DEFAULT_RENAME_API_MODEL).strip()
        try:
            self.rename_api_timeout = int(settings_state.get("rename_api_timeout", DEFAULT_RENAME_API_TIMEOUT) or DEFAULT_RENAME_API_TIMEOUT)
        except (TypeError, ValueError):
            self.rename_api_timeout = DEFAULT_RENAME_API_TIMEOUT

        self.comic_dl_downloader = ComicDownloader()
        self.comic_title = ""
        self.chapter_data = []
        self.is_cancelled = False
        self.is_getcomics_cancelled = False
        self.getcomics_downloader = None

        self.getcomics_recent_searches = list(self.gui_state["getcomics"]["recent_searches"])
        self.getcomics_favorites = [(item["url"], item["title"]) for item in self.gui_state["getcomics"]["favorites"]]
        self.getcomics_download_queue = [(item["url"], item["title"]) for item in self.gui_state["getcomics"]["queue_items"]]
        self.getcomics_view_mode = self.gui_state["getcomics"]["view_mode"]
        self.getcomics_search_results_data = [(item["url"], item["title"]) for item in self.gui_state["getcomics"]["last_results"]]
        self.getcomics_results_data = []
        self.getcomics_results_restored_from_cache = bool(self.getcomics_search_results_data)
        self.getcomics_search_current_page = self.gui_state["getcomics"]["last_page"]
        self.getcomics_current_page = self.getcomics_search_current_page
        self.is_updating_getcomics_history_menu = False

        self.reader_library_entries = []
        self.reader_current_entry = None
        self.reader_current_pages = []
        self.reader_current_page_index = -1
        self.reader_source_image = None
        self.reader_image_pixmap = None
        self.reader_preview_render_key = None
        self.reader_focus_mode = bool(self.gui_state["reader"]["focus_mode"])
        self.reader_focus_mode_before_fullscreen = self.reader_focus_mode
        self.reader_fullscreen_active = False
        self.reader_zoom_mode = normalize_reader_zoom_mode(self.gui_state["reader"].get("zoom_mode", DEFAULT_READER_ZOOM_MODE))
        self.reader_zoom_percent = clamp_reader_zoom_percent(self.gui_state["reader"].get("zoom_percent", 100))
        self.reader_scroll_positions = {}
        self.reader_pending_render = None
        self._reader_tab_bar_visible_before_fullscreen = True
        self._reader_window_was_maximized = False
        self._reader_window_size_before_fullscreen = self.size()

        active_path = str(self.gui_state["reader"].get("active_path") or "").strip()
        active_page = max(0, int(self.gui_state["reader"].get("active_page", 0) or 0))
        if active_path and active_page > 0:
            self.reader_scroll_positions[(active_path, active_page - 1)] = (
                normalize_reader_scroll_fraction(self.gui_state["reader"].get("scroll_x")),
                normalize_reader_scroll_fraction(self.gui_state["reader"].get("scroll_y")),
            )

        self.rename_files = []
        self._threads = []
        self._latest_error_text = "暂无错误"
        self._pending_log_lines = []
        self._ui_ready = False

        self.log_emitter = QtLogEmitter()
        self.qt_log_handler = QtLogHandler(self.log_emitter)
        self.log_emitter.message.connect(self.append_log)
        logging.getLogger().addHandler(self.qt_log_handler)

        self.reader_render_timer = QTimer(self)
        self.reader_render_timer.setSingleShot(True)
        self.reader_render_timer.timeout.connect(self.flush_reader_render)

        self.reader_scroll_save_timer = QTimer(self)
        self.reader_scroll_save_timer.setSingleShot(True)
        self.reader_scroll_save_timer.timeout.connect(self.store_current_reader_scroll_position)

        self.build_ui()
        self.apply_appearance_mode(self.appearance_mode, persist=False)
        self.restore_state()
        self.update_supported_sites_summary()
        self.update_comic_dl_site_status()
        self.refresh_getcomics_history_menu()
        self.set_getcomics_view_mode(self.getcomics_view_mode, persist=False)
        self.refresh_reader_library(
            initial_path=self.gui_state["reader"].get("source_path", self.default_getcomics_save_dir),
            select_first=False,
        )
        self.restore_reader_state()
        self.refresh_settings_labels()
        self.load_recent_log_tail()
        self._ui_ready = True
        self.log("Qt 主界面已切换为 PySide6，全功能标签页已启用。")

    def build_ui(self):
        central = QWidget()
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(10, 10, 10, 10)
        root_layout.setSpacing(10)

        self.tabs = QTabWidget()
        self.tabs.setTabBar(HorizontalWestTabBar())
        self.tabs.setTabPosition(QTabWidget.TabPosition.West)
        self.tabs.setUsesScrollButtons(False)
        self.tabs.currentChanged.connect(self.on_tab_changed)
        root_layout.addWidget(self.tabs)

        self.home_tab = QWidget()
        self.comic_dl_tab = QWidget()
        self.getcomics_tab = QWidget()
        self.convert_tab = QWidget()
        self.rename_tab = QWidget()
        self.reader_library_tab = QWidget()
        self.reader_view_tab = QWidget()
        self.logs_tab = QWidget()
        self.settings_tab = QWidget()

        self.tabs.addTab(self.home_tab, "主页")
        self.tabs.addTab(self.comic_dl_tab, "Comic DL")
        self.tabs.addTab(self.getcomics_tab, "GetComics")
        self.tabs.addTab(self.convert_tab, "转 CBZ")
        self.tabs.addTab(self.rename_tab, "重命名")
        self.tabs.addTab(self.reader_library_tab, "漫画库")
        self.tabs.addTab(self.reader_view_tab, "阅读器")
        self.tabs.addTab(self.logs_tab, "日志")
        self.tabs.addTab(self.settings_tab, "设置")

        self.setup_home_tab()
        self.setup_comic_dl_tab()
        self.setup_getcomics_tab()
        self.setup_convert_tab()
        self.setup_rename_tab()
        self.setup_reader_library_tab()
        self.setup_reader_view_tab()
        self.setup_logs_tab()
        self.setup_settings_tab()

        self.setCentralWidget(central)

        status_bar = QStatusBar()
        self.status_label = QLabel("准备就绪")
        self.status_progress_bar = QProgressBar()
        self.status_progress_bar.setFixedWidth(220)
        self.status_progress_bar.setRange(0, 100)
        self.status_progress_bar.setValue(0)
        status_bar.addWidget(self.status_label, 1)
        status_bar.addPermanentWidget(self.status_progress_bar)
        self.setStatusBar(status_bar)

        QShortcut(QKeySequence("F11"), self, activated=self.toggle_reader_fullscreen_mode)
        QShortcut(QKeySequence("Escape"), self, activated=self.handle_escape_shortcut)
        QShortcut(QKeySequence("Left"), self, activated=lambda: self.change_reader_page(-1))
        QShortcut(QKeySequence("Right"), self, activated=lambda: self.change_reader_page(1))
        QShortcut(QKeySequence("PgUp"), self, activated=lambda: self.change_reader_page(-1))
        QShortcut(QKeySequence("PgDown"), self, activated=lambda: self.change_reader_page(1))
        QShortcut(QKeySequence("Home"), self, activated=lambda: self.set_reader_page(0))
        QShortcut(QKeySequence("End"), self, activated=self.go_to_last_reader_page)

    def setup_home_tab(self):
        layout = QVBoxLayout(self.home_tab)
        layout.setSpacing(14)

        title = QLabel("漫画下载器")
        title.setStyleSheet("font-size: 28px; font-weight: 700;")
        layout.addWidget(title)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)
        layout.addLayout(grid)

        cards = [
            ("Comic-DL", "抓取在线章节页面，适合按话下载并保存到本地。", "comic_dl"),
            ("GetComics", "搜索整卷美漫资源，可收藏、排队并批量下载。", "getcomics"),
            ("转为 CBZ", "把文件夹、压缩包、7z、PDF 等来源统一整理成 CBZ。", "convert"),
            ("重命名", "调用 API 识别系列和刊号，批量规范漫画文件名。", "rename"),
            ("漫画库", "扫描目录或单文件，查看页数、格式和文件位置。", "reader_library"),
            ("阅读器", "支持滚轮翻页、缩放、专注模式和 Windows 全屏。", "reader_view"),
            ("日志", "记录下载、转换、解析和异常信息，方便维护排错。", "logs"),
            ("设置", "调整界面主题、全屏策略与重命名接口参数。", "settings"),
        ]
        for index, (card_title, description, tab_name) in enumerate(cards):
            card = QGroupBox(card_title)
            card.setMinimumHeight(126)
            card_layout = QVBoxLayout(card)
            card_layout.setSpacing(12)
            desc = QLabel(description)
            desc.setWordWrap(True)
            desc.setStyleSheet("font-size: 13px;")
            button = QPushButton("进入")
            button.setFixedWidth(82)
            button.setFixedHeight(32)
            button.clicked.connect(lambda _checked=False, name=tab_name: self.switch_tab(name))
            card_layout.addWidget(desc)
            card_layout.addStretch(1)
            button_row = QHBoxLayout()
            button_row.addStretch(1)
            button_row.addWidget(button)
            card_layout.addLayout(button_row)
            row, col = divmod(index, 2)
            grid.addWidget(card, row, col)

        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        layout.addStretch(1)

    def setup_comic_dl_tab(self):
        layout = QVBoxLayout(self.comic_dl_tab)
        layout.setSpacing(10)

        url_group = QGroupBox("漫画地址")
        url_layout = QGridLayout(url_group)
        self.comic_dl_url_edit = QLineEdit()
        self.comic_dl_url_edit.setPlaceholderText("请输入漫画主页链接")
        self.comic_dl_url_edit.textChanged.connect(self.update_comic_dl_site_status)
        self.comic_dl_fetch_button = QPushButton("获取章节")
        self.comic_dl_fetch_button.clicked.connect(self.fetch_comic_info)
        url_layout.addWidget(QLabel("URL"), 0, 0)
        url_layout.addWidget(self.comic_dl_url_edit, 0, 1)
        url_layout.addWidget(self.comic_dl_fetch_button, 0, 2)
        layout.addWidget(url_group)

        info_group = QGroupBox("站点信息")
        info_layout = QFormLayout(info_group)
        self.comic_dl_site_status_label = QLabel("等待输入 URL")
        self.comic_dl_site_status_label.setWordWrap(True)
        self.comic_dl_supported_sites_text = QPlainTextEdit()
        self.comic_dl_supported_sites_text.setReadOnly(True)
        self.comic_dl_supported_sites_text.setFixedHeight(120)
        info_layout.addRow("识别结果", self.comic_dl_site_status_label)
        info_layout.addRow("当前支持", self.comic_dl_supported_sites_text)
        layout.addWidget(info_group)

        chapters_group = QGroupBox("章节列表")
        chapters_layout = QVBoxLayout(chapters_group)
        self.comic_dl_chapter_list = QListWidget()
        self.comic_dl_chapter_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        chapters_layout.addWidget(self.comic_dl_chapter_list)
        chapter_actions = QHBoxLayout()
        select_all_button = QPushButton("全选")
        deselect_all_button = QPushButton("取消全选")
        select_all_button.clicked.connect(self.comic_dl_chapter_list.selectAll)
        deselect_all_button.clicked.connect(self.comic_dl_chapter_list.clearSelection)
        chapter_actions.addWidget(select_all_button)
        chapter_actions.addWidget(deselect_all_button)
        chapter_actions.addStretch(1)
        chapters_layout.addLayout(chapter_actions)
        layout.addWidget(chapters_group, 1)

        save_group = QGroupBox("保存位置")
        save_layout = QHBoxLayout(save_group)
        self.comic_dl_save_dir_edit = QLineEdit(self.comic_dl_downloader.base_dir)
        browse_button = QPushButton("浏览")
        browse_button.clicked.connect(self.browse_comic_dl_save_dir)
        open_button = QPushButton("打开")
        open_button.clicked.connect(lambda: self.open_folder(self.comic_dl_save_dir_edit.text()))
        save_layout.addWidget(self.comic_dl_save_dir_edit, 1)
        save_layout.addWidget(browse_button)
        save_layout.addWidget(open_button)
        layout.addWidget(save_group)

        controls = QHBoxLayout()
        self.comic_dl_download_button = QPushButton("开始下载")
        self.comic_dl_download_button.clicked.connect(self.start_comic_download)
        self.comic_dl_cancel_button = QPushButton("取消下载")
        self.comic_dl_cancel_button.clicked.connect(self.cancel_comic_download)
        self.comic_dl_cancel_button.setEnabled(False)
        controls.addWidget(self.comic_dl_download_button)
        controls.addWidget(self.comic_dl_cancel_button)
        controls.addStretch(1)
        layout.addLayout(controls)

    def setup_getcomics_tab(self):
        layout = QVBoxLayout(self.getcomics_tab)
        layout.setSpacing(10)

        search_group = QGroupBox("搜索")
        search_layout = QGridLayout(search_group)
        self.getcomics_query_edit = QLineEdit()
        self.getcomics_date_edit = QLineEdit()
        self.getcomics_date_edit.setPlaceholderText("YYYY / YYYY-MM / YYYY-MM-DD")
        self.getcomics_results_combo = QComboBox()
        self.getcomics_results_combo.addItems(["5", "10", "20", "50"])
        self.getcomics_search_button = QPushButton("搜索")
        self.getcomics_search_button.clicked.connect(self.search_getcomics)
        self.getcomics_prev_button = QPushButton("上一页")
        self.getcomics_prev_button.clicked.connect(self.load_previous_getcomics_page)
        self.getcomics_next_button = QPushButton("下一页")
        self.getcomics_next_button.clicked.connect(self.load_next_getcomics_page)
        self.getcomics_page_label = QLabel("当前页：未搜索")
        self.getcomics_jump_spin = QSpinBox()
        self.getcomics_jump_spin.setMinimum(1)
        self.getcomics_jump_spin.setMaximum(9999)
        self.getcomics_jump_button = QPushButton("跳转")
        self.getcomics_jump_button.clicked.connect(self.jump_to_getcomics_page)

        search_layout.addWidget(QLabel("关键词"), 0, 0)
        search_layout.addWidget(self.getcomics_query_edit, 0, 1)
        search_layout.addWidget(QLabel("日期过滤"), 0, 2)
        search_layout.addWidget(self.getcomics_date_edit, 0, 3)
        search_layout.addWidget(QLabel("结果数"), 0, 4)
        search_layout.addWidget(self.getcomics_results_combo, 0, 5)
        search_layout.addWidget(self.getcomics_search_button, 0, 6)

        self.getcomics_recent_combo = QComboBox()
        self.getcomics_recent_combo.currentIndexChanged.connect(self.apply_recent_getcomics_search)
        self.getcomics_clear_history_button = QPushButton("清空历史")
        self.getcomics_clear_history_button.clicked.connect(self.clear_getcomics_history)
        search_layout.addWidget(QLabel("最近搜索"), 1, 0)
        search_layout.addWidget(self.getcomics_recent_combo, 1, 1, 1, 3)
        search_layout.addWidget(self.getcomics_clear_history_button, 1, 4)
        search_layout.addWidget(self.getcomics_prev_button, 1, 5)
        search_layout.addWidget(self.getcomics_next_button, 1, 6)

        search_layout.addWidget(self.getcomics_page_label, 2, 0, 1, 3)
        search_layout.addWidget(QLabel("跳转页码"), 2, 3)
        search_layout.addWidget(self.getcomics_jump_spin, 2, 4)
        search_layout.addWidget(self.getcomics_jump_button, 2, 5)
        layout.addWidget(search_group)

        results_group = QGroupBox("搜索结果")
        results_layout = QVBoxLayout(results_group)
        self.getcomics_results_list = QListWidget()
        self.getcomics_results_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.getcomics_results_list.itemDoubleClicked.connect(lambda _item: self.open_selected_getcomics_results())
        self.getcomics_results_list.itemSelectionChanged.connect(self.update_getcomics_action_states)
        results_layout.addWidget(self.getcomics_results_list)
        layout.addWidget(results_group, 1)

        actions = QHBoxLayout()
        self.getcomics_open_button = QPushButton("打开详情")
        self.getcomics_open_button.clicked.connect(self.open_selected_getcomics_results)
        self.getcomics_copy_button = QPushButton("复制链接")
        self.getcomics_copy_button.clicked.connect(self.copy_selected_getcomics_links)
        self.getcomics_add_favorite_button = QPushButton("加入收藏")
        self.getcomics_add_favorite_button.clicked.connect(self.add_selected_getcomics_to_favorites)
        self.getcomics_remove_favorite_button = QPushButton("移除收藏")
        self.getcomics_remove_favorite_button.clicked.connect(self.remove_selected_getcomics_from_favorites)
        self.getcomics_toggle_favorite_button = QPushButton("查看收藏")
        self.getcomics_toggle_favorite_button.clicked.connect(self.toggle_getcomics_view_mode)
        self.getcomics_add_queue_button = QPushButton("加入队列")
        self.getcomics_add_queue_button.clicked.connect(self.add_selected_getcomics_to_queue)
        self.getcomics_remove_queue_button = QPushButton("移除队列")
        self.getcomics_remove_queue_button.clicked.connect(self.remove_selected_getcomics_from_queue)
        self.getcomics_toggle_queue_button = QPushButton("查看队列")
        self.getcomics_toggle_queue_button.clicked.connect(self.toggle_getcomics_queue_view)
        self.getcomics_clear_queue_button = QPushButton("清空队列")
        self.getcomics_clear_queue_button.clicked.connect(self.clear_getcomics_queue)
        for button in (
            self.getcomics_open_button,
            self.getcomics_copy_button,
            self.getcomics_add_favorite_button,
            self.getcomics_remove_favorite_button,
            self.getcomics_toggle_favorite_button,
            self.getcomics_add_queue_button,
            self.getcomics_remove_queue_button,
            self.getcomics_toggle_queue_button,
            self.getcomics_clear_queue_button,
        ):
            actions.addWidget(button)
        actions.addStretch(1)
        layout.addLayout(actions)

        save_group = QGroupBox("保存位置")
        save_layout = QHBoxLayout(save_group)
        self.getcomics_save_dir_edit = QLineEdit(self.default_getcomics_save_dir)
        browse_button = QPushButton("浏览")
        browse_button.clicked.connect(self.browse_getcomics_save_dir)
        open_button = QPushButton("打开")
        open_button.clicked.connect(lambda: self.open_folder(self.getcomics_save_dir_edit.text()))
        save_layout.addWidget(self.getcomics_save_dir_edit, 1)
        save_layout.addWidget(browse_button)
        save_layout.addWidget(open_button)
        layout.addWidget(save_group)

        download_controls = QHBoxLayout()
        self.getcomics_download_button = QPushButton("下载选中")
        self.getcomics_download_button.clicked.connect(self.start_getcomics_download)
        self.getcomics_download_queue_button = QPushButton("下载队列")
        self.getcomics_download_queue_button.clicked.connect(self.start_getcomics_queue_download)
        self.getcomics_cancel_button = QPushButton("取消下载")
        self.getcomics_cancel_button.clicked.connect(self.cancel_getcomics_download)
        self.getcomics_cancel_button.setEnabled(False)
        download_controls.addWidget(self.getcomics_download_button)
        download_controls.addWidget(self.getcomics_download_queue_button)
        download_controls.addWidget(self.getcomics_cancel_button)
        download_controls.addStretch(1)
        layout.addLayout(download_controls)

    def setup_convert_tab(self):
        layout = QVBoxLayout(self.convert_tab)
        layout.setSpacing(10)

        group = QGroupBox("转换为 CBZ")
        group_layout = QGridLayout(group)
        self.convert_input_edit = QLineEdit()
        self.convert_output_edit = QLineEdit()
        group_layout.addWidget(QLabel("输入"), 0, 0)
        group_layout.addWidget(self.convert_input_edit, 0, 1)
        input_file_button = QPushButton("选择文件")
        input_file_button.clicked.connect(self.browse_convert_input_file)
        input_dir_button = QPushButton("选择目录")
        input_dir_button.clicked.connect(self.browse_convert_input_dir)
        group_layout.addWidget(input_file_button, 0, 2)
        group_layout.addWidget(input_dir_button, 0, 3)
        group_layout.addWidget(QLabel("输出"), 1, 0)
        group_layout.addWidget(self.convert_output_edit, 1, 1)
        output_button = QPushButton("浏览")
        output_button.clicked.connect(self.browse_convert_output)
        open_output_button = QPushButton("打开目录")
        open_output_button.clicked.connect(self.open_convert_output_dir)
        group_layout.addWidget(output_button, 1, 2)
        group_layout.addWidget(open_output_button, 1, 3)
        self.convert_support_label = QLabel(build_support_notice_text())
        self.convert_support_label.setWordWrap(True)
        group_layout.addWidget(self.convert_support_label, 2, 0, 1, 4)
        self.convert_button = QPushButton("开始转换")
        self.convert_button.clicked.connect(self.start_convert)
        group_layout.addWidget(self.convert_button, 3, 0, 1, 4)
        layout.addWidget(group)
        layout.addStretch(1)

    def setup_rename_tab(self):
        layout = QHBoxLayout(self.rename_tab)
        layout.setSpacing(10)

        left_group = QGroupBox("批量重命名")
        left_layout = QVBoxLayout(left_group)
        folder_row = QHBoxLayout()
        self.rename_folder_edit = QLineEdit()
        rename_browse_button = QPushButton("浏览")
        rename_browse_button.clicked.connect(self.rename_browse_folder)
        rename_open_button = QPushButton("打开")
        rename_open_button.clicked.connect(lambda: self.open_folder(self.rename_folder_edit.text()))
        folder_row.addWidget(self.rename_folder_edit, 1)
        folder_row.addWidget(rename_browse_button)
        folder_row.addWidget(rename_open_button)
        left_layout.addLayout(folder_row)

        refresh_button = QPushButton("刷新文件列表")
        refresh_button.clicked.connect(self.rename_refresh_files)
        left_layout.addWidget(refresh_button)

        left_layout.addWidget(QLabel("AI 提示词"))
        self.rename_prompt_edit = QTextEdit()
        self.rename_prompt_edit.setPlainText(
            "你是一个漫画文件名分析专家，擅长识别美漫的标题、期号和年份。"
            "请将输入的文件名分析为标准格式：'漫画标题 #期号 (年份).扩展名'。"
            "只返回分析后的文件名，不要包含其他内容。"
        )
        left_layout.addWidget(self.rename_prompt_edit, 1)

        self.rename_api_hint_label = QLabel("AI 接口 Key、地址和模型请到“设置”页配置。")
        self.rename_api_hint_label.setWordWrap(True)
        left_layout.addWidget(self.rename_api_hint_label)
        open_settings_button = QPushButton("打开设置")
        open_settings_button.clicked.connect(lambda: self.switch_tab("settings"))
        left_layout.addWidget(open_settings_button)

        self.rename_include_folder_checkbox = QCheckBox("包含文件夹名作为参考")
        self.rename_include_folder_checkbox.setChecked(True)
        left_layout.addWidget(self.rename_include_folder_checkbox)

        self.rename_analyze_button = QPushButton("AI 分析文件名")
        self.rename_analyze_button.clicked.connect(self.rename_analyze_with_ai)
        self.rename_execute_button = QPushButton("执行批量重命名")
        self.rename_execute_button.clicked.connect(self.rename_execute_rename)
        left_layout.addWidget(self.rename_analyze_button)
        left_layout.addWidget(self.rename_execute_button)
        left_layout.addStretch(1)
        layout.addWidget(left_group, 0)

        right_group = QGroupBox("文件预览")
        right_layout = QVBoxLayout(right_group)
        self.rename_table = QTableWidget(0, 2)
        self.rename_table.setHorizontalHeaderLabels(["原文件名", "新文件名"])
        self.rename_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.rename_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.rename_table.verticalHeader().setVisible(False)
        self.rename_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        right_layout.addWidget(self.rename_table)
        layout.addWidget(right_group, 1)

    def setup_reader_library_tab(self):
        layout = QVBoxLayout(self.reader_library_tab)
        layout.setSpacing(10)

        intro_group = QGroupBox("漫画库")
        intro_layout = QVBoxLayout(intro_group)
        intro_text = QLabel(
            "这里专门负责扫描和整理本地漫画。先选目录或单个文件，再从列表里挑一部进入阅读器，结构会比把库和阅读区堆在一起更清晰。"
        )
        intro_text.setWordWrap(True)
        intro_layout.addWidget(intro_text)

        source_row = QHBoxLayout()
        self.reader_source_edit = QLineEdit()
        self.reader_source_edit.setPlaceholderText("选择漫画目录或单个 CBZ / ZIP / CBR / RAR / 7z / PDF 文件")
        browse_dir_button = QPushButton("浏览目录")
        browse_dir_button.clicked.connect(self.browse_reader_library_dir)
        browse_file_button = QPushButton("选择文件")
        browse_file_button.clicked.connect(self.browse_reader_library_file)
        refresh_button = QPushButton("刷新")
        refresh_button.clicked.connect(self.refresh_reader_library)
        source_row.addWidget(self.reader_source_edit, 1)
        source_row.addWidget(browse_dir_button)
        source_row.addWidget(browse_file_button)
        source_row.addWidget(refresh_button)
        intro_layout.addLayout(source_row)
        layout.addWidget(intro_group)

        self.reader_left_panel = QWidget()
        left_layout = QVBoxLayout(self.reader_left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)

        source_group = QGroupBox("漫画列表")
        source_layout = QVBoxLayout(source_group)
        self.reader_library_list = QListWidget()
        self.reader_library_list.itemSelectionChanged.connect(self.on_reader_selection_changed)
        self.reader_library_list.itemDoubleClicked.connect(lambda _item: self.open_selected_reader_comic())
        source_layout.addWidget(self.reader_library_list, 1)
        file_actions = QHBoxLayout()
        self.reader_open_button = QPushButton("进入阅读器")
        self.reader_open_button.clicked.connect(self.open_selected_reader_comic)
        self.reader_open_file_button = QPushButton("打开源文件")
        self.reader_open_file_button.clicked.connect(self.open_selected_reader_item)
        self.reader_open_folder_button = QPushButton("打开所在目录")
        self.reader_open_folder_button.clicked.connect(self.open_selected_reader_parent)
        file_actions.addWidget(self.reader_open_button)
        file_actions.addWidget(self.reader_open_file_button)
        file_actions.addWidget(self.reader_open_folder_button)
        source_layout.addLayout(file_actions)
        left_layout.addWidget(source_group, 2)

        info_group = QGroupBox("文件信息")
        info_layout = QVBoxLayout(info_group)
        self.reader_details_label = QLabel("漫画阅读器")
        self.reader_details_label.setStyleSheet("font-size: 16px; font-weight: 600;")
        self.reader_info_text = QPlainTextEdit()
        self.reader_info_text.setReadOnly(True)
        info_layout.addWidget(self.reader_details_label)
        info_layout.addWidget(self.reader_info_text)
        left_layout.addWidget(info_group, 1)

        layout.addWidget(self.reader_left_panel, 1)

        self.update_reader_details(None)

    def setup_reader_view_tab(self):
        layout = QVBoxLayout(self.reader_view_tab)
        layout.setSpacing(10)

        self.reader_header_group = QGroupBox("阅读器")
        header_layout = QGridLayout(self.reader_header_group)
        self.reader_hint_label = QLabel(
            "阅读页只保留翻页、缩放和预览区域。漫画选择与文件详情已经移到“漫画库”标签页，阅读时会更专注。"
        )
        self.reader_hint_label.setWordWrap(True)
        header_layout.addWidget(self.reader_hint_label, 0, 0, 1, 4)
        open_library_button = QPushButton("打开漫画库")
        open_library_button.clicked.connect(lambda: self.switch_tab("reader_library"))
        self.reader_focus_button = QPushButton("专注阅读")
        self.reader_focus_button.clicked.connect(self.toggle_reader_focus_mode)
        self.reader_fullscreen_button = QPushButton("全屏阅读")
        self.reader_fullscreen_button.clicked.connect(self.toggle_reader_fullscreen_mode)
        header_layout.addWidget(open_library_button, 1, 0)
        header_layout.addWidget(self.reader_focus_button, 1, 1)
        header_layout.addWidget(self.reader_fullscreen_button, 1, 2)
        layout.addWidget(self.reader_header_group)

        self.reader_right_panel = QWidget()
        right_layout = QVBoxLayout(self.reader_right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)

        self.reader_page_group = QGroupBox("阅读控制")
        page_layout = QHBoxLayout(self.reader_page_group)
        self.reader_first_button = QPushButton("首页")
        self.reader_first_button.clicked.connect(lambda: self.set_reader_page(0))
        self.reader_prev_button = QPushButton("上一页")
        self.reader_prev_button.clicked.connect(lambda: self.change_reader_page(-1))
        self.reader_page_spin = QSpinBox()
        self.reader_page_spin.setMinimum(1)
        self.reader_page_spin.setMaximum(1)
        self.reader_jump_button = QPushButton("跳转")
        self.reader_jump_button.clicked.connect(self.jump_reader_page)
        self.reader_page_total_label = QLabel("/ 0")
        self.reader_next_button = QPushButton("下一页")
        self.reader_next_button.clicked.connect(lambda: self.change_reader_page(1))
        self.reader_last_button = QPushButton("末页")
        self.reader_last_button.clicked.connect(self.go_to_last_reader_page)
        page_layout.addWidget(self.reader_first_button)
        page_layout.addWidget(self.reader_prev_button)
        page_layout.addWidget(QLabel("页码"))
        page_layout.addWidget(self.reader_page_spin)
        page_layout.addWidget(self.reader_jump_button)
        page_layout.addWidget(self.reader_page_total_label)
        page_layout.addStretch(1)
        page_layout.addWidget(self.reader_next_button)
        page_layout.addWidget(self.reader_last_button)
        right_layout.addWidget(self.reader_page_group)

        self.reader_zoom_group = QGroupBox("缩放")
        zoom_layout = QHBoxLayout(self.reader_zoom_group)
        self.reader_zoom_mode_combo = QComboBox()
        self.reader_zoom_mode_combo.addItems(list(READER_ZOOM_MODE_VALUES.keys()))
        self.reader_zoom_mode_combo.currentTextChanged.connect(
            lambda label: self.set_reader_zoom_mode(self.get_reader_zoom_mode_value(label), reset_scroll=True)
        )
        self.reader_zoom_out_button = QPushButton("缩小")
        self.reader_zoom_out_button.clicked.connect(lambda: self.adjust_reader_zoom(-READER_ZOOM_STEP))
        self.reader_zoom_in_button = QPushButton("放大")
        self.reader_zoom_in_button.clicked.connect(lambda: self.adjust_reader_zoom(READER_ZOOM_STEP))
        self.reader_zoom_reset_button = QPushButton("100%")
        self.reader_zoom_reset_button.clicked.connect(self.reset_reader_zoom)
        self.reader_zoom_value_label = QLabel("100%")
        zoom_layout.addWidget(QLabel("模式"))
        zoom_layout.addWidget(self.reader_zoom_mode_combo)
        zoom_layout.addWidget(self.reader_zoom_out_button)
        zoom_layout.addWidget(self.reader_zoom_in_button)
        zoom_layout.addWidget(self.reader_zoom_reset_button)
        zoom_layout.addStretch(1)
        zoom_layout.addWidget(self.reader_zoom_value_label)
        right_layout.addWidget(self.reader_zoom_group)

        self.reader_scroll_area = ReaderScrollArea()
        self.reader_scroll_area.setWidgetResizable(True)
        self.reader_scroll_area.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.reader_scroll_area.resized.connect(lambda: self.schedule_reader_render(invalidate=True))
        self.reader_scroll_area.boundaryPageRequested.connect(self.change_reader_page)
        self.reader_scroll_area.doubleClicked.connect(self.toggle_reader_fullscreen_mode)
        self.reader_scroll_area.verticalScrollBar().valueChanged.connect(self.schedule_reader_scroll_save)
        self.reader_scroll_area.horizontalScrollBar().valueChanged.connect(self.schedule_reader_scroll_save)

        self.reader_canvas = QWidget()
        canvas_layout = QVBoxLayout(self.reader_canvas)
        canvas_layout.setContentsMargins(12, 12, 12, 12)
        canvas_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.reader_image_label = QLabel("从“漫画库”标签页选择漫画后即可在这里翻页阅读")
        self.reader_image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.reader_image_label.setWordWrap(True)
        canvas_layout.addWidget(self.reader_image_label, 0, Qt.AlignmentFlag.AlignCenter)
        self.reader_scroll_area.setWidget(self.reader_canvas)
        right_layout.addWidget(self.reader_scroll_area, 1)

        layout.addWidget(self.reader_right_panel, 1)

        self.reader_page_group.setVisible(not self.reader_focus_mode)
        self.reader_zoom_group.setVisible(not self.reader_focus_mode)
        self.update_reader_page_controls()
        self.update_reader_zoom_controls()
        self.update_reader_focus_button()
        self.update_reader_fullscreen_button()

    def setup_logs_tab(self):
        layout = QVBoxLayout(self.logs_tab)
        layout.setSpacing(10)

        summary_group = QGroupBox("日志概览")
        summary_layout = QFormLayout(summary_group)
        self.logs_file_label = QLabel(str(log_filename))
        self.logs_file_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.logs_latest_error_label = QLabel(self._latest_error_text)
        self.logs_latest_error_label.setWordWrap(True)
        summary_layout.addRow("当前日志文件", self.logs_file_label)
        summary_layout.addRow("最近错误", self.logs_latest_error_label)
        layout.addWidget(summary_group)

        actions = QHBoxLayout()
        open_log_file_button = QPushButton("打开日志文件")
        open_log_file_button.clicked.connect(lambda: open_path(log_filename))
        open_log_dir_button = QPushButton("打开日志目录")
        open_log_dir_button.clicked.connect(lambda: self.open_folder(Path(log_filename).parent))
        reload_button = QPushButton("重新载入")
        reload_button.clicked.connect(self.load_recent_log_tail)
        clear_button = QPushButton("清空视图")
        clear_button.clicked.connect(lambda: self.logs_text_edit.setPlainText(""))
        actions.addWidget(open_log_file_button)
        actions.addWidget(open_log_dir_button)
        actions.addWidget(reload_button)
        actions.addWidget(clear_button)
        actions.addStretch(1)
        layout.addLayout(actions)

        self.logs_text_edit = QPlainTextEdit()
        self.logs_text_edit.setReadOnly(True)
        self.logs_text_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self.logs_text_edit, 1)

    def setup_settings_tab(self):
        layout = QVBoxLayout(self.settings_tab)
        layout.setSpacing(10)

        appearance_group = QGroupBox("外观与阅读")
        appearance_layout = QFormLayout(appearance_group)
        self.settings_appearance_combo = QComboBox()
        self.settings_appearance_combo.addItems(["Light", "Dark", "System"])
        self.settings_reader_fullscreen_combo = QComboBox()
        self.settings_reader_fullscreen_combo.addItems(list(WINDOWS_READER_FULLSCREEN_MODE_VALUES.keys()))
        self.settings_reader_fullscreen_combo.currentTextChanged.connect(lambda _text: self.refresh_settings_fullscreen_hint())
        self.settings_fullscreen_hint_label = QLabel()
        self.settings_fullscreen_hint_label.setWordWrap(True)
        appearance_layout.addRow("外观模式", self.settings_appearance_combo)
        appearance_layout.addRow("Windows 全屏策略", self.settings_reader_fullscreen_combo)
        appearance_layout.addRow("模式说明", self.settings_fullscreen_hint_label)
        layout.addWidget(appearance_group)

        api_group = QGroupBox("AI 重命名接口")
        api_layout = QFormLayout(api_group)
        self.settings_api_key_edit = QLineEdit()
        self.settings_api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.settings_show_api_key_checkbox = QCheckBox("显示 Key")
        self.settings_show_api_key_checkbox.toggled.connect(
            lambda checked: self.settings_api_key_edit.setEchoMode(
                QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
            )
        )
        self.settings_api_key_edit.textChanged.connect(lambda _text: self.refresh_settings_api_status_label())
        api_key_row = QWidget()
        api_key_layout = QHBoxLayout(api_key_row)
        api_key_layout.setContentsMargins(0, 0, 0, 0)
        api_key_layout.addWidget(self.settings_api_key_edit, 1)
        api_key_layout.addWidget(self.settings_show_api_key_checkbox)
        self.settings_api_url_edit = QLineEdit()
        self.settings_api_model_edit = QLineEdit()
        self.settings_api_timeout_spin = QSpinBox()
        self.settings_api_timeout_spin.setRange(5, 300)
        self.settings_api_status_label = QLabel()
        self.settings_api_status_label.setWordWrap(True)
        api_layout.addRow("API Key", api_key_row)
        api_layout.addRow("API 地址", self.settings_api_url_edit)
        api_layout.addRow("模型名称", self.settings_api_model_edit)
        api_layout.addRow("超时（秒）", self.settings_api_timeout_spin)
        api_layout.addRow("当前状态", self.settings_api_status_label)
        layout.addWidget(api_group)

        status_row = QHBoxLayout()
        self.settings_status_label = QLabel("修改后会写入本地 .gui_state.json。")
        save_button = QPushButton("保存设置")
        save_button.clicked.connect(self.save_settings)
        reset_button = QPushButton("恢复默认")
        reset_button.clicked.connect(self.reset_settings)
        status_row.addWidget(self.settings_status_label, 1)
        status_row.addWidget(save_button)
        status_row.addWidget(reset_button)
        layout.addLayout(status_row)
        layout.addStretch(1)

    def get_tab_index(self, name):
        normalized_name = str(name or "").strip()
        alias_map = {
            "reader": "reader_view",
            "library": "reader_library",
        }
        try:
            return self.TAB_NAMES.index(alias_map.get(normalized_name, normalized_name))
        except ValueError:
            return 0

    def switch_tab(self, name):
        self.tabs.setCurrentIndex(self.get_tab_index(name))

    def on_tab_changed(self, index):
        if not self._ui_ready:
            return
        target_name = self.TAB_NAMES[index] if 0 <= index < len(self.TAB_NAMES) else "home"
        if target_name != "reader_view" and self.reader_fullscreen_active:
            self.set_reader_fullscreen_mode(False)
        if target_name == "reader_view":
            self.schedule_reader_render(invalidate=False)
        self.persist_gui_state_snapshot()

    def load_recent_log_tail(self):
        log_path = Path(log_filename)
        if not log_path.exists():
            return
        try:
            lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return
        self.logs_text_edit.setPlainText("\n".join(lines[-600:]))
        cursor = self.logs_text_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.logs_text_edit.setTextCursor(cursor)
        if self._pending_log_lines:
            pending = self._pending_log_lines[:]
            self._pending_log_lines = []
            for message in pending:
                self.append_log(message)

    def append_log(self, message):
        text = str(message or "").rstrip()
        if not text:
            return
        if not hasattr(self, "logs_text_edit"):
            self._pending_log_lines.append(text)
            return
        self.logs_text_edit.appendPlainText(text)
        cursor = self.logs_text_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.logs_text_edit.setTextCursor(cursor)

    def set_latest_error_text(self, message=None):
        self._latest_error_text = str(message or "").strip() or "暂无错误"
        if hasattr(self, "logs_latest_error_label"):
            self.logs_latest_error_label.setText(self._latest_error_text)

    def log(self, message, level="info"):
        clean_message = str(message or "").strip()
        if not clean_message:
            return
        getattr(main_logger, str(level or "info").lower(), main_logger.info)(clean_message)

    def set_status(self, message):
        self.status_label.setText(str(message or "准备就绪"))

    def set_progress_busy(self, enabled):
        if enabled:
            self.status_progress_bar.setRange(0, 0)
        else:
            self.status_progress_bar.setRange(0, 100)

    def set_progress_value(self, value):
        self.set_progress_busy(False)
        try:
            progress = max(0, min(100, int(round(float(value)))))
        except (TypeError, ValueError):
            progress = 0
        self.status_progress_bar.setValue(progress)

    def reset_progress(self):
        self.set_progress_busy(False)
        self.status_progress_bar.setValue(0)

    def prune_finished_threads(self):
        self._threads = [thread for thread in self._threads if thread.is_alive()]

    def is_any_task_running(self):
        self.prune_finished_threads()
        return bool(self._threads)

    def run_background(self, task_name, worker, on_result=None, on_error=None, on_finished=None, on_progress=None, on_info=None):
        signals = TaskSignals()

        def handle_progress(value):
            if on_progress:
                on_progress(value)
            else:
                self.set_progress_value(value)

        def handle_info(message):
            if on_info:
                on_info(message)
            else:
                self.set_status(message)
                self.log(message)

        def handle_error(message):
            clean_message = str(message or "").strip()
            if clean_message:
                self.set_latest_error_text(clean_message)
                self.set_status(clean_message)
                self.log(clean_message, level="error")
            if on_error:
                on_error(clean_message)

        def handle_finished():
            self.prune_finished_threads()
            if on_finished:
                on_finished()

        signals.progress.connect(handle_progress)
        signals.info.connect(handle_info)
        signals.error.connect(handle_error)
        if on_result:
            signals.result.connect(on_result)
        signals.finished.connect(handle_finished)

        def runner():
            try:
                worker(signals)
            except Exception as exc:
                signals.error.emit(f"{task_name} 失败: {exc}")
            finally:
                signals.finished.emit()

        thread = threading.Thread(target=runner, daemon=True, name=task_name)
        self._threads.append(thread)
        thread.start()
        return thread

    def open_folder(self, folder_path):
        target_path = Path(str(folder_path or "").strip()).expanduser()
        if not target_path.exists():
            QMessageBox.warning(self, "路径不存在", f"找不到路径：\n{target_path}")
            return
        if not open_path(target_path):
            QMessageBox.warning(self, "打开失败", f"无法打开路径：\n{target_path}")

    def apply_appearance_mode(self, mode, persist=True):
        self.appearance_mode = str(mode or DEFAULT_APPEARANCE_MODE).strip() or DEFAULT_APPEARANCE_MODE
        app = QApplication.instance()
        if app is None:
            return
        dark_mode = self.appearance_mode == "Dark"
        app.setPalette(create_dark_palette() if dark_mode else self.default_palette)
        app.setStyleSheet(build_app_stylesheet(dark_mode))
        if hasattr(self, "settings_appearance_combo"):
            self.settings_appearance_combo.setCurrentText(self.appearance_mode)
        if persist:
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
        if not hasattr(self, "settings_fullscreen_hint_label"):
            return
        mode = self.get_windows_reader_fullscreen_mode_value(self.settings_reader_fullscreen_combo.currentText())
        if os.name != "nt":
            hint_text = "当前系统不是 Windows，此选项主要用于兼容保存；阅读器仍会使用标准全屏行为。"
        elif mode == "exclusive":
            hint_text = "真全屏会调用 Qt 的独占全屏，通常会隐藏任务栏，更适合沉浸阅读。"
        else:
            hint_text = "顺滑全屏会优先使用最大化，切换更轻、更适合频繁进出全屏。"
        self.settings_fullscreen_hint_label.setText(hint_text)

    def refresh_settings_api_status_label(self):
        if not hasattr(self, "settings_api_status_label"):
            return
        current_key = self.settings_api_key_edit.text().strip() if hasattr(self, "settings_api_key_edit") else ""
        if current_key:
            status = "当前会优先使用设置页中的 API Key。"
        elif ENV_DEEPSEEK_API_KEY:
            status = "设置页未填写 API Key，运行时会回退使用环境变量 DEEPSEEK_API_KEY。"
        else:
            status = "当前还没有可用的 API Key，使用 AI 重命名前请先填写。"
        self.settings_api_status_label.setText(status)
        if hasattr(self, "rename_api_hint_label"):
            self.rename_api_hint_label.setText(
                "AI 接口已配置，可以直接分析文件名。"
                if current_key or ENV_DEEPSEEK_API_KEY
                else "AI 接口 Key、地址和模型请到“设置”页配置。"
            )

    def refresh_settings_labels(self):
        self.refresh_settings_fullscreen_hint()
        self.refresh_settings_api_status_label()
        self.update_reader_focus_button()
        self.update_reader_fullscreen_button()
        self.convert_support_label.setText(build_support_notice_text())

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

    def save_settings(self):
        appearance_mode = self.settings_appearance_combo.currentText().strip() or DEFAULT_APPEARANCE_MODE
        fullscreen_mode = self.get_windows_reader_fullscreen_mode_value(self.settings_reader_fullscreen_combo.currentText())
        self.reader_windows_fullscreen_mode = fullscreen_mode
        self.rename_api_key = self.settings_api_key_edit.text().strip()
        self.rename_api_url = self.settings_api_url_edit.text().strip() or DEFAULT_RENAME_API_URL
        self.rename_api_model = self.settings_api_model_edit.text().strip() or DEFAULT_RENAME_API_MODEL
        self.rename_api_timeout = self.settings_api_timeout_spin.value()
        self.apply_appearance_mode(appearance_mode, persist=False)
        self.refresh_settings_labels()
        self.settings_status_label.setText("设置已保存")
        self.persist_gui_state_snapshot()
        self.log(
            f"已保存设置：外观 {self.appearance_mode} / Windows 全屏 {self.get_windows_reader_fullscreen_mode_label(self.reader_windows_fullscreen_mode)} / AI 模型 {self.rename_api_model}"
        )

    def reset_settings(self):
        self.settings_appearance_combo.setCurrentText(DEFAULT_APPEARANCE_MODE)
        self.settings_reader_fullscreen_combo.setCurrentText(
            self.get_windows_reader_fullscreen_mode_label(DEFAULT_WINDOWS_READER_FULLSCREEN_MODE)
        )
        self.settings_api_key_edit.setText("")
        self.settings_api_url_edit.setText(DEFAULT_RENAME_API_URL)
        self.settings_api_model_edit.setText(DEFAULT_RENAME_API_MODEL)
        self.settings_api_timeout_spin.setValue(DEFAULT_RENAME_API_TIMEOUT)
        self.settings_status_label.setText("已恢复默认设置，记得点“保存设置”。")
        self.refresh_settings_labels()

    def handle_escape_shortcut(self):
        if self.tabs.currentIndex() != self.get_tab_index("reader_view"):
            return
        if self.reader_fullscreen_active:
            self.set_reader_fullscreen_mode(False)
            return
        if self.reader_focus_mode:
            self.set_reader_focus_mode(False)

    def update_supported_sites_summary(self):
        self.comic_dl_supported_sites_text.setPlainText(self.comic_dl_downloader.get_supported_sites_summary())

    def update_comic_dl_site_status(self):
        url = self.comic_dl_url_edit.text().strip()
        if not url:
            self.comic_dl_site_status_label.setText("等待输入 URL")
            return
        site_info = self.comic_dl_downloader.describe_site(url)
        if not site_info:
            self.comic_dl_site_status_label.setText("未识别到匹配模块，请确认链接域名是否受支持。")
            return
        domains = ", ".join(site_info["domains"]) if site_info["domains"] else site_info["key"]
        browser_text = "是" if site_info["requires_browser"] else "否"
        self.comic_dl_site_status_label.setText(
            "\n".join(
                [
                    f"已识别为 {site_info['display_name']}",
                    f"域名: {domains}",
                    f"当前并发: {site_info['max_workers']}",
                    f"当前重试: {site_info['max_retries']}",
                    f"下载间隔: {site_info['download_delay']:.2f}s",
                    f"请求超时: {site_info['request_timeout']:.1f}s",
                    f"浏览器辅助: {browser_text}",
                    f"备注: {site_info['notes'] or '无'}",
                ]
            )
        )

    def browse_comic_dl_save_dir(self):
        directory = QFileDialog.getExistingDirectory(self, "选择保存目录", self.comic_dl_save_dir_edit.text().strip())
        if directory:
            self.comic_dl_save_dir_edit.setText(directory)

    def fetch_comic_info(self):
        url = self.comic_dl_url_edit.text().strip()
        if not url:
            QMessageBox.warning(self, "缺少链接", "请输入漫画链接。")
            return
        self.update_comic_dl_site_status()
        self.comic_dl_fetch_button.setEnabled(False)
        self.set_progress_busy(True)
        self.set_status("正在获取漫画信息...")
        self.log(f"正在获取漫画信息: {url}")

        def worker(signals):
            parser = None
            try:
                parser = self.comic_dl_downloader.get_parser(url)
                if not parser:
                    raise ValueError("不支持的网站，详情见站点信息。")
                comic_title, chapter_links = parser.get_comic_info(url)
                if not comic_title:
                    raise ValueError("无法获取漫画信息。")
                signals.result.emit((comic_title, chapter_links))
            except Exception as exc:
                signals.error.emit(f"获取信息失败: {exc}")
            finally:
                close_method = getattr(parser, "close", None)
                if callable(close_method):
                    try:
                        close_method()
                    except Exception:
                        pass

        def on_result(payload):
            comic_title, chapter_links = payload
            self.comic_title = comic_title
            self.chapter_data = list(chapter_links or [])
            self.comic_dl_chapter_list.clear()
            for chapter_name, _chapter_url in self.chapter_data:
                self.comic_dl_chapter_list.addItem(chapter_name)
            self.set_status(f"已读取《{comic_title}》共 {len(self.chapter_data)} 个章节")
            self.log(f"已获取漫画信息: {comic_title} / {len(self.chapter_data)} 个章节")

        def on_error(message):
            QMessageBox.warning(self, "获取失败", message)

        def on_finished():
            self.comic_dl_fetch_button.setEnabled(True)
            self.set_progress_busy(False)

        self.run_background("fetch-comic-info", worker, on_result=on_result, on_error=on_error, on_finished=on_finished)

    def start_comic_download(self):
        url = self.comic_dl_url_edit.text().strip()
        if not url:
            QMessageBox.warning(self, "缺少链接", "请输入漫画链接。")
            return
        selected_items = self.comic_dl_chapter_list.selectedIndexes()
        if not selected_items:
            QMessageBox.warning(self, "未选择章节", "请选择要下载的章节。")
            return
        save_dir = self.comic_dl_save_dir_edit.text().strip()
        if not save_dir:
            QMessageBox.warning(self, "缺少目录", "请选择保存目录。")
            return
        chapter_links = []
        for index in selected_items:
            row = index.row()
            if 0 <= row < len(self.chapter_data):
                chapter_links.append(self.chapter_data[row])
        if not chapter_links:
            QMessageBox.warning(self, "无法下载", "当前选择里没有有效章节。")
            return

        save_path = Path(save_dir).expanduser()
        save_path.mkdir(parents=True, exist_ok=True)
        self.comic_dl_downloader.set_base_dir(str(save_path))
        self.is_cancelled = False
        self.comic_dl_download_button.setEnabled(False)
        self.comic_dl_cancel_button.setEnabled(True)
        self.reset_progress()
        self.set_status("正在下载章节...")
        self.log(f"开始 Comic-DL 下载，共 {len(chapter_links)} 个章节")

        def worker(signals):
            parser = None
            stopped_due_to_failure = False
            try:
                parser = self.comic_dl_downloader.get_parser(url)
                if not parser:
                    raise ValueError("不支持的网站，详情见站点信息。")
                total_chapters = len(chapter_links)
                for i, (chapter_name, chapter_url) in enumerate(chapter_links):
                    if self.is_cancelled:
                        signals.info.emit("已取消 Comic-DL 下载，当前章节结束后停止。")
                        break
                    signals.progress.emit((i / total_chapters) * 100)
                    signals.info.emit(f"正在下载章节 {i + 1}/{total_chapters}: {chapter_name}")
                    resolved_url = self.comic_dl_downloader.resolve_chapter_url(url, chapter_url)

                    def chapter_progress_callback(message):
                        if isinstance(message, str) and "下载图片" in message:
                            match = re.search(r"(\d+)/(\d+)", message)
                            if match:
                                current, total = map(int, match.groups())
                                chapter_progress = (current / total) * (100 / total_chapters)
                                total_progress = (i / total_chapters) * 100 + chapter_progress
                                signals.progress.emit(total_progress)
                        signals.info.emit(str(message))

                    result = self.comic_dl_downloader.download_chapter(
                        self.comic_title or "Comic",
                        chapter_name,
                        resolved_url,
                        parser,
                        chapter_progress_callback,
                    )
                    if result:
                        signals.info.emit(f"章节 {chapter_name} 下载完成")
                    else:
                        signals.error.emit(f"章节 {chapter_name} 下载失败")
                        if self.comic_dl_downloader.get_default_chapter_failure_policy(resolved_url) == "stop":
                            stopped_due_to_failure = True
                            signals.info.emit("站点策略要求在章节失败后停止剩余下载。")
                            break
                if not self.is_cancelled and not stopped_due_to_failure:
                    signals.progress.emit(100)
                    signals.info.emit("所有章节下载完成")
            except Exception as exc:
                signals.error.emit(f"下载失败: {exc}")
            finally:
                close_method = getattr(parser, "close", None)
                if callable(close_method):
                    try:
                        close_method()
                    except Exception:
                        pass

        def on_finished():
            self.comic_dl_download_button.setEnabled(True)
            self.comic_dl_cancel_button.setEnabled(False)

        self.run_background("comic-dl-download", worker, on_finished=on_finished)

    def cancel_comic_download(self):
        self.is_cancelled = True
        self.set_status("正在请求停止 Comic-DL 下载...")
        self.log("收到 Comic-DL 取消请求。")

    def refresh_getcomics_history_menu(self):
        self.is_updating_getcomics_history_menu = True
        self.getcomics_recent_combo.clear()
        if self.getcomics_recent_searches:
            self.getcomics_recent_combo.addItem("最近搜索")
            for item in self.getcomics_recent_searches:
                self.getcomics_recent_combo.addItem(build_getcomics_history_label(item), item)
            self.getcomics_clear_history_button.setEnabled(True)
        else:
            self.getcomics_recent_combo.addItem("最近搜索为空")
            self.getcomics_clear_history_button.setEnabled(False)
        self.getcomics_recent_combo.setCurrentIndex(0)
        self.is_updating_getcomics_history_menu = False

    def apply_recent_getcomics_search(self, index):
        if self.is_updating_getcomics_history_menu or index <= 0:
            return
        item = self.getcomics_recent_combo.itemData(index)
        if not item:
            return
        self.getcomics_query_edit.setText(str(item.get("query") or ""))
        self.getcomics_date_edit.setText(str(item.get("date") or ""))
        self.getcomics_results_combo.setCurrentText(str(item.get("results") or DEFAULT_GETCOMICS_RESULTS))
        self.persist_gui_state_snapshot()

    def clear_getcomics_history(self):
        self.getcomics_recent_searches = []
        self.refresh_getcomics_history_menu()
        self.persist_gui_state_snapshot()
        self.log("已清空 GetComics 搜索历史")

    def get_selected_getcomics_indices(self):
        return [index.row() for index in self.getcomics_results_list.selectedIndexes()]

    def get_selected_getcomics_results(self, selected_indices=None):
        if selected_indices is None:
            selected_indices = self.get_selected_getcomics_indices()
        return collect_selected_getcomics_results(self.getcomics_results_data, selected_indices)

    def get_getcomics_favorite_urls(self):
        return {url for url, _title in self.getcomics_favorites}

    def get_getcomics_queue_urls(self):
        return {url for url, _title in self.getcomics_download_queue}

    def render_getcomics_result_text(self, url, title):
        tags = []
        if url in self.get_getcomics_favorite_urls():
            tags.append("收藏")
        if url in self.get_getcomics_queue_urls():
            tags.append("队列")
        return f"{title}  [{' / '.join(tags)}]" if tags else title

    def populate_getcomics_results_list(self, visible_results):
        self.getcomics_results_data = list(visible_results or [])
        self.getcomics_results_list.clear()
        for url, title in self.getcomics_results_data:
            item = QListWidgetItem(self.render_getcomics_result_text(url, title))
            item.setData(Qt.ItemDataRole.UserRole, (url, title))
            self.getcomics_results_list.addItem(item)
        self.update_getcomics_action_states()

    def update_getcomics_page_status(self, current_page=None):
        if self.getcomics_view_mode == "favorites":
            self.getcomics_page_label.setText(f"收藏夹：{len(self.getcomics_favorites)} 项")
            return
        if self.getcomics_view_mode == "queue":
            self.getcomics_page_label.setText(f"下载队列：{len(self.getcomics_download_queue)} 项")
            return
        if current_page is None:
            current_page = self.getcomics_search_current_page
        try:
            self.getcomics_current_page = max(0, int(current_page))
        except (TypeError, ValueError):
            self.getcomics_current_page = 0
        self.getcomics_search_current_page = self.getcomics_current_page
        if self.getcomics_current_page > 0:
            label = f"当前页：第 {self.getcomics_current_page} 页"
            if self.getcomics_results_restored_from_cache and not self.getcomics_downloader:
                label += "（缓存）"
            self.getcomics_page_label.setText(label)
            self.getcomics_jump_spin.setValue(self.getcomics_current_page)
        else:
            self.getcomics_page_label.setText("当前页：未搜索")

    def update_getcomics_action_states(self):
        has_results = bool(self.getcomics_results_data)
        selected_results = self.get_selected_getcomics_results() if has_results else []
        has_selection = bool(selected_results)
        favorite_urls = self.get_getcomics_favorite_urls()
        queue_urls = self.get_getcomics_queue_urls()
        has_selected_unfavorited = any(url not in favorite_urls for url, _title in selected_results)
        has_selected_favorited = any(url in favorite_urls for url, _title in selected_results)
        has_selected_unqueued = any(url not in queue_urls for url, _title in selected_results)
        has_selected_queued = any(url in queue_urls for url, _title in selected_results)

        self.getcomics_open_button.setEnabled(has_selection)
        self.getcomics_copy_button.setEnabled(has_selection)
        self.getcomics_add_favorite_button.setEnabled(has_selected_unfavorited)
        self.getcomics_remove_favorite_button.setEnabled(has_selected_favorited)
        self.getcomics_add_queue_button.setEnabled(has_selected_unqueued)
        self.getcomics_remove_queue_button.setEnabled(has_selected_queued)
        self.getcomics_download_button.setEnabled(has_selection)
        self.getcomics_download_queue_button.setEnabled(bool(self.getcomics_download_queue))
        self.getcomics_clear_queue_button.setEnabled(bool(self.getcomics_download_queue))

        if self.getcomics_view_mode == "favorites":
            self.getcomics_toggle_favorite_button.setText("返回搜索")
            self.getcomics_toggle_favorite_button.setEnabled(True)
        else:
            self.getcomics_toggle_favorite_button.setText("查看收藏")
            self.getcomics_toggle_favorite_button.setEnabled(bool(self.getcomics_favorites))

        if self.getcomics_view_mode == "queue":
            self.getcomics_toggle_queue_button.setText("返回搜索")
            self.getcomics_toggle_queue_button.setEnabled(True)
        else:
            self.getcomics_toggle_queue_button.setText("查看队列")
            self.getcomics_toggle_queue_button.setEnabled(bool(self.getcomics_download_queue))

        can_paginate = self.getcomics_view_mode == "search" and not self.is_any_task_running()
        self.getcomics_prev_button.setEnabled(can_paginate and self.getcomics_current_page > 1 and self.getcomics_downloader is not None)
        self.getcomics_next_button.setEnabled(can_paginate and self.getcomics_current_page > 0 and self.getcomics_downloader is not None)
        self.getcomics_jump_button.setEnabled(can_paginate and self.getcomics_current_page > 0 and self.getcomics_downloader is not None)
        self.getcomics_jump_spin.setEnabled(can_paginate and self.getcomics_current_page > 0 and self.getcomics_downloader is not None)

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
        self.update_getcomics_page_status(self.getcomics_search_current_page if self.getcomics_view_mode == "search" else 0)
        self.update_getcomics_action_states()
        if persist:
            self.persist_gui_state_snapshot()

    def toggle_getcomics_view_mode(self):
        if self.getcomics_view_mode == "favorites":
            self.set_getcomics_view_mode("search")
            return
        if not self.getcomics_favorites:
            QMessageBox.information(self, "收藏为空", "收藏夹还是空的，先从搜索结果里添加一些吧。")
            return
        self.set_getcomics_view_mode("favorites")

    def toggle_getcomics_queue_view(self):
        if self.getcomics_view_mode == "queue":
            self.set_getcomics_view_mode("search")
            return
        if not self.getcomics_download_queue:
            QMessageBox.information(self, "队列为空", "下载队列还是空的，先把结果加入队列吧。")
            return
        self.set_getcomics_view_mode("queue")

    def add_selected_getcomics_to_favorites(self):
        selected_results = self.get_selected_getcomics_results()
        if not selected_results:
            QMessageBox.warning(self, "未选择结果", "请先选择漫画结果。")
            return
        before_urls = self.get_getcomics_favorite_urls()
        self.getcomics_favorites = upsert_getcomics_results(self.getcomics_favorites, selected_results)
        added_count = len(self.get_getcomics_favorite_urls() - before_urls)
        if added_count <= 0:
            self.set_status("所选结果已在收藏夹中")
            self.update_getcomics_action_states()
            return
        if self.getcomics_view_mode == "favorites":
            self.set_getcomics_view_mode("favorites", persist=False)
        else:
            self.populate_getcomics_results_list(self.getcomics_results_data)
        self.persist_gui_state_snapshot()
        self.set_status(f"已添加 {added_count} 个收藏")
        self.log(f"已添加 {added_count} 个 GetComics 结果到收藏夹")

    def remove_selected_getcomics_from_favorites(self):
        selected_results = self.get_selected_getcomics_results()
        if not selected_results:
            QMessageBox.warning(self, "未选择结果", "请先选择漫画结果。")
            return
        before_count = len(self.getcomics_favorites)
        self.getcomics_favorites = remove_getcomics_results(self.getcomics_favorites, selected_results)
        removed_count = before_count - len(self.getcomics_favorites)
        if removed_count <= 0:
            self.set_status("所选结果不在收藏夹中")
            self.update_getcomics_action_states()
            return
        if self.getcomics_view_mode == "favorites":
            self.set_getcomics_view_mode("favorites", persist=False)
        else:
            self.populate_getcomics_results_list(self.getcomics_results_data)
        self.persist_gui_state_snapshot()
        self.set_status(f"已移除 {removed_count} 个收藏")
        self.log(f"已从收藏夹移除 {removed_count} 个 GetComics 结果")

    def add_selected_getcomics_to_queue(self):
        selected_results = self.get_selected_getcomics_results()
        if not selected_results:
            QMessageBox.warning(self, "未选择结果", "请先选择漫画结果。")
            return
        before_urls = self.get_getcomics_queue_urls()
        self.getcomics_download_queue = upsert_getcomics_results(self.getcomics_download_queue, selected_results)
        added_count = len(self.get_getcomics_queue_urls() - before_urls)
        if added_count <= 0:
            self.set_status("所选结果已在下载队列中")
            self.update_getcomics_action_states()
            return
        if self.getcomics_view_mode == "queue":
            self.set_getcomics_view_mode("queue", persist=False)
        else:
            self.populate_getcomics_results_list(self.getcomics_results_data)
        self.persist_gui_state_snapshot()
        self.set_status(f"已添加 {added_count} 个到下载队列")
        self.log(f"已添加 {added_count} 个 GetComics 结果到下载队列")

    def remove_selected_getcomics_from_queue(self):
        selected_results = self.get_selected_getcomics_results()
        if not selected_results:
            QMessageBox.warning(self, "未选择结果", "请先选择漫画结果。")
            return
        before_count = len(self.getcomics_download_queue)
        self.getcomics_download_queue = remove_getcomics_results(self.getcomics_download_queue, selected_results)
        removed_count = before_count - len(self.getcomics_download_queue)
        if removed_count <= 0:
            self.set_status("所选结果不在下载队列中")
            self.update_getcomics_action_states()
            return
        if self.getcomics_view_mode == "queue":
            self.set_getcomics_view_mode("queue", persist=False)
        else:
            self.populate_getcomics_results_list(self.getcomics_results_data)
        self.persist_gui_state_snapshot()
        self.set_status(f"已移除 {removed_count} 个队列项")
        self.log(f"已从下载队列移除 {removed_count} 个 GetComics 结果")

    def clear_getcomics_queue(self):
        if not self.getcomics_download_queue:
            QMessageBox.information(self, "队列为空", "下载队列已经是空的。")
            return
        result = QMessageBox.question(self, "确认清空", f"将清空 {len(self.getcomics_download_queue)} 个队列项，是否继续？")
        if result != QMessageBox.StandardButton.Yes:
            return
        self.getcomics_download_queue = []
        if self.getcomics_view_mode == "queue":
            self.set_getcomics_view_mode("search", persist=False)
        else:
            self.populate_getcomics_results_list(self.getcomics_results_data)
        self.persist_gui_state_snapshot()
        self.set_status("已清空下载队列")
        self.log("已清空 GetComics 下载队列")

    def copy_selected_getcomics_links(self):
        selected_results = self.get_selected_getcomics_results()
        if not selected_results:
            QMessageBox.warning(self, "未选择结果", "请先选择漫画结果。")
            return
        clipboard_text = format_getcomics_results_for_clipboard(selected_results)
        if not clipboard_text:
            QMessageBox.warning(self, "复制失败", "没有可复制的链接。")
            return
        QApplication.clipboard().setText(clipboard_text)
        self.set_status(f"已复制 {len(selected_results)} 个链接")
        self.log(f"已复制 {len(selected_results)} 个 GetComics 链接到剪贴板")

    def open_selected_getcomics_results(self):
        selected_results = self.get_selected_getcomics_results()
        if not selected_results:
            QMessageBox.warning(self, "未选择结果", "请先选择漫画结果。")
            return
        if len(selected_results) > 5:
            result = QMessageBox.question(self, "确认打开", f"将打开 {len(selected_results)} 个详情页，是否继续？")
            if result != QMessageBox.StandardButton.Yes:
                return
        opened_count = 0
        for url, _title in selected_results:
            try:
                webbrowser.open_new_tab(url)
                opened_count += 1
            except Exception as exc:
                self.log(f"打开详情页失败: {url} - {exc}", level="error")
        if opened_count:
            self.set_status(f"已打开 {opened_count} 个详情页")
            self.log(f"已打开 {opened_count} 个 GetComics 详情页")

    def browse_getcomics_save_dir(self):
        directory = QFileDialog.getExistingDirectory(self, "选择保存目录", self.getcomics_save_dir_edit.text().strip())
        if directory:
            self.getcomics_save_dir_edit.setText(directory)
            self.persist_gui_state_snapshot()

    def remember_getcomics_search(self):
        self.getcomics_recent_searches = upsert_recent_getcomics_search(
            self.getcomics_recent_searches,
            {
                "query": self.getcomics_query_edit.text().strip(),
                "date": self.getcomics_date_edit.text().strip(),
                "results": self.getcomics_results_combo.currentText().strip(),
            },
        )
        self.refresh_getcomics_history_menu()

    def search_getcomics(self):
        self.start_getcomics_search(mode="new")

    def load_previous_getcomics_page(self):
        self.start_getcomics_search(mode="previous")

    def load_next_getcomics_page(self):
        self.start_getcomics_search(mode="next")

    def jump_to_getcomics_page(self):
        self.start_getcomics_search(mode="jump", target_page=self.getcomics_jump_spin.value())

    def start_getcomics_search(self, mode="new", target_page=None):
        query = self.getcomics_query_edit.text().strip()
        load_next = mode == "next"
        load_previous = mode == "previous"
        jump_to_page = mode == "jump"
        is_new_search = mode == "new"

        if not is_new_search and self.getcomics_view_mode != "search":
            QMessageBox.warning(self, "无法翻页", "当前正在查看收藏夹或队列，请先返回搜索结果。")
            return
        if not is_new_search and not self.getcomics_downloader:
            QMessageBox.warning(self, "无法翻页", "请先执行一次新的搜索。")
            return
        if load_previous and self.getcomics_current_page <= 1:
            QMessageBox.information(self, "已经到头", "已经是第一页。")
            return
        if jump_to_page and target_page is None:
            QMessageBox.warning(self, "缺少页码", "请输入目标页码。")
            return
        if is_new_search and not query:
            QMessageBox.warning(self, "缺少关键词", "请输入搜索内容。")
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
            target_page = 1
            self.getcomics_results_restored_from_cache = False
            self.getcomics_search_results_data = []
            self.getcomics_search_current_page = 0
            self.set_getcomics_view_mode("search", persist=False)
            self.log(f"正在搜索 GetComics: {query}")

        self.getcomics_search_button.setEnabled(False)
        self.getcomics_prev_button.setEnabled(False)
        self.getcomics_next_button.setEnabled(False)
        self.getcomics_jump_button.setEnabled(False)
        self.getcomics_jump_spin.setEnabled(False)
        self.set_progress_busy(True)
        self.set_status("正在搜索 GetComics...")

        date = self.getcomics_date_edit.text().strip()
        results = int(self.getcomics_results_combo.currentText().strip() or DEFAULT_GETCOMICS_RESULTS)

        def worker(signals):
            current_target_page = 1
            try:
                if not is_new_search:
                    if load_next:
                        current_target_page = max(1, int(getattr(self.getcomics_downloader, "page", 1)))
                    elif load_previous:
                        current_target_page = max(1, self.getcomics_current_page - 1)
                    elif jump_to_page:
                        current_target_page = max(1, int(target_page))
                    self.getcomics_downloader.page = current_target_page
                    self.getcomics_downloader.page_links.clear()
                    self.getcomics_downloader.comic_links.clear()
                else:
                    self.getcomics_downloader = GetComics(query, results, True, date=date or None)
                    current_target_page = 1

                async def search_async():
                    await self.getcomics_downloader.find_pages()
                    await self.getcomics_downloader.get_download_links()

                asyncio.run(search_async())
                if not self.getcomics_downloader.comic_links:
                    if not is_new_search:
                        signals.info.emit(f"第 {current_target_page} 页没有可下载结果，请继续尝试下一页或调整筛选条件。")
                    else:
                        signals.error.emit("未找到搜索结果。")
                    return
                signals.result.emit({"comic_links": dict(self.getcomics_downloader.comic_links), "page": current_target_page})
            except Exception as exc:
                signals.error.emit(f"搜索失败: {exc}")

        def on_result(payload):
            comic_links = payload["comic_links"]
            page = payload["page"]
            self.getcomics_search_results_data = list(comic_links.items())
            self.getcomics_search_current_page = page
            self.getcomics_current_page = page
            self.set_getcomics_view_mode("search", persist=False)
            self.update_getcomics_page_status(page)
            self.remember_getcomics_search()
            self.persist_gui_state_snapshot()
            self.log(f"GetComics 第 {page} 页已加载，共 {len(self.getcomics_search_results_data)} 项")

        def on_finished():
            self.set_progress_busy(False)
            self.update_getcomics_action_states()
            self.getcomics_search_button.setEnabled(True)

        self.run_background("getcomics-search", worker, on_result=on_result, on_finished=on_finished)

    def start_getcomics_download_for_results(self, selected_results, task_label="GetComics 下载完成"):
        if not selected_results:
            QMessageBox.warning(self, "未选择结果", "请选择有效的漫画结果。")
            return
        save_dir_input = self.getcomics_save_dir_edit.text().strip()
        if not save_dir_input:
            QMessageBox.warning(self, "缺少目录", "请选择保存目录。")
            return
        save_dir = Path(save_dir_input).expanduser()
        save_dir.mkdir(parents=True, exist_ok=True)

        selected_comics = {url: title for url, title in selected_results}
        self.is_getcomics_cancelled = False
        self.getcomics_download_button.setEnabled(False)
        self.getcomics_download_queue_button.setEnabled(False)
        self.getcomics_cancel_button.setEnabled(True)
        self.reset_progress()
        self.set_status("正在下载 GetComics 资源...")
        self.log(f"开始 GetComics 下载，共 {len(selected_comics)} 项")

        def worker(signals):
            try:
                def progress_callback(message):
                    if isinstance(message, tuple) and message[0] == "progress":
                        signals.progress.emit(message[1])
                    else:
                        signals.info.emit(str(message))

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
                if self.is_getcomics_cancelled:
                    signals.info.emit("已取消 GetComics 下载。")
                else:
                    signals.progress.emit(100)
                    signals.info.emit("所有漫画下载完成")
                    signals.result.emit(task_label)
            except Exception as exc:
                signals.error.emit(f"下载失败: {exc}")

        def on_result(message):
            self.log(message)
            self.set_status(message)

        def on_finished():
            self.getcomics_download_button.setEnabled(bool(self.get_selected_getcomics_results()))
            self.getcomics_download_queue_button.setEnabled(bool(self.getcomics_download_queue))
            self.getcomics_cancel_button.setEnabled(False)
            self.update_getcomics_action_states()

        self.run_background("getcomics-download", worker, on_result=on_result, on_finished=on_finished)

    def start_getcomics_download(self):
        selected_results = self.get_selected_getcomics_results()
        if not selected_results:
            QMessageBox.warning(self, "未选择结果", "请选择要下载的漫画。")
            return
        self.start_getcomics_download_for_results(selected_results, task_label="GetComics 下载完成")

    def start_getcomics_queue_download(self):
        if not self.getcomics_download_queue:
            QMessageBox.warning(self, "队列为空", "下载队列还是空的。")
            return
        self.start_getcomics_download_for_results(list(self.getcomics_download_queue), task_label="GetComics 队列下载完成")

    def cancel_getcomics_download(self):
        self.is_getcomics_cancelled = True
        self.set_status("正在请求停止 GetComics 下载...")
        self.log("收到 GetComics 取消请求。")

    def browse_convert_input_file(self):
        file_path, _selected = QFileDialog.getOpenFileName(
            self,
            "选择漫画源文件",
            "",
            "Comic Sources (*.cbz *.zip *.cbr *.rar *.cb7 *.7z *.pdf);;All Files (*.*)",
        )
        if not file_path:
            return
        self.convert_input_edit.setText(file_path)
        if not self.convert_output_edit.text().strip():
            self.convert_output_edit.setText(self._suggest_convert_output_path(file_path))

    def browse_convert_input_dir(self):
        directory = QFileDialog.getExistingDirectory(self, "选择漫画目录")
        if not directory:
            return
        self.convert_input_edit.setText(directory)
        if not self.convert_output_edit.text().strip():
            self.convert_output_edit.setText(self._suggest_convert_output_path(directory))

    def browse_convert_output(self):
        output_path, _selected = QFileDialog.getSaveFileName(
            self,
            "保存 CBZ 文件",
            self.convert_output_edit.text().strip() or "",
            "CBZ Files (*.cbz)",
        )
        if output_path:
            self.convert_output_edit.setText(output_path)

    def open_convert_output_dir(self):
        output_path = self.convert_output_edit.text().strip()
        if not output_path:
            QMessageBox.information(self, "缺少路径", "请先选择输出路径。")
            return
        self.open_folder(Path(output_path).expanduser().parent)

    def _suggest_convert_output_path(self, input_path):
        source = Path(str(input_path or "").strip()).expanduser()
        if not source.name:
            return ""
        name = source.stem if source.is_file() else source.name
        return str(source.parent / f"{name}.cbz")

    def start_convert(self):
        input_path = self.convert_input_edit.text().strip()
        output_path = self.convert_output_edit.text().strip()
        if not input_path or not output_path:
            QMessageBox.warning(self, "路径不完整", "请选择输入和输出路径。")
            return
        support_message = get_comic_source_requirement_message(input_path, action="转换")
        if support_message:
            QMessageBox.information(self, "需要额外支持", support_message)
            return

        self.convert_button.setEnabled(False)
        self.reset_progress()
        self.set_status("正在转换为 CBZ...")
        self.log(f"开始转换为 CBZ: {input_path}")

        def worker(signals):
            try:
                def progress_callback(message):
                    text = str(message)
                    if "添加图片" in text:
                        match = re.search(r"(\d+)/(\d+)", text)
                        if match:
                            current, total = map(int, match.groups())
                            signals.progress.emit((current / total) * 100)
                    signals.info.emit(text)

                result = self.comic_dl_downloader.convert_to_cbz(input_path, output_path, progress_callback)
                if result:
                    signals.progress.emit(100)
                    signals.result.emit(output_path)
                else:
                    signals.error.emit("转换失败。")
            except Exception as exc:
                signals.error.emit(f"转换失败: {exc}")

        def on_result(result_path):
            self.set_status("CBZ 转换完成")
            self.log(f"CBZ 转换完成: {result_path}")

        def on_finished():
            self.convert_button.setEnabled(True)

        self.run_background("convert-cbz", worker, on_result=on_result, on_finished=on_finished)

    def rename_browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择需要重命名的目录", self.rename_folder_edit.text().strip())
        if folder:
            self.rename_folder_edit.setText(folder)
            self.rename_refresh_files()

    def rename_refresh_files(self):
        folder = Path(self.rename_folder_edit.text().strip()).expanduser()
        if not folder.exists() or not folder.is_dir():
            self.rename_table.setRowCount(0)
            self.rename_files = []
            return
        file_names = sorted([path.name for path in folder.iterdir() if path.is_file()], key=str.casefold)
        self.rename_files = [(name, name) for name in file_names]
        self.rename_table.setRowCount(len(self.rename_files))
        for row, (original, new_name) in enumerate(self.rename_files):
            self.rename_table.setItem(row, 0, QTableWidgetItem(original))
            self.rename_table.setItem(row, 1, QTableWidgetItem(new_name))

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
            "temperature": 0.1,
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
            error_message = result.get("error", {}).get("message") or "接口没有返回可用结果。"
            raise ValueError(error_message)
        new_name = choices[0]["message"]["content"].strip().strip('"')
        if not new_name:
            raise ValueError("接口返回了空文件名。")
        if not new_name.endswith(extension):
            new_name += extension
        return new_name

    def rename_analyze_with_ai(self):
        if not self.rename_files:
            QMessageBox.information(self, "没有文件", "请先选择目录并刷新文件列表。")
            return
        try:
            self.get_rename_api_request_settings()
        except ValueError as exc:
            QMessageBox.warning(self, "缺少配置", str(exc))
            return

        custom_prompt = self.rename_prompt_edit.toPlainText().strip()
        folder_name = Path(self.rename_folder_edit.text().strip()).name if self.rename_include_folder_checkbox.isChecked() else ""
        total = len(self.rename_files)
        self.rename_analyze_button.setEnabled(False)
        self.rename_execute_button.setEnabled(False)
        self.reset_progress()
        self.set_status("正在调用 AI 分析文件名...")
        self.log(f"开始 AI 分析文件名，共 {total} 个文件")

        def worker(signals):
            for index, (original, _current_new_name) in enumerate(list(self.rename_files)):
                try:
                    signals.progress.emit((index / total) * 100)
                    signals.info.emit(f"正在分析: {original}")
                    new_name = self.rename_analyze_with_deepseek(original, custom_prompt, folder_name)
                    signals.result.emit((index, original, new_name))
                except Exception as exc:
                    signals.error.emit(f"分析失败: {original} - {exc}")
            signals.progress.emit(100)
            signals.info.emit("AI 分析完成")

        def on_result(payload):
            index, original, new_name = payload
            self.rename_files[index] = (original, new_name)
            self.rename_table.setItem(index, 0, QTableWidgetItem(original))
            self.rename_table.setItem(index, 1, QTableWidgetItem(new_name))

        def on_finished():
            self.rename_analyze_button.setEnabled(True)
            self.rename_execute_button.setEnabled(True)

        self.run_background("rename-analyze", worker, on_result=on_result, on_finished=on_finished)

    def rename_execute_rename(self):
        folder = Path(self.rename_folder_edit.text().strip()).expanduser()
        if not folder.exists() or not folder.is_dir() or not self.rename_files:
            QMessageBox.information(self, "没有可处理内容", "请先选择目录并准备重命名列表。")
            return
        total = len(self.rename_files)
        self.rename_analyze_button.setEnabled(False)
        self.rename_execute_button.setEnabled(False)
        self.reset_progress()
        self.set_status("正在执行批量重命名...")
        self.log(f"开始执行批量重命名，共 {total} 个文件")

        def worker(signals):
            renamed_count = 0
            for index, (original, new_name) in enumerate(list(self.rename_files), 1):
                signals.progress.emit((index - 1) / total * 100)
                if original == new_name:
                    continue
                source = folder / original
                target = folder / new_name
                if not source.exists():
                    signals.error.emit(f"找不到源文件，已跳过: {original}")
                    continue
                if target.exists():
                    signals.error.emit(f"目标文件已存在，已跳过: {new_name}")
                    continue
                try:
                    source.rename(target)
                    renamed_count += 1
                    signals.info.emit(f"已重命名: {original} -> {new_name}")
                except Exception as exc:
                    signals.error.emit(f"重命名失败: {original} - {exc}")
            signals.progress.emit(100)
            signals.result.emit(renamed_count)

        def on_result(renamed_count):
            self.log(f"重命名完成: {renamed_count} 个文件")
            self.set_status(f"重命名完成：{renamed_count} 个文件")

        def on_finished():
            self.rename_analyze_button.setEnabled(True)
            self.rename_execute_button.setEnabled(True)
            self.rename_refresh_files()

        self.run_background("rename-execute", worker, on_result=on_result, on_finished=on_finished)

    def show_comic_source_support_message(self, source_path, action):
        support_message = get_comic_source_requirement_message(source_path, action=action)
        if support_message:
            QMessageBox.information(self, "需要额外支持", support_message)
            return True
        return False

    def get_reader_zoom_mode_label(self, value):
        normalized_mode = normalize_reader_zoom_mode(value)
        return READER_ZOOM_MODE_LABELS.get(normalized_mode, READER_ZOOM_MODE_LABELS[DEFAULT_READER_ZOOM_MODE])

    def get_reader_zoom_mode_value(self, label):
        return READER_ZOOM_MODE_VALUES.get(str(label or "").strip(), DEFAULT_READER_ZOOM_MODE)

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
        directory = QFileDialog.getExistingDirectory(self, "选择漫画目录", self.reader_source_edit.text().strip() or self.default_getcomics_save_dir)
        if not directory:
            return
        self.refresh_reader_library(initial_path=directory)
        self.persist_gui_state_snapshot()

    def browse_reader_library_file(self):
        file_path, _selected = QFileDialog.getOpenFileName(
            self,
            "选择漫画文件",
            "",
            "Comic Files (*.cbz *.zip *.cbr *.rar *.cb7 *.7z *.pdf);;All Files (*.*)",
        )
        if not file_path:
            return
        if self.show_comic_source_support_message(file_path, "打开"):
            self.reader_source_edit.setText(file_path)
            self.reset_reader_session("当前文件需要额外支持，详情见上方提示。")
            self.persist_gui_state_snapshot()
            return
        self.refresh_reader_library(initial_path=file_path)
        self.persist_gui_state_snapshot()

    def refresh_reader_library(self, initial_path=None, select_first=True):
        if initial_path is not None:
            self.reader_source_edit.setText(str(initial_path))
        source_path = self.reader_source_edit.text().strip()
        if not source_path:
            self.reader_library_list.clear()
            self.reader_library_entries = []
            self.update_reader_details(None)
            self.reset_reader_session("请先选择漫画目录或 CBZ / ZIP / CBR / RAR / 7z / PDF 文件。")
            return
        expanded_source = str(Path(source_path).expanduser())
        self.reader_source_edit.setText(expanded_source)
        source = Path(expanded_source)
        if not source.exists():
            self.reader_library_list.clear()
            self.reader_library_entries = []
            self.update_reader_details(None)
            self.reset_reader_session("所选路径不存在，请重新选择。")
            self.set_status("所选阅读路径不存在")
            return
        if source.is_file():
            support_message = get_comic_source_requirement_message(expanded_source, action="打开")
            if support_message:
                self.reader_library_list.clear()
                self.reader_library_entries = []
                self.update_reader_details(None)
                self.reset_reader_session("当前文件需要额外支持，详情见上方提示。")
                self.set_status("当前文件缺少必要支持")
                return

        previous_path = ""
        selected_entry = self.get_selected_reader_entry()
        if selected_entry:
            previous_path = selected_entry["path"]
        elif self.reader_current_entry:
            previous_path = self.reader_current_entry["path"]

        try:
            entries = discover_comics(expanded_source)
        except Exception as exc:
            QMessageBox.warning(self, "扫描失败", f"扫描漫画文件失败：{exc}")
            return

        self.reader_library_entries = entries
        self.reader_library_list.clear()
        for entry in entries:
            kind_text = self.get_reader_entry_kind_label(entry)
            self.reader_library_list.addItem(f"{entry['name']}  [{kind_text} · {entry['page_count']} 页]")

        if not entries:
            self.update_reader_details(None)
            self.reset_reader_session("当前路径下没有找到可阅读的漫画文件。")
            self.set_status("未发现可阅读的漫画文件")
            return

        target_index = None
        for index, entry in enumerate(entries):
            if entry["path"] == previous_path:
                target_index = index
                break
        if target_index is None and select_first:
            target_index = 0

        if target_index is not None:
            self.reader_library_list.setCurrentRow(target_index)
            self.on_reader_selection_changed()
        else:
            self.update_reader_details(None)
        self.set_status(f"已加载 {len(entries)} 个本地漫画条目")

    def get_selected_reader_entry(self):
        row = self.reader_library_list.currentRow()
        if row < 0 or row >= len(self.reader_library_entries):
            return None
        return self.reader_library_entries[row]

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
        self.reader_library_list.setCurrentRow(index)
        self.on_reader_selection_changed()
        return self.reader_library_entries[index]

    def on_reader_selection_changed(self):
        entry = self.get_selected_reader_entry()
        self.update_reader_details(entry)
        self.persist_gui_state_snapshot()

    def update_reader_file_actions(self, entry=None):
        state = bool(entry)
        self.reader_open_button.setEnabled(state)
        self.reader_open_file_button.setEnabled(state)
        self.reader_open_folder_button.setEnabled(state)

    def update_reader_details(self, entry=None):
        if not entry:
            self.reader_details_label.setText("漫画阅读器")
            self.reader_info_text.setPlainText("在“漫画库”标签页里选择漫画后，可以在这里查看文件信息并进入独立阅读器。")
            self.update_reader_file_actions(None)
            return
        self.reader_details_label.setText(entry["name"])
        self.reader_info_text.setPlainText(build_reader_entry_description(entry))
        self.update_reader_file_actions(entry)

    def reset_reader_session(self, placeholder="从“漫画库”标签页选择漫画后即可在这里翻页阅读"):
        self.store_current_reader_scroll_position()
        self.reader_current_entry = None
        self.reader_current_pages = []
        self.reader_current_page_index = -1
        self.reader_source_image = None
        self.reader_image_pixmap = None
        self.reader_preview_render_key = None
        self.show_reader_placeholder(placeholder)
        self.update_reader_page_controls()
        self.update_reader_zoom_controls()

    def open_selected_reader_item(self):
        entry = self.get_selected_reader_entry()
        if not entry:
            QMessageBox.warning(self, "未选择漫画", "请先选择漫画文件。")
            return
        if not open_path(entry["path"]):
            QMessageBox.warning(self, "打开失败", f"无法打开：\n{entry['path']}")

    def open_selected_reader_parent(self):
        entry = self.get_selected_reader_entry()
        if not entry:
            QMessageBox.warning(self, "未选择漫画", "请先选择漫画文件。")
            return
        source_path = Path(entry["path"])
        self.open_folder(source_path if source_path.is_dir() else source_path.parent)

    def open_selected_reader_comic(self):
        entry = self.get_selected_reader_entry()
        if not entry:
            QMessageBox.warning(self, "未选择漫画", "请先选择漫画文件。")
            return
        if self.open_reader_entry(entry):
            self.switch_tab("reader_view")

    def open_reader_entry(self, entry, target_page=1, persist=True, announce=True):
        if not entry:
            return False
        if self.show_comic_source_support_message(entry["path"], "打开"):
            self.set_status("当前文件缺少必要支持")
            return False
        try:
            pages = list_comic_pages(entry["path"])
        except Exception as exc:
            QMessageBox.warning(self, "读取失败", f"读取漫画页失败：{exc}")
            return False
        if not pages:
            QMessageBox.warning(self, "没有内容", "当前漫画没有可读取的页面。")
            return False
        try:
            target_page_number = int(target_page)
        except (TypeError, ValueError):
            target_page_number = 1
        self.store_current_reader_scroll_position()
        self.reader_current_entry = entry
        self.reader_current_pages = pages
        self.reader_current_page_index = -1
        ok = self.set_reader_page(min(max(1, target_page_number), len(pages)) - 1, persist=persist)
        if ok and announce:
            self.log(f"已打开本地漫画: {entry['name']}")
            self.set_status(f"正在阅读: {entry['name']}")
        return ok

    def update_reader_page_controls(self):
        total_pages = len(self.reader_current_pages)
        has_pages = self.reader_current_entry is not None and total_pages > 0
        current_page = self.reader_current_page_index + 1 if has_pages else 1
        self.reader_page_total_label.setText(f"/ {total_pages}")
        self.reader_page_spin.setEnabled(has_pages)
        self.reader_page_spin.blockSignals(True)
        self.reader_page_spin.setMaximum(max(1, total_pages))
        self.reader_page_spin.setValue(max(1, current_page))
        self.reader_page_spin.blockSignals(False)
        self.reader_first_button.setEnabled(has_pages and self.reader_current_page_index > 0)
        self.reader_prev_button.setEnabled(has_pages and self.reader_current_page_index > 0)
        self.reader_next_button.setEnabled(has_pages and self.reader_current_page_index < total_pages - 1)
        self.reader_last_button.setEnabled(has_pages and self.reader_current_page_index < total_pages - 1)
        self.reader_jump_button.setEnabled(has_pages)
        self.update_reader_zoom_controls()

    def get_reader_scroll_key(self, entry=None, page_index=None):
        target_entry = entry if entry is not None else self.reader_current_entry
        target_page_index = self.reader_current_page_index if page_index is None else int(page_index)
        if not target_entry or target_page_index < 0:
            return None
        return (target_entry["path"], target_page_index)

    def get_current_reader_scroll_position(self):
        horizontal_bar = self.reader_scroll_area.horizontalScrollBar()
        vertical_bar = self.reader_scroll_area.verticalScrollBar()
        scroll_x = 0.0 if horizontal_bar.maximum() <= 0 else horizontal_bar.value() / horizontal_bar.maximum()
        scroll_y = 0.0 if vertical_bar.maximum() <= 0 else vertical_bar.value() / vertical_bar.maximum()
        return (
            normalize_reader_scroll_fraction(scroll_x),
            normalize_reader_scroll_fraction(scroll_y),
        )

    def get_reader_saved_scroll_position(self, entry=None, page_index=None):
        scroll_key = self.get_reader_scroll_key(entry=entry, page_index=page_index)
        if scroll_key is None:
            return (0.0, 0.0)
        return self.reader_scroll_positions.get(scroll_key, (0.0, 0.0))

    def store_current_reader_scroll_position(self):
        scroll_key = self.get_reader_scroll_key()
        if scroll_key is None:
            return (0.0, 0.0)
        scroll_position = self.get_current_reader_scroll_position()
        self.reader_scroll_positions[scroll_key] = scroll_position
        return scroll_position

    def apply_reader_scroll_position(self, scroll_position):
        horizontal_bar = self.reader_scroll_area.horizontalScrollBar()
        vertical_bar = self.reader_scroll_area.verticalScrollBar()
        scroll_x, scroll_y = scroll_position or (0.0, 0.0)
        horizontal_bar.setValue(round(horizontal_bar.maximum() * normalize_reader_scroll_fraction(scroll_x)) if horizontal_bar.maximum() > 0 else 0)
        vertical_bar.setValue(round(vertical_bar.maximum() * normalize_reader_scroll_fraction(scroll_y)) if vertical_bar.maximum() > 0 else 0)

    def get_reader_viewport_size(self):
        viewport = self.reader_scroll_area.viewport()
        return max(1, viewport.width() - 24), max(1, viewport.height() - 24)

    def get_reader_effective_zoom_percent(self):
        if self.reader_source_image is None:
            return clamp_reader_zoom_percent(self.reader_zoom_percent)
        viewport_size = self.get_reader_viewport_size()
        target_width, _target_height = calculate_reader_image_size(
            self.reader_source_image.size,
            viewport_size,
            zoom_mode=self.reader_zoom_mode,
            zoom_percent=self.reader_zoom_percent,
        )
        source_width = max(self.reader_source_image.size[0], 1)
        return max(1, int(round((target_width / source_width) * 100)))

    def show_reader_placeholder(self, text=None):
        placeholder = str(text or "从“漫画库”标签页选择漫画后即可在这里翻页阅读").strip()
        self.reader_image_label.clear()
        self.reader_image_label.setText(placeholder)
        self.reader_image_label.setPixmap(QPixmap())
        self.reader_image_label.setFixedSize(self.reader_scroll_area.viewport().size())
        self.reader_canvas.setMinimumSize(0, 0)

    def queue_reader_render(self, reset_scroll=False, scroll_position=None, invalidate=False):
        pending = self.reader_pending_render or ReaderRenderRequest()
        pending.reset_scroll = pending.reset_scroll or bool(reset_scroll)
        pending.invalidate = pending.invalidate or bool(invalidate)
        if pending.reset_scroll:
            pending.scroll_position = None
        elif scroll_position is not None:
            pending.scroll_position = (
                normalize_reader_scroll_fraction(scroll_position[0]),
                normalize_reader_scroll_fraction(scroll_position[1]),
            )
        self.reader_pending_render = pending

    def schedule_reader_scroll_save(self):
        if self.reader_current_entry:
            self.reader_scroll_save_timer.start(150)

    def schedule_reader_render(self, delay_ms=READER_RENDER_DELAY_MS, reset_scroll=False, scroll_position=None, invalidate=False):
        self.queue_reader_render(reset_scroll=reset_scroll, scroll_position=scroll_position, invalidate=invalidate)
        self.reader_render_timer.start(max(1, int(delay_ms or READER_RENDER_DELAY_MS)))

    def flush_reader_render(self):
        pending = self.reader_pending_render or ReaderRenderRequest()
        self.reader_pending_render = None
        if pending.invalidate:
            self.reader_preview_render_key = None
        if self.reader_source_image is None:
            self.show_reader_placeholder()
            self.update_reader_zoom_controls()
            return
        if pending.reset_scroll:
            target_scroll_position = (0.0, 0.0)
        elif pending.scroll_position is not None:
            target_scroll_position = pending.scroll_position
        else:
            target_scroll_position = self.get_current_reader_scroll_position()

        viewport_size = self.get_reader_viewport_size()
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
        if self.reader_preview_render_key == render_key and self.reader_image_pixmap is not None:
            self.apply_reader_scroll_position(target_scroll_position)
            self.update_reader_zoom_controls()
            return

        preview_image = self.reader_source_image.copy() if target_size == self.reader_source_image.size else self.reader_source_image.resize(target_size, Image.Resampling.LANCZOS)
        self.reader_image_pixmap = pil_image_to_qpixmap(preview_image)
        self.reader_image_label.setText("")
        self.reader_image_label.setPixmap(self.reader_image_pixmap)
        self.reader_image_label.setFixedSize(target_size[0], target_size[1])
        self.reader_canvas.setMinimumSize(target_size[0] + 24, target_size[1] + 24)
        self.reader_preview_render_key = render_key
        QTimer.singleShot(0, lambda: self.apply_reader_scroll_position(target_scroll_position))
        self.update_reader_zoom_controls()

    def set_reader_page(self, index, persist=True):
        if not self.reader_current_entry or not self.reader_current_pages:
            return False
        if index < 0 or index >= len(self.reader_current_pages):
            return False
        previous_page_index = self.reader_current_page_index
        current_scroll_position = self.store_current_reader_scroll_position() if previous_page_index >= 0 else (0.0, 0.0)
        page_name = self.reader_current_pages[index]
        try:
            self.reader_source_image = load_comic_page_image(self.reader_current_entry["path"], page_name)
        except Exception as exc:
            QMessageBox.warning(self, "读取失败", f"读取漫画页面失败：{exc}")
            return False
        target_scroll_position = current_scroll_position if previous_page_index == index else self.get_reader_saved_scroll_position(page_index=index)
        self.reader_current_page_index = index
        self.reader_preview_render_key = None
        self.update_reader_page_controls()
        self.schedule_reader_render(delay_ms=1, scroll_position=target_scroll_position, invalidate=True)
        self.set_status(f"正在阅读 {self.reader_current_entry['name']} - 第 {index + 1}/{len(self.reader_current_pages)} 页")
        if persist:
            self.persist_gui_state_snapshot()
        return True

    def change_reader_page(self, delta):
        if self.reader_current_page_index >= 0:
            self.set_reader_page(self.reader_current_page_index + int(delta))

    def go_to_last_reader_page(self):
        if self.reader_current_pages:
            self.set_reader_page(len(self.reader_current_pages) - 1)

    def jump_reader_page(self):
        if self.reader_current_pages:
            self.set_reader_page(self.reader_page_spin.value() - 1)

    def update_reader_zoom_controls(self):
        has_pages = self.reader_current_entry is not None and bool(self.reader_current_pages)
        self.reader_zoom_value_label.setText(f"{self.get_reader_effective_zoom_percent()}%")
        self.reader_zoom_mode_combo.blockSignals(True)
        self.reader_zoom_mode_combo.setCurrentText(self.get_reader_zoom_mode_label(self.reader_zoom_mode))
        self.reader_zoom_mode_combo.blockSignals(False)
        self.reader_zoom_mode_combo.setEnabled(has_pages)
        self.reader_zoom_out_button.setEnabled(has_pages)
        self.reader_zoom_in_button.setEnabled(has_pages)
        self.reader_zoom_reset_button.setEnabled(has_pages)

    def set_reader_zoom_mode(self, mode, persist=True, refresh=True, reset_scroll=False):
        self.reader_zoom_mode = normalize_reader_zoom_mode(mode)
        self.update_reader_zoom_controls()
        if refresh:
            self.schedule_reader_render(delay_ms=1, reset_scroll=reset_scroll, invalidate=True)
        if persist:
            self.persist_gui_state_snapshot()

    def set_reader_zoom_percent(self, zoom_percent, persist=True, refresh=True, reset_scroll=False):
        self.reader_zoom_percent = clamp_reader_zoom_percent(zoom_percent, fallback=self.reader_zoom_percent)
        self.reader_zoom_mode = "manual"
        self.update_reader_zoom_controls()
        if refresh:
            self.schedule_reader_render(delay_ms=1, reset_scroll=reset_scroll, invalidate=True)
        if persist:
            self.persist_gui_state_snapshot()

    def adjust_reader_zoom(self, delta):
        if self.reader_source_image is not None:
            self.set_reader_zoom_percent(self.get_reader_effective_zoom_percent() + int(delta), reset_scroll=True)

    def reset_reader_zoom(self):
        if self.reader_source_image is not None:
            self.set_reader_zoom_percent(100, reset_scroll=True)

    def update_reader_focus_button(self):
        if self.reader_fullscreen_active:
            self.reader_focus_button.setText("全屏阅读中")
            self.reader_focus_button.setEnabled(False)
            self.reader_hint_label.setText("全屏阅读已开启：标签栏和状态栏已隐藏。按 Esc、F11 或双击预览区即可退出。")
            return
        self.reader_focus_button.setEnabled(True)
        self.reader_focus_button.setText("退出专注阅读" if self.reader_focus_mode else "专注阅读")
        self.reader_hint_label.setText(
            "专注阅读已开启：翻页与缩放工具栏已收起，预览区占据更多空间。可继续使用滚轮、方向键、PageUp / PageDown 阅读，按 Esc 可恢复完整工具栏。"
            if self.reader_focus_mode
            else "阅读器现在与漫画库完全分开。先在“漫画库”选择漫画，再到这里翻页、缩放或全屏；滚轮会优先滚动页面，到边界时自动翻页。"
        )

    def update_reader_fullscreen_button(self):
        self.reader_fullscreen_button.setText("退出全屏" if self.reader_fullscreen_active else "全屏阅读")

    def set_reader_focus_mode(self, enabled, persist=True, refresh=True):
        scroll_position = self.store_current_reader_scroll_position()
        self.reader_focus_mode = bool(enabled)
        self.reader_page_group.setVisible(not self.reader_focus_mode)
        self.reader_zoom_group.setVisible(not self.reader_focus_mode)
        self.update_reader_focus_button()
        self.update_reader_fullscreen_button()
        if refresh:
            self.schedule_reader_render(scroll_position=scroll_position, invalidate=True)
        if persist:
            self.persist_gui_state_snapshot()

    def toggle_reader_focus_mode(self):
        self.set_reader_focus_mode(not self.reader_focus_mode)

    def get_reader_fullscreen_transition_delay_ms(self):
        if os.name == "nt" and self.reader_windows_fullscreen_mode == "exclusive":
            return READER_FULLSCREEN_TRANSITION_MS + 80
        return READER_FULLSCREEN_TRANSITION_MS

    def set_reader_fullscreen_mode(self, enabled):
        target_mode = bool(enabled)
        if target_mode == self.reader_fullscreen_active:
            self.update_reader_focus_button()
            self.update_reader_fullscreen_button()
            return
        scroll_position = self.store_current_reader_scroll_position()
        self.reader_fullscreen_active = target_mode
        if self.reader_fullscreen_active:
            if self.tabs.currentIndex() != self.get_tab_index("reader_view"):
                self.switch_tab("reader_view")
            self._reader_tab_bar_visible_before_fullscreen = self.tabs.tabBar().isVisible()
            self._reader_window_was_maximized = self.isMaximized()
            self._reader_window_size_before_fullscreen = self.size()
            self.reader_focus_mode_before_fullscreen = self.reader_focus_mode
            self.tabs.tabBar().setVisible(False)
            self.statusBar().setVisible(False)
            self.reader_header_group.setVisible(False)
            self.set_reader_focus_mode(True, persist=False, refresh=False)
            if os.name == "nt" and self.reader_windows_fullscreen_mode == "exclusive":
                self.showFullScreen()
            else:
                self.showMaximized()
            self.log("已进入全屏阅读模式")
            self.set_status("全屏阅读模式已开启")
        else:
            self.showNormal()
            if self._reader_window_was_maximized:
                self.showMaximized()
            else:
                self.resize(self._reader_window_size_before_fullscreen)
            self.tabs.tabBar().setVisible(self._reader_tab_bar_visible_before_fullscreen)
            self.statusBar().setVisible(True)
            self.reader_header_group.setVisible(True)
            self.set_reader_focus_mode(self.reader_focus_mode_before_fullscreen, persist=False, refresh=False)
            self.log("已退出全屏阅读模式")
            self.set_status("已退出全屏阅读模式")
        self.update_reader_focus_button()
        self.update_reader_fullscreen_button()
        QTimer.singleShot(
            self.get_reader_fullscreen_transition_delay_ms(),
            lambda: self.schedule_reader_render(delay_ms=1, scroll_position=scroll_position, invalidate=True),
        )

    def toggle_reader_fullscreen_mode(self):
        self.set_reader_fullscreen_mode(not self.reader_fullscreen_active)

    def restore_state(self):
        getcomics_state = self.gui_state["getcomics"]
        self.getcomics_query_edit.setText(getcomics_state["query"])
        self.getcomics_date_edit.setText(getcomics_state["date"])
        self.getcomics_results_combo.setCurrentText(getcomics_state["results"])
        self.getcomics_save_dir_edit.setText(getcomics_state["save_dir"])
        self.populate_getcomics_results_list(self.getcomics_search_results_data)
        self.update_getcomics_page_status(getcomics_state["last_page"])

        self.settings_appearance_combo.setCurrentText(self.appearance_mode)
        self.settings_reader_fullscreen_combo.setCurrentText(
            self.get_windows_reader_fullscreen_mode_label(self.reader_windows_fullscreen_mode)
        )
        self.settings_api_key_edit.setText(self.rename_api_key)
        self.settings_api_url_edit.setText(self.rename_api_url)
        self.settings_api_model_edit.setText(self.rename_api_model)
        self.settings_api_timeout_spin.setValue(self.rename_api_timeout)
        self.refresh_settings_labels()

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
        if active_path and entry["path"] == active_path and active_page > 0:
            self.open_reader_entry(entry, target_page=active_page, persist=False, announce=False)

    def collect_gui_state(self):
        selected_reader_entry = self.get_selected_reader_entry()
        active_scroll_x, active_scroll_y = self.get_current_reader_scroll_position()
        return {
            "getcomics": {
                "query": self.getcomics_query_edit.text().strip(),
                "date": self.getcomics_date_edit.text().strip(),
                "results": self.getcomics_results_combo.currentText().strip(),
                "save_dir": self.getcomics_save_dir_edit.text().strip(),
                "recent_searches": list(self.getcomics_recent_searches),
                "view_mode": self.getcomics_view_mode,
                "favorites": normalize_cached_getcomics_results([{"url": url, "title": title} for url, title in self.getcomics_favorites]),
                "queue_items": normalize_cached_getcomics_results([{"url": url, "title": title} for url, title in self.getcomics_download_queue]),
                "last_page": self.getcomics_search_current_page if self.getcomics_search_results_data else 0,
                "last_results": normalize_cached_getcomics_results([{"url": url, "title": title} for url, title in self.getcomics_search_results_data]),
            },
            "reader": {
                "source_path": self.reader_source_edit.text().strip(),
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
        if not save_gui_state(self.gui_state_path, self.gui_state, default_save_dir=self.default_getcomics_save_dir):
            main_logger.warning("Failed to save GUI state to %s", self.gui_state_path)

    def closeEvent(self, event: QCloseEvent):
        self.store_current_reader_scroll_position()
        if self.is_any_task_running():
            result = QMessageBox.question(self, "确认关闭", "当前仍有后台任务在运行，确定要关闭吗？")
            if result != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.is_cancelled = True
            self.is_getcomics_cancelled = True
        self.reader_render_timer.stop()
        self.reader_scroll_save_timer.stop()
        self.persist_gui_state_snapshot()
        try:
            self.comic_dl_downloader.close_parsers()
        except Exception:
            pass
        logging.getLogger().removeHandler(self.qt_log_handler)
        super().closeEvent(event)


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("漫画下载器整合版")
    window = ComicDownloaderQtWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
