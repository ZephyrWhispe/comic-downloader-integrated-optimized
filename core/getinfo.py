import asyncio
import re
from typing import Dict, Optional
from urllib.parse import quote_plus

import aiohttp
from bs4 import BeautifulSoup
from rich.console import Console

from .cache import cache
from .logger import getinfo_logger

BASE_URL = "https://getcomics.org"
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}
YEAR_PATTERN = re.compile(r"(19|20)\d{2}")
ISSUE_PATTERNS = (
    re.compile(r"#\s*(\d+(?:\.\d+)?)", re.IGNORECASE),
    re.compile(r"\bissue\s*#?\s*(\d+(?:\.\d+)?)", re.IGNORECASE),
    re.compile(r"\bchapter\s*#?\s*(\d+(?:\.\d+)?)", re.IGNORECASE),
)
DATE_CLASS_NAMES = (
    "entry-date",
    "posted-on",
    "post-date",
    "meta-date",
    "date",
    "published",
)
PREFERRED_DOWNLOAD_LABELS = (
    "DOWNLOAD NOW",
    "MAIN SERVER",
    "PIXELDRAIN",
    "MEGA",
)

console = Console()


class GetComics:
    def __init__(
        self,
        query: Optional[str],
        results: int,
        verbose: bool,
        min_issue: Optional[int] = None,
        max_issue: Optional[int] = None,
        date: Optional[object] = None,
    ):
        self.query = (query or "").strip()
        self.num_results_desired = results
        self.verbose = verbose
        self.page = 1
        self.page_links: Dict[str, str] = {}
        self.comic_links: Dict[str, str] = {}
        self.filter_year: Optional[int] = None
        self.min_issue: Optional[int] = None
        self.max_issue: Optional[int] = None
        self.set_filters(date=date, min_issue=min_issue, max_issue=max_issue)
        getinfo_logger.info(
            "Initialized GetComics with query=%s results=%s year=%s min=%s max=%s",
            self.query,
            results,
            self.filter_year,
            self.min_issue,
            self.max_issue,
        )

    def set_filters(
        self,
        date: Optional[object] = None,
        min_issue: Optional[object] = None,
        max_issue: Optional[object] = None,
    ) -> None:
        self.filter_year = self._normalize_year_filter(date)
        self.min_issue = self._normalize_issue_filter(min_issue)
        self.max_issue = self._normalize_issue_filter(max_issue)
        if (
            self.min_issue is not None
            and self.max_issue is not None
            and self.min_issue > self.max_issue
        ):
            self.min_issue, self.max_issue = self.max_issue, self.min_issue
            getinfo_logger.warning(
                "Swapped invalid issue range so min=%s max=%s",
                self.min_issue,
                self.max_issue,
            )

    def _normalize_year_filter(self, value: Optional[object]) -> Optional[int]:
        if value in (None, ""):
            return None
        if isinstance(value, int):
            return value
        match = YEAR_PATTERN.search(str(value))
        return int(match.group(0)) if match else None

    def _normalize_issue_filter(self, value: Optional[object]) -> Optional[int]:
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def get_loaded_page(self) -> int:
        try:
            return max(0, int(self.page) - 1)
        except (TypeError, ValueError):
            return 0

    def _limit_links(self, links: Dict[str, str]) -> Dict[str, str]:
        try:
            limit = int(self.num_results_desired)
        except (TypeError, ValueError):
            return links

        if limit < 1:
            return links
        return dict(list(links.items())[:limit])

    def _extract_year_from_text(self, value: Optional[str]) -> Optional[int]:
        if not value:
            return None
        match = YEAR_PATTERN.search(value)
        return int(match.group(0)) if match else None

    def _extract_article_year(self, article) -> Optional[int]:
        article_text = article.get_text(" ", strip=True)
        year = self._extract_year_from_text(article_text)
        if year:
            return year

        title_tag = article.find("h1", {"class": "post-title"})
        if title_tag:
            year = self._extract_year_from_text(title_tag.get_text(" ", strip=True))
            if year:
                return year

        time_tag = article.find("time")
        if time_tag:
            for candidate in (
                time_tag.get("datetime"),
                time_tag.get("title"),
                time_tag.get_text(" ", strip=True),
            ):
                year = self._extract_year_from_text(candidate)
                if year:
                    return year

        for class_name in DATE_CLASS_NAMES:
            for tag in article.find_all(class_=class_name):
                for candidate in (
                    tag.get("datetime"),
                    tag.get("title"),
                    tag.get_text(" ", strip=True),
                ):
                    year = self._extract_year_from_text(candidate)
                    if year:
                        return year

        return None

    def _select_preferred_direct_link(self, candidates):
        if not candidates:
            return None

        def candidate_rank(candidate):
            label = candidate["label"]
            for index, preferred_label in enumerate(PREFERRED_DOWNLOAD_LABELS):
                if preferred_label in label:
                    return (index, candidate["position"])
            return (len(PREFERRED_DOWNLOAD_LABELS), candidate["position"])

        return min(candidates, key=candidate_rank)

    def _extract_post_download_links(self, soup, title: str) -> Dict[str, str]:
        direct_candidates = []
        mediafire_candidates = []

        for position, tag in enumerate(soup.find_all("a", href=True)):
            href = tag["href"]
            link_text = tag.get_text(" ", strip=True).upper()
            link_title = tag.get("title", "").upper()
            label = " ".join(part for part in (link_text, link_title) if part).strip()

            if "getcomics.org/download" in href or "getcomics.org/dlds/" in href:
                direct_candidates.append(
                    {
                        "href": href,
                        "label": label,
                        "position": position,
                    }
                )
                continue

            if "MEDIAFIRE" in label:
                mediafire_candidates.append(
                    {
                        "href": href,
                        "position": position,
                    }
                )

        page_comic_links: Dict[str, str] = {}
        preferred_direct_link = self._select_preferred_direct_link(direct_candidates)
        if preferred_direct_link:
            page_comic_links[preferred_direct_link["href"]] = title
            return page_comic_links

        if mediafire_candidates:
            page_comic_links[f"_MEDIAFIRE_{mediafire_candidates[0]['href']}"] = title

        return page_comic_links

    def _extract_issue_number(self, title: str) -> Optional[float]:
        for pattern in ISSUE_PATTERNS:
            match = pattern.search(title or "")
            if match:
                try:
                    return float(match.group(1))
                except ValueError:
                    return None
        return None

    def _title_matches_filters(self, title: str, article_year: Optional[int] = None) -> bool:
        if self.filter_year is not None and article_year is not None and article_year < self.filter_year:
            return False

        issue_number = self._extract_issue_number(title)
        if self.min_issue is not None and issue_number is not None and issue_number < self.min_issue:
            return False
        if self.max_issue is not None and issue_number is not None and issue_number > self.max_issue:
            return False
        return True

    def _deserialize_cached_page_entries(self, raw_entries: Dict[str, object]) -> Dict[str, Dict[str, Optional[int]]]:
        normalized_entries: Dict[str, Dict[str, Optional[int]]] = {}
        for url, value in (raw_entries or {}).items():
            if isinstance(value, dict):
                title = str(value.get("title", "")).strip()
                year = self._normalize_year_filter(value.get("year"))
            else:
                title = str(value).strip()
                year = None

            if title:
                normalized_entries[url] = {"title": title, "year": year}
        return normalized_entries

    def _apply_page_filters(self, entries: Dict[str, Dict[str, Optional[int]]]) -> Dict[str, str]:
        filtered: Dict[str, str] = {}
        for url, metadata in entries.items():
            title = metadata.get("title", "")
            article_year = metadata.get("year")
            if self._title_matches_filters(title, article_year):
                filtered[url] = title
        return filtered

    def _apply_download_filters(self, links: Dict[str, str]) -> Dict[str, str]:
        if self.min_issue is None and self.max_issue is None:
            return links
        return {
            url: title
            for url, title in links.items()
            if self._title_matches_filters(title)
        }

    async def find_pages(self, date: Optional[object] = None) -> None:
        """Find article pages for the current search."""
        if date is not None:
            self.filter_year = self._normalize_year_filter(date)

        url = f"{BASE_URL}/page/{self.page}?s={quote_plus(self.query)}"
        getinfo_logger.info(
            "Finding pages for query=%s page=%s year=%s min=%s max=%s",
            self.query,
            self.page,
            self.filter_year,
            self.min_issue,
            self.max_issue,
        )

        cache_key = f"find_pages:{url}"
        cached_result = cache.get(cache_key)
        if cached_result:
            cached_entries = self._deserialize_cached_page_entries(cached_result)
            limited_result = self._limit_links(self._apply_page_filters(cached_entries))
            self.page_links.update(limited_result)
            getinfo_logger.info(
                "Found %s cached articles on page %s after filtering",
                len(limited_result),
                self.page,
            )
            self.page += 1
            return

        timeout = aiohttp.ClientTimeout(total=30)
        html = None
        for attempt in range(3):
            try:
                if self.verbose:
                    console.print(f"Opening page {url}")
                async with aiohttp.ClientSession(headers=DEFAULT_HEADERS) as session:
                    async with session.get(url, timeout=timeout) as response:
                        response.raise_for_status()
                        html = await response.text()
                break
            except aiohttp.ClientError as exc:
                error_msg = f"Error contacting URL: {url} (Attempt {attempt + 1}/3): {exc}"
                console.print(error_msg)
                getinfo_logger.error(error_msg)
                if attempt < 2:
                    console.print("Retrying in 2 seconds...")
                    await asyncio.sleep(2)
                else:
                    console.print("Max retries reached. Skipping this page.")
                    getinfo_logger.warning("Max retries reached for %s", url)
                    return

        if not html:
            getinfo_logger.warning("Failed to fetch HTML for %s", url)
            return

        try:
            soup = BeautifulSoup(html, "html.parser")
            articles = soup.find_all("article")
            if not articles:
                getinfo_logger.info("No articles found for query=%s", self.query)
                return

            raw_entries: Dict[str, Dict[str, Optional[int]]] = {}
            for article in articles:
                try:
                    title_tag = article.find("h1", {"class": "post-title"})
                    if not title_tag:
                        if self.verbose:
                            console.print("No title tag found for article, skipping")
                        continue

                    link_tag = title_tag.find("a")
                    if not link_tag or "href" not in link_tag.attrs:
                        if self.verbose:
                            console.print("No link found for article, skipping")
                        continue

                    title = title_tag.text.strip()
                    raw_entries[link_tag["href"]] = {
                        "title": title,
                        "year": self._extract_article_year(article),
                    }
                except Exception as exc:
                    error_msg = f"Error processing article: {exc}"
                    console.print(error_msg)
                    getinfo_logger.error(error_msg)

            cache.set(cache_key, raw_entries)
            limited_links = self._limit_links(self._apply_page_filters(raw_entries))
            self.page_links.update(limited_links)
            getinfo_logger.info(
                "Found %s articles on page %s after filtering",
                len(limited_links),
                self.page,
            )
            self.page += 1
        except Exception as exc:
            error_msg = f"Error parsing page: {exc}"
            console.print(error_msg)
            getinfo_logger.error(error_msg)

    async def get_download_links(self) -> None:
        """Extract direct download links from known GetComics posts."""
        getinfo_logger.info("Getting download links for %s pages", len(self.page_links))

        if not self.page_links:
            getinfo_logger.warning("No page links to process")
            return

        semaphore = asyncio.Semaphore(3)
        timeout = aiohttp.ClientTimeout(total=120, connect=20, sock_read=90, sock_connect=20)

        async with aiohttp.ClientSession(headers=DEFAULT_HEADERS) as session:
            async def process_page(url: str, title: str) -> None:
                async with semaphore:
                    cache_key = f"get_download_links:{url}"
                    cached_result = cache.get(cache_key)
                    if cached_result:
                        getinfo_logger.debug("Using cached download links for %s", url)
                        self.comic_links.update(self._apply_download_filters(cached_result))
                        return

                    html = None
                    for attempt in range(2):
                        try:
                            if self.verbose:
                                console.print(f"Opening page {url}")
                            async with session.get(url, timeout=timeout) as response:
                                if response.status == 404:
                                    error_msg = f"Page not found (404): {url}"
                                    console.print(error_msg)
                                    getinfo_logger.warning(error_msg)
                                    return
                                response.raise_for_status()
                                html = await response.text()
                            break
                        except aiohttp.ClientError as exc:
                            error_msg = f"Error contacting URL: {url} (Attempt {attempt + 1}/2): {exc}"
                            console.print(error_msg)
                            getinfo_logger.error(error_msg)
                            if attempt < 1:
                                console.print("Retrying in 3 seconds...")
                                await asyncio.sleep(3)
                            else:
                                console.print("Max retries reached. Skipping this page.")
                                getinfo_logger.warning("Max retries reached for %s", url)
                                return
                        except asyncio.TimeoutError as exc:
                            error_msg = f"Timeout error when fetching page {url}: {exc}"
                            console.print(error_msg)
                            getinfo_logger.error(error_msg)
                            if attempt < 1:
                                console.print("Retrying in 3 seconds...")
                                await asyncio.sleep(3)
                            else:
                                console.print("Max retries reached. Skipping this page.")
                                getinfo_logger.warning("Max retries reached for %s", url)
                                return
                        except Exception as exc:
                            error_msg = f"Unexpected error when fetching page {url}: {exc}"
                            console.print(error_msg)
                            getinfo_logger.error(error_msg, exc_info=True)
                            return

                    if not html:
                        getinfo_logger.warning("Failed to fetch HTML for %s", url)
                        return

                    try:
                        soup = BeautifulSoup(html, "html.parser")
                        page_comic_links = self._extract_post_download_links(soup, title)
                        direct_links_found = any(
                            not key.startswith("_MEDIAFIRE_") for key in page_comic_links
                        )

                        cache.set(cache_key, page_comic_links)
                        filtered_links = self._apply_download_filters(page_comic_links)
                        self.comic_links.update(filtered_links)

                        if not direct_links_found and not any(
                            key.startswith("_MEDIAFIRE_") for key in page_comic_links
                        ):
                            if self.verbose:
                                console.print(f"No link found: {url}")
                            getinfo_logger.warning("No download link found for %s", url)
                    except Exception as exc:
                        error_msg = f"Error processing page {url}: {exc}"
                        console.print(error_msg)
                        getinfo_logger.error(error_msg, exc_info=True)

            tasks = [process_page(url, title) for url, title in self.page_links.items()]
            await asyncio.gather(*tasks)

        getinfo_logger.info("Found %s download links in total", len(self.comic_links))
