import logging
import os
from pathlib import Path
from datetime import datetime

# 确保日志目录存在
LOG_DIR = Path(".") / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# 生成日志文件名
log_filename = LOG_DIR / f"comic_downloader_integrated_{datetime.now().strftime('%Y-%m-%d')}.log"

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_filename),
        logging.StreamHandler()
    ]
)

# 创建不同模块的日志记录器
getinfo_logger = logging.getLogger("getinfo")
download_logger = logging.getLogger("download")
menu_logger = logging.getLogger("menu")
main_logger = logging.getLogger("main")

# 导出所有日志记录器
__all__ = ["getinfo_logger", "download_logger", "menu_logger", "main_logger", "setup_gui_logging"]

def setup_gui_logging(queue):
    """设置 GUI 日志处理程序"""
    class GuiHandler(logging.Handler):
        def __init__(self, queue):
            super().__init__()
            self.queue = queue

        def emit(self, record):
            msg = self.format(record)
            self.queue.put(("log", msg))

    gui_handler = GuiHandler(queue)
    gui_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    
    # 将处理程序添加到所有主要的记录器
    # 包含 root 记录器以捕获所有模块的日志
    logging.getLogger().addHandler(gui_handler)
    
    return gui_handler
