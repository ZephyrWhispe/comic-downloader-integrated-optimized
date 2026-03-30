import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base_parser import BaseComicParser
from .base_parser import logger


class XoxoComicParser(BaseComicParser):
    """xoxocomic.com 网站解析器"""

    BASE_URL = "https://xoxocomic.com"

    def close(self):
        """Kept for compatibility with the shared downloader cleanup flow."""

    def _sanitize_title(self, value):
        return re.sub(r'[\\/:*?"<>|]', "_", (value or "").strip())

    def _extract_title(self, soup):
        h1 = soup.find("h1")
        if h1 and h1.get_text(strip=True):
            title = h1.get_text(" ", strip=True)
            title = re.sub(r"\s+Comic$", "", title, flags=re.IGNORECASE)
            title = re.sub(r"\s+-\s+Issue.+$", "", title, flags=re.IGNORECASE)
            if title:
                return self._sanitize_title(title)

        title_tag = soup.find("title")
        if title_tag:
            title = title_tag.get_text(" ", strip=True)
            title = re.sub(r"\s+\|\s+Xoxocomic$", "", title, flags=re.IGNORECASE)
            title = re.sub(r"\s+-\s+Issue.+$", "", title, flags=re.IGNORECASE)
            if title:
                return self._sanitize_title(title)

        return "Unknown Comic"

    def _extract_chapter_links_from_page(self, soup):
        chapter_links = []
        chapter_list_container = soup.find("div", id="nt_listchapter")
        if chapter_list_container:
            for item in chapter_list_container.find_all("li", class_="row"):
                if "heading" in item.get("class", []):
                    continue
                chapter_link = item.find("a", href=True)
                if not chapter_link:
                    continue
                href = chapter_link.get("href", "").strip()
                text = chapter_link.get_text(" ", strip=True)
                if href and text:
                    chapter_links.append((text, href))
            return chapter_links

        for link in soup.find_all("a", href=True):
            href = link.get("href", "").strip()
            text = link.get_text(" ", strip=True)
            if (
                "/comic/" in href
                and "issue-" in href.lower()
                and text
                and not text.isspace()
            ):
                chapter_links.append((text, href))
        return chapter_links

    def _find_next_catalog_page(self, soup, current_url):
        pagination = soup.find("div", class_="pagination-outter")
        if not pagination:
            return None

        next_link = pagination.find("a", rel="next")
        if next_link and next_link.get("href"):
            return urljoin(current_url, next_link["href"].strip())

        current_page = 1
        if "page=" in current_url:
            try:
                current_page = int(current_url.split("page=")[1])
            except ValueError:
                current_page = 1

        for link in pagination.find_all("a", href=True):
            href = link.get("href", "").strip()
            if "page=" not in href:
                continue
            try:
                page_num = int(href.split("page=")[1])
            except ValueError:
                continue
            if page_num == current_page + 1:
                return urljoin(current_url, href)

        return None

    def _extract_page_urls(self, soup, chapter_url):
        page_urls = []
        seen = set()

        for option in soup.select("#selectPage option[value]"):
            page_url = urljoin(chapter_url, option.get("value", "").strip())
            if not page_url or page_url in seen:
                continue
            seen.add(page_url)
            page_urls.append(page_url)

        if page_urls:
            return page_urls

        return [chapter_url]

    def _extract_page_image(self, soup, page_url):
        for img in soup.select("img[data-original], img.single-page, .page-chapter img"):
            img_url = (
                img.get("data-original")
                or img.get("data-src")
                or img.get("src")
                or ""
            ).strip()
            if not img_url or img_url.startswith("data:"):
                continue
            if any(token in img_url for token in ("logo", "loading-small", "blank")):
                continue
            return urljoin(page_url, img_url)

        og_image = soup.find("meta", {"property": "og:image"})
        if og_image and og_image.get("content"):
            img_url = og_image["content"].strip()
            if img_url and "logo" not in img_url:
                return urljoin(page_url, img_url)

        return None

    def _extract_issue_title(self, soup, series_title):
        h1 = soup.find("h1")
        if h1 and h1.get_text(strip=True):
            title = h1.get_text(" ", strip=True)
            title = re.sub(r"\s+Page\s+\d+$", "", title, flags=re.IGNORECASE)
            return self._sanitize_title(title)

        title_tag = soup.find("title")
        if title_tag:
            title = title_tag.get_text(" ", strip=True)
            title = re.sub(r"\s+\|\s+Xoxocomic$", "", title, flags=re.IGNORECASE)
            title = re.sub(r"\s+Page\s+\d+$", "", title, flags=re.IGNORECASE)
            return self._sanitize_title(title)

        return self._sanitize_title(series_title)

    def get_comic_info(self, url):
        logger.info("获取漫画信息: %s", url)
        try:
            chapter_links = []
            title = None
            current_url = url

            while current_url:
                logger.info("处理页面: %s", current_url)
                response = self.scraper.get(current_url, timeout=30)
                response.raise_for_status()
                logger.info("响应状态码: %s", response.status_code)

                soup = BeautifulSoup(response.text, "html.parser")
                if not title:
                    title = self._extract_title(soup)
                    logger.info("漫画标题: %s", title)

                if "/issue-" in response.url:
                    issue_title = self._extract_issue_title(soup, title)
                    logger.info("检测到单话页面，返回当前章节")
                    return title, [(issue_title, response.url)]

                chapter_links.extend(self._extract_chapter_links_from_page(soup))
                current_url = self._find_next_catalog_page(soup, response.url)

            seen = set()
            unique_chapters = []
            for chapter_name, chapter_url in chapter_links:
                chapter_url = urljoin(self.BASE_URL, chapter_url)
                if chapter_url in seen:
                    continue
                seen.add(chapter_url)
                unique_chapters.append((chapter_name, chapter_url))

            logger.info("找到 %s 个章节", len(unique_chapters))
            return title, unique_chapters
        except Exception as e:
            logger.error(f"获取漫画信息失败: {e}")
            return None, []

    def get_chapter_images(self, chapter_url, progress_callback=None):
        logger.info("获取章节图片: %s", chapter_url)
        try:
            response = self.scraper.get(chapter_url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")

            page_urls = self._extract_page_urls(soup, response.url)
            image_urls = []
            seen = set()

            total_pages = len(page_urls)
            for index, page_url in enumerate(page_urls, start=1):
                if progress_callback:
                    progress_callback(f"收集 XoxoComic 页面 {index}/{total_pages}...")

                page_response = self.scraper.get(page_url, timeout=30)
                page_response.raise_for_status()
                page_soup = BeautifulSoup(page_response.text, "html.parser")
                image_url = self._extract_page_image(page_soup, page_response.url)

                if image_url and image_url not in seen:
                    seen.add(image_url)
                    image_urls.append(image_url)

            logger.info("成功提取到 %s 个图片 URL", len(image_urls))
            return image_urls
        except Exception as e:
            logger.error(f"获取章节图片失败: {e}")
            return []

    def get_site_name(self):
        return "xoxocomic.com"
