import threading
from typing import Dict, List, Optional, Tuple

import requests

from core.browser_manager import BrowserManager

from .base_parser import BaseComicParser
from .base_parser import logger

BATCAVE_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
BATCAVE_STEALTH_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'platform', {get: () => 'Win32'});
Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
"""


class BatCaveBizParser(BaseComicParser):
    """batcave.biz parser using Playwright to pass Cloudflare and extract data."""

    BASE_URL = "https://batcave.biz"

    def __init__(self):
        super().__init__()
        self._browser_managers: Dict[int, BrowserManager] = {}
        self._browser_lock = threading.Lock()
        self._download_cookies: Dict[str, str] = {}
        self._download_referer: Optional[str] = None
        self._download_lock = threading.Lock()

    def _get_browser_manager(self) -> BrowserManager:
        thread_id = threading.get_ident()
        with self._browser_lock:
            manager = self._browser_managers.get(thread_id)
            if manager is None:
                manager = BrowserManager(headless=True)
                self._browser_managers[thread_id] = manager
            return manager

    def _new_page(self):
        browser_manager = self._get_browser_manager()
        context = browser_manager.browser.new_context(
            user_agent=BATCAVE_USER_AGENT,
            viewport={"width": 1366, "height": 768},
            locale="en-US",
            timezone_id="America/New_York",
        )
        context.add_init_script(BATCAVE_STEALTH_SCRIPT)
        return context.new_page(), context

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

    def _sanitize_title(self, value: Optional[str]) -> str:
        title = (value or "").strip()
        for char in '\\/:*?"<>|':
            title = title.replace(char, "_")
        return title or "Unknown Comic"

    def _wait_for_data(self, page, require_images=False):
        page.wait_for_function(
            "document.title && document.title !== 'Just a moment...'",
            timeout=60000,
        )
        page.wait_for_function(
            "typeof window.__DATA__ === 'object' && window.__DATA__ !== null",
            timeout=60000,
        )
        if require_images:
            page.wait_for_function(
                "Array.isArray(window.__DATA__.images) && window.__DATA__.images.length > 0",
                timeout=60000,
            )

    def _open_page_data(
        self,
        url: str,
        require_images: bool = False,
    ) -> Tuple[Dict, str, Optional[Dict[str, str]], List[Dict[str, str]]]:
        last_error = None
        for attempt in range(3):
            page, context = self._new_page()
            try:
                logger.info("Opening BatCave page: %s", url)
                page.goto(url, wait_until="domcontentloaded", timeout=120000)
                page.wait_for_timeout(4000)
                self._wait_for_data(page, require_images=require_images)
                data = page.evaluate("window.__DATA__")
                series_link = page.evaluate(
                    """() => {
                        const el = document.querySelector('.header__post-link');
                        if (!el) return null;
                        return {
                            text: (el.textContent || '').trim(),
                            href: el.href || '',
                        };
                    }"""
                )
                cookies = context.cookies()
                return data, page.url, series_link, cookies
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "BatCave page open failed (attempt %s/3): %s",
                    attempt + 1,
                    exc,
                )
            finally:
                context.close()

        raise RuntimeError(f"Failed to open BatCave page: {last_error}")

    def _build_chapter_links(self, news_id: int, chapters: List[Dict], xhash: str = "") -> List[Tuple[str, str]]:
        chapter_links = []
        for chapter in chapters or []:
            chapter_id = chapter.get("id")
            if not chapter_id:
                continue
            title = (chapter.get("title_en") or chapter.get("title") or f"Chapter {chapter_id}").strip()
            chapter_links.append((title, f"{self.BASE_URL}/reader/{news_id}/{chapter_id}{xhash or ''}"))
        return chapter_links

    def _store_download_state(self, cookies: List[Dict[str, str]], referer: str) -> None:
        with self._download_lock:
            self._download_cookies = {cookie["name"]: cookie["value"] for cookie in cookies}
            self._download_referer = referer

    def get_comic_info(self, url):
        logger.info("Fetching BatCave comic info: %s", url)
        try:
            is_reader_page = "/reader/" in url
            data, resolved_url, series_link, _ = self._open_page_data(url, require_images=is_reader_page)

            if is_reader_page:
                title = (series_link or {}).get("text") or data.get("title") or "Unknown Comic"
            else:
                title = data.get("title") or (series_link or {}).get("text") or "Unknown Comic"

            chapter_links = self._build_chapter_links(
                data.get("news_id"),
                data.get("chapters", []),
                data.get("xhash", ""),
            )

            title = self._sanitize_title(title)

            logger.info("BatCave title: %s", title)
            logger.info("Found %s chapters for %s", len(chapter_links), resolved_url)
            return title, chapter_links
        except Exception as exc:
            logger.error("Failed to fetch BatCave comic info: %s", exc)
            return None, []

    def get_chapter_images(self, chapter_url, progress_callback=None):
        logger.info("Fetching BatCave chapter images: %s", chapter_url)
        try:
            if progress_callback:
                progress_callback("Opening BatCave reader page...")

            data, resolved_url, _, cookies = self._open_page_data(chapter_url, require_images=True)
            image_urls = [url.strip() for url in data.get("images", []) if url]
            self._store_download_state(cookies, resolved_url)

            if progress_callback:
                progress_callback(f"Collected {len(image_urls)} BatCave pages")

            logger.info("Collected %s BatCave images", len(image_urls))
            return image_urls
        except Exception as exc:
            logger.error("Failed to fetch BatCave chapter images: %s", exc)
            return []

    def download_image(self, image_url, save_path, headers=None, timeout=30):
        request_headers = {"User-Agent": BATCAVE_USER_AGENT}
        if headers:
            request_headers.update(headers)

        with self._download_lock:
            cookies = dict(self._download_cookies)
            referer = self._download_referer

        if referer and "Referer" not in request_headers:
            request_headers["Referer"] = referer

        if not cookies:
            raise RuntimeError("BatCave image download requested without solved cookies")

        response = requests.get(
            image_url,
            headers=request_headers,
            cookies=cookies,
            timeout=timeout,
        )
        response.raise_for_status()

        content_type = response.headers.get("content-type", "").lower()
        if "text/html" in content_type:
            raise ValueError("BatCave returned HTML instead of image content")

        with open(save_path, "wb") as file_handle:
            file_handle.write(response.content)

        return True

    def get_site_name(self):
        return "batcave.biz"
