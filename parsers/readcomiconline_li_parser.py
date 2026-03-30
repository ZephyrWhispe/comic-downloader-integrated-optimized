from .base_parser import BaseComicParser
from .base_parser import logger
from bs4 import BeautifulSoup
import threading
import re
import sys
import os

# 添加项目根目录到 Python 路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.browser_manager import BrowserManager
from playwright.sync_api import TimeoutError as PlaywrightTimeout

class ReadComicOnlineLiParser(BaseComicParser):
    def __init__(self):
        super().__init__()
        self._browser_managers = {}
        self._browser_lock = threading.Lock()

    def _get_browser_manager(self):
        thread_id = threading.get_ident()
        with self._browser_lock:
            manager = self._browser_managers.get(thread_id)
            if manager is None:
                manager = BrowserManager(headless=True)
                self._browser_managers[thread_id] = manager
            return manager
    
    def _new_page(self):
        return self._get_browser_manager().new_page()
    
    def close(self):
        thread_id = threading.get_ident()
        with self._browser_lock:
            manager = self._browser_managers.pop(thread_id, None)
        if manager:
            manager.close()

    def close_all(self):
        with self._browser_lock:
            managers = list(self._browser_managers.values())
            self._browser_managers.clear()
        for manager in managers:
            try:
                manager.close()
            except Exception:
                pass
    """readcomiconline.li 网站解析器"""
    def get_comic_info(self, url):
        logger.info(f"获取漫画信息: {url}")
        try:
            response = self.scraper.get(url)
            logger.info(f"响应状态码: {response.status_code}")
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 提取漫画标题
            title = 'Unknown Comic'
            # 尝试从 bigChar 类的链接中提取标题
            title_element = soup.find('a', class_='bigChar')
            if title_element:
                title = title_element.text.strip()
            else:
                # 尝试从 h1 标签中提取标题
                h1_element = soup.find('h1')
                if h1_element:
                    title = h1_element.text.strip()
                else:
                    # 尝试从页面标题中提取
                    title_tag = soup.find('title')
                    if title_tag:
                        title = title_tag.text.strip()
                        # 清理页面标题
                        if 'comic | Read' in title:
                            title = title.split('comic | Read')[0].strip()
            # 清理标题，移除特殊字符
            title = re.sub(r'[\\/:*?"<>|]', '_', title)
            logger.info(f"漫画标题: {title}")
            
            # 提取章节链接
            chapter_links = []
            
            # 首先尝试从章节列表表格中提取
            # 查找所有表格，然后找到包含章节链接的表格
            tables = soup.find_all('table')
            logger.info(f"找到 {len(tables)} 个表格")
            
            for table in tables:
                # 检查表格中是否有章节链接
                links = table.find_all('a', href=lambda href: href and '/Comic/' in href and ('Issue' in href or 'Chapter' in href))
                if links:
                    logger.info(f"在表格中找到 {len(links)} 个章节链接")
                    for link in links:
                        chapter_name = link.text.strip()
                        chapter_url = link.get('href', '').strip()
                        if chapter_url and chapter_name:
                            chapter_links.append((chapter_name, chapter_url))
                    break
            
            # 如果没有从表格中找到章节，尝试原来的方法
            if not chapter_links:
                logger.info("未从表格中找到章节，使用备选方法")
                # 查找章节列表
                chapter_elements = soup.find_all('a', href=lambda href: href and '/Comic/' in href and ('Issue' in href or 'Chapter' in href))
                logger.info(f"找到 {len(chapter_elements)} 个章节元素")
                
                for element in chapter_elements:
                    chapter_name = element.text.strip()
                    chapter_url = element.get('href', '').strip()
                    if chapter_url and chapter_name:
                        # 如果章节名称只有 "Issue #X"，添加漫画标题
                        if chapter_name.startswith('Issue #') or chapter_name.startswith('Chapter #'):
                            chapter_name = f"{title.replace('_', ' ')} {chapter_name}"
                        chapter_links.append((chapter_name, chapter_url))
            
            # 去重
            seen = set()
            unique_chapters = []
            for chapter in chapter_links:
                if chapter[1] not in seen:
                    seen.add(chapter[1])
                    unique_chapters.append(chapter)
            
            logger.info(f"找到 {len(unique_chapters)} 个章节")
            
            # 打印找到的章节
            logger.info("找到的章节:")
            for i, (chapter_name, chapter_url) in enumerate(unique_chapters[:20], 1):
                logger.info(f"{i}. {chapter_name} - {chapter_url}")
            
            if len(unique_chapters) > 20:
                logger.info(f"... 还有 {len(unique_chapters) - 20} 个章节")
            
            return title, unique_chapters
        except Exception as e:
            logger.error(f"获取漫画信息失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None, []
    
    def _decode_image_url(self, encoded_url):
        """
        解码图片 URL
        实现 cUJ0CKOn8ZU 函数的逻辑
        """
        # 替换特殊字符
        decoded_url = encoded_url.replace('2u__EXHYIq_', 'g')
        decoded_url = decoded_url.replace('b', 'pw_.g28x')
        decoded_url = decoded_url.replace('h', 'd2pr.x_27')
        # 移除可能的前缀
        if decoded_url.startswith('tB6g6rIEm1B'):
            decoded_url = decoded_url[11:]
        return decoded_url
    
    def get_chapter_images(self, chapter_url, progress_callback=None):
        logger.info(f"获取章节图片: {chapter_url}")
        if progress_callback:
            progress_callback(f"正在准备浏览器加载章节...")
        try:
            # 使用 Playwright 处理动态内容和懒加载
            # Append readType=1 to load all pages on a single page
            separator = "&" if "?" in chapter_url else "?"
            all_pages_url = f"{chapter_url}{separator}readType=1"
            
            page, context = self._new_page()
            try:
                # Set viewport to something reasonable
                page.set_viewport_size({"width": 1280, "height": 1024})
                
                logger.info(f"正在加载页面: {all_pages_url}")
                if progress_callback:
                    progress_callback(f"正在加载漫画页面...")
                page.goto(all_pages_url, wait_until="load", timeout=90000)
                
                try:
                    # Wait for the main image container
                    page.wait_for_selector("div#divImage", timeout=30000)
                except PlaywrightTimeout:
                    logger.warning("未找到图片容器 div#divImage")
                    return []
                
                # Scroll to bottom slowly to trigger lazy loading
                logger.info("正在模拟滚动以触发图片加载...")
                if progress_callback:
                    progress_callback(f"正在模拟滚动以触发图片懒加载...")
                page.evaluate("""async () => {
                    const scrollStep = 500;
                    const scrollDelay = 100;
                    
                    let totalHeight = 0;
                    let distance = 0;
                    
                    const scrollContainer = document.scrollingElement || document.documentElement;
                    
                    while (distance < scrollContainer.scrollHeight) {
                        window.scrollBy(0, scrollStep);
                        distance += scrollStep;
                        await new Promise(resolve => setTimeout(resolve, scrollDelay));
                        
                        // Dynamic scroll height check
                        if (scrollContainer.scrollHeight > totalHeight) {
                            totalHeight = scrollContainer.scrollHeight;
                        }
                    }
                    
                    // Final scroll to top and bottom to nudge any missed ones
                    window.scrollTo(0, 0);
                    await new Promise(r => setTimeout(r, 500));
                    window.scrollTo(0, document.body.scrollHeight);
                    await new Promise(r => setTimeout(r, 1000));
                }""")
                
                # Poll for images to load, replacing blank.gif
                logger.info("等待所有图片加载完成...")
                if progress_callback:
                    progress_callback(f"等待所有图片加载完成...")
                page.evaluate("""async () => {
                    const getIncompleteImages = () => {
                        const imgs = Array.from(document.querySelectorAll('div#divImage img'));
                        return imgs.filter(img => {
                            const isVisible = img.offsetParent !== null;
                            const isBlank = !img.src || img.src.includes('blank.gif');
                            const isNotLoaded = !img.complete || img.naturalWidth === 0;
                            return isVisible && (isBlank || isNotLoaded);
                        });
                    };
                    
                    let deadline = Date.now() + 30000; // 30 seconds max wait
                    while (Date.now() < deadline) {
                        const incomplete = getIncompleteImages();
                        if (incomplete.length === 0) break;
                        
                        // Nudge the first incomplete image
                        incomplete[0].scrollIntoView({ behavior: 'smooth', block: 'center' });
                        await new Promise(r => setTimeout(r, 1000));
                        
                        // Extend deadline slightly if progress is being made
                        // (Optional: can be added if needed)
                    }
                }""")
                
                # Extract image URLs in order
                image_urls = page.evaluate("""() => {
                    const imgs = Array.from(document.querySelectorAll('div#divImage img'));
                    return imgs
                        .filter(img => img.offsetParent !== null) // only visible
                        .map(img => img.src)
                        .filter(src => src && !src.includes('blank.gif'));
                }""")
                
                if not image_urls:
                    logger.warning("未提取到任何有效的图片 URL")
                    return []
                
                # Maintain order and remove duplicates (rare but possible)
                seen = set()
                unique_ordered_urls = []
                for url in image_urls:
                    if url not in seen:
                        seen.add(url)
                        unique_ordered_urls.append(url)
                
                logger.info(f"使用 Playwright 提取到 {len(unique_ordered_urls)} 个图片 URL")
                return unique_ordered_urls
            finally:
                context.close()
        except Exception as e:
            logger.error(f"获取章节图片失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return []
    
    def get_site_name(self):
        return "readcomiconline.li"
