import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .base_parser import BaseComicParser
from .base_parser import logger

ISSUE_LINK_TEXT_PATTERN = re.compile(
    r"^(#|\d|issue\b|vol(?:ume)?\b|tpb\b|full\b|annual\b|special\b)",
    re.IGNORECASE,
)


class ReadAllComicsParser(BaseComicParser):
    """readallcomics.com 网站解析器"""

    BASE_URL = "https://readallcomics.com"

    def _sanitize_title(self, value):
        return re.sub(r'[\\/:*?"<>|]', "_", (value or "").strip())

    def _is_category_page(self, url):
        return "/category/" in urlparse(url).path.lower()

    def _extract_series_title(self, soup, url):
        h1 = soup.find("h1")
        if h1 and h1.get_text(strip=True):
            return self._sanitize_title(h1.get_text(" ", strip=True))

        og_title = soup.find("meta", {"property": "og:title"})
        if og_title and og_title.get("content"):
            title = og_title["content"].strip()
            title = re.sub(r"\s*\|\s*Read All Comics Online.*$", "", title, flags=re.IGNORECASE)
            if not self._is_category_page(url):
                title = re.sub(r"\s+#.*$", "", title)
            if title:
                return self._sanitize_title(title)

        title_tag = soup.find("title")
        if title_tag:
            title = title_tag.get_text(" ", strip=True)
            title = re.sub(r"\s*\|\s*Read All Comics Online.*$", "", title, flags=re.IGNORECASE)
            if not self._is_category_page(url):
                title = re.sub(r"\s+#.*$", "", title)
            if title:
                return self._sanitize_title(title)

        path_parts = [part for part in urlparse(url).path.split("/") if part]
        if "category" in path_parts:
            slug = path_parts[-1]
            return self._sanitize_title(slug.replace("-", " ").title())

        slug = path_parts[-1] if path_parts else "Unknown Comic"
        slug = re.sub(r"-\d{4}$", "", slug)
        slug = re.sub(r"-\d+$", "", slug)
        return self._sanitize_title(slug.replace("-", " ").title())

    def _extract_issue_title(self, soup, url, series_title):
        h1 = soup.find("h1")
        if h1 and h1.get_text(strip=True):
            return self._sanitize_title(h1.get_text(" ", strip=True))

        og_title = soup.find("meta", {"property": "og:title"})
        if og_title and og_title.get("content"):
            title = re.sub(r"\s*\|\s*Read All Comics Online.*$", "", og_title["content"].strip(), flags=re.IGNORECASE)
            if title:
                return self._sanitize_title(title)

        title_tag = soup.find("title")
        if title_tag:
            title = re.sub(r"\s*\|\s*Read All Comics Online.*$", "", title_tag.get_text(" ", strip=True), flags=re.IGNORECASE)
            if title:
                return self._sanitize_title(title)

        slug = urlparse(url).path.strip("/").split("/")[-1]
        return self._sanitize_title(f"{series_title} {slug.replace('-', ' ')}")

    def _is_issue_link(self, href, text):
        parsed = urlparse(href)
        if parsed.netloc and "readallcomics.com" not in parsed.netloc:
            return False

        path = parsed.path.strip("/")
        if not path or path.startswith("category/") or "/" in path:
            return False

        if not text:
            return False

        return bool(ISSUE_LINK_TEXT_PATTERN.search(text))

    def _extract_category_chapters(self, soup, base_url, title):
        chapter_links = []
        seen = set()

        for anchor in soup.find_all("a", href=True):
            href = anchor.get("href", "").strip()
            text = anchor.get_text(" ", strip=True)

            if not self._is_issue_link(href, text):
                continue

            chapter_url = urljoin(base_url, href)
            if chapter_url in seen:
                continue

            seen.add(chapter_url)
            chapter_name = text if text.lower().startswith(title.lower()) else f"{title} {text}"
            chapter_links.append((chapter_name.strip(), chapter_url))

        return chapter_links

    def _extract_category_url(self, soup, base_url):
        category_link = soup.select_one('a[href*="/category/"]')
        if not category_link or not category_link.get("href"):
            return None
        return urljoin(base_url, category_link["href"].strip())

    def _extract_image_urls_from_soup(self, soup, base_url):
        image_urls = []
        seen = set()

        for img in soup.find_all("img"):
            img_url = (
                img.get("data-jh-lazy-img")
                or img.get("data-src")
                or img.get("src")
                or ""
            ).strip()

            if not img_url or img_url.startswith("data:"):
                continue

            if img_url.startswith("//"):
                img_url = f"https:{img_url}"
            elif not img_url.startswith("http"):
                img_url = urljoin(base_url, img_url)

            if not any(token in img_url for token in ("googleusercontent.com", "blogspot.com")):
                continue

            if img_url in seen:
                continue

            seen.add(img_url)
            image_urls.append(img_url)

        return image_urls

    def get_comic_info(self, url):
        logger.info("获取漫画信息: %s", url)
        try:
            response = self.scraper.get(url, timeout=30)
            response.raise_for_status()
            logger.info("响应状态码: %s", response.status_code)

            soup = BeautifulSoup(response.text, "html.parser")
            resolved_url = response.url

            if self._is_category_page(resolved_url):
                title = self._extract_series_title(soup, resolved_url)
                chapter_links = self._extract_category_chapters(soup, resolved_url, title)
                logger.info("漫画标题: %s", title)
                logger.info("找到 %s 个章节", len(chapter_links))
                return title, chapter_links

            category_url = self._extract_category_url(soup, resolved_url)
            if category_url and category_url != resolved_url:
                category_response = self.scraper.get(category_url, timeout=30)
                category_response.raise_for_status()
                category_soup = BeautifulSoup(category_response.text, "html.parser")
                title = self._extract_series_title(category_soup, category_response.url)
                chapter_links = self._extract_category_chapters(category_soup, category_response.url, title)
                if chapter_links:
                    logger.info("漫画标题: %s", title)
                    logger.info("从分类页恢复到 %s 个章节", len(chapter_links))
                    return title, chapter_links

            series_title = self._extract_series_title(soup, resolved_url)
            issue_title = self._extract_issue_title(soup, resolved_url, series_title)
            logger.info("漫画标题: %s", series_title)
            logger.info("检测到单话页面，返回当前章节")
            return series_title, [(issue_title, resolved_url)]
        except Exception as e:
            logger.error(f"获取漫画信息失败: {e}")
            return None, []

    def get_chapter_images(self, chapter_url, progress_callback=None):
        logger.info("获取章节图片: %s", chapter_url)
        try:
            response = self.scraper.get(chapter_url, timeout=30)
            response.raise_for_status()
            logger.info("响应状态码: %s", response.status_code)

            soup = BeautifulSoup(response.text, "html.parser")
            image_urls = self._extract_image_urls_from_soup(soup, response.url)

            logger.info("提取到 %s 个图片 URL", len(image_urls))
            return image_urls
        except Exception as e:
            logger.error(f"获取章节图片失败: {e}")
            return []

    def get_site_name(self):
        return "readallcomics.com"
