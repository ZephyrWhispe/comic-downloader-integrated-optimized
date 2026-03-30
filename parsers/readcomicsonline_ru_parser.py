import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .base_parser import BaseComicParser
from .base_parser import logger

PAGES_PATTERN = re.compile(r"var\s+pages\s*=\s*\[(.*?)\];", re.DOTALL)
IMAGE_PATTERN = re.compile(r'"([^"]+\.(?:jpg|jpeg|png|gif|webp))"', re.IGNORECASE)


class ReadComicsOnlineRuParser(BaseComicParser):
    """readcomicsonline.ru 网站解析器"""

    BASE_URL = "https://readcomicsonline.ru"

    def _sanitize_title(self, value):
        return re.sub(r'[\\/:*?"<>|]', "_", (value or "").strip())

    def _extract_series_slug(self, url):
        path_parts = [part for part in urlparse(url).path.split("/") if part]
        if len(path_parts) >= 2 and path_parts[0] == "comic":
            return path_parts[1]
        return ""

    def _extract_title(self, soup, url):
        title_tag = soup.find("title")
        if title_tag:
            title = title_tag.get_text(" ", strip=True)
            title = re.sub(r"\s*-\s*Info Page$", "", title, flags=re.IGNORECASE)
            title = re.sub(r"\s*-\s*Page\s*\d+$", "", title, flags=re.IGNORECASE)
            title = re.sub(r"\s+Chapter\s+.+$", "", title, flags=re.IGNORECASE)
            title = re.sub(r"\s+by\s+.+$", "", title, flags=re.IGNORECASE)
            if title and title.lower() != "read comics online":
                return self._sanitize_title(title)

        og_title = soup.find("meta", {"property": "og:title"})
        if og_title and og_title.get("content"):
            title = og_title["content"].strip()
            title = re.sub(r"\s*-\s*Info Page$", "", title, flags=re.IGNORECASE)
            title = re.sub(r"\s*-\s*Page\s*\d+$", "", title, flags=re.IGNORECASE)
            title = re.sub(r"\s+Chapter\s+.+$", "", title, flags=re.IGNORECASE)
            title = re.sub(r"\s+by\s+.+$", "", title, flags=re.IGNORECASE)
            if title and title.lower() != "read comics online":
                return self._sanitize_title(title)

        slug = self._extract_series_slug(url)
        if slug:
            return self._sanitize_title(slug.replace("-", " ").title())

        return "Unknown Comic"

    def _extract_chapter_title(self, soup, url, series_title):
        title_tag = soup.find("title")
        if title_tag:
            title = title_tag.get_text(" ", strip=True)
            title = re.sub(r"\s*-\s*Page\s*\d+$", "", title, flags=re.IGNORECASE)
            if title:
                return self._sanitize_title(title)

        suffix = urlparse(url).path.strip("/").split("/")[-1]
        return self._sanitize_title(f"{series_title} {suffix.replace('-', ' ')}")

    def _extract_chapter_links(self, soup, series_url):
        series_slug = self._extract_series_slug(series_url)
        if not series_slug:
            return []

        prefix = f"/comic/{series_slug}/"
        chapter_links = []
        seen = set()

        for anchor in soup.find_all("a", href=True):
            chapter_url = urljoin(self.BASE_URL, anchor.get("href", "").strip())
            chapter_name = anchor.get_text(" ", strip=True)

            if not chapter_name:
                continue

            path = urlparse(chapter_url).path
            if not path.startswith(prefix):
                continue

            suffix = path[len(prefix):].strip("/")
            if not suffix or "/" in suffix:
                continue

            if not re.search(r"\d", suffix) and not any(
                keyword in suffix.lower() for keyword in ("annual", "special", "full", "tpb")
            ):
                continue

            if chapter_url in seen:
                continue

            seen.add(chapter_url)
            chapter_links.append((chapter_name, chapter_url))

        return chapter_links

    def _extract_images_from_html(self, html, chapter_url):
        image_urls = []
        seen = set()

        pages_match = PAGES_PATTERN.search(html)
        if pages_match:
            for raw_url in IMAGE_PATTERN.findall(pages_match.group(1)):
                img_url = raw_url.strip()
                if not img_url:
                    continue
                if not img_url.startswith("http"):
                    img_url = self._normalize_image_url(chapter_url, img_url)
                if img_url in seen:
                    continue
                seen.add(img_url)
                image_urls.append(img_url)

        if image_urls:
            return image_urls

        soup = BeautifulSoup(html, "html.parser")
        for img in soup.select("#all img[data-src], #all img[src], img[data-src]"):
            img_url = (img.get("data-src") or img.get("src") or "").strip()
            if not img_url or img_url.startswith("data:"):
                continue
            if not img_url.startswith("http"):
                img_url = self._normalize_image_url(chapter_url, img_url)
            if img_url in seen:
                continue
            seen.add(img_url)
            image_urls.append(img_url)

        return image_urls

    def _normalize_image_url(self, chapter_url, img_url):
        img_url = (img_url or "").strip()
        if not img_url:
            return img_url

        if img_url.startswith("http"):
            return img_url

        if img_url.startswith("/"):
            return urljoin(self.BASE_URL, img_url)

        path_parts = [part for part in urlparse(chapter_url).path.split("/") if part]
        if len(path_parts) >= 3 and path_parts[0] == "comic":
            series_slug = path_parts[1]
            chapter_slug = path_parts[2]
            return urljoin(
                self.BASE_URL,
                f"/uploads/manga/{series_slug}/chapters/{chapter_slug}/{img_url.lstrip('/')}",
            )

        return urljoin(chapter_url, img_url)

    def get_comic_info(self, url):
        logger.info("获取漫画信息: %s", url)
        try:
            response = self.scraper.get(url, timeout=30)
            response.raise_for_status()
            logger.info("响应状态码: %s", response.status_code)

            soup = BeautifulSoup(response.text, "html.parser")
            resolved_url = response.url
            title = self._extract_title(soup, resolved_url)

            path_parts = [part for part in urlparse(resolved_url).path.split("/") if part]
            if len(path_parts) >= 3:
                chapter_title = self._extract_chapter_title(soup, resolved_url, title)
                logger.info("漫画标题: %s", title)
                logger.info("检测到单话页面，返回当前章节")
                return title, [(chapter_title, resolved_url)]

            chapter_links = self._extract_chapter_links(soup, resolved_url)
            logger.info("漫画标题: %s", title)
            logger.info("找到 %s 个章节", len(chapter_links))
            return title, chapter_links
        except Exception as e:
            logger.error(f"获取漫画信息失败: {e}")
            return None, []

    def get_chapter_images(self, chapter_url, progress_callback=None):
        logger.info("获取章节图片: %s", chapter_url)
        try:
            response = self.scraper.get(chapter_url, timeout=30)
            response.raise_for_status()
            logger.info("响应状态码: %s", response.status_code)

            image_urls = self._extract_images_from_html(response.text, response.url)
            logger.info("提取到 %s 个图片 URL", len(image_urls))
            return image_urls
        except Exception as e:
            logger.error(f"获取章节图片失败: {e}")
            return []

    def get_site_name(self):
        return "readcomicsonline.ru"
