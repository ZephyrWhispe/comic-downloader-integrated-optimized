import cloudscraper
import logging

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class BaseComicParser:
    """漫画网站解析器基类"""
    def __init__(self):
        self.scraper = cloudscraper.create_scraper()
    
    def get_comic_info(self, url):
        """获取漫画信息和章节列表"""
        raise NotImplementedError
    
    def get_chapter_images(self, chapter_url, progress_callback=None):
        """获取章节图片链接"""
        raise NotImplementedError
    
    def get_site_name(self):
        """获取网站名称"""
        raise NotImplementedError
