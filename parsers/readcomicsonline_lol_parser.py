import json
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .base_parser import BaseComicParser
from .base_parser import logger


class ReadComicsOnlineLolParser(BaseComicParser):
    """Parser for readcomicsonline.lol."""

    BASE_URL = "https://readcomicsonline.lol"
    NEXT_PUSH_PATTERN = re.compile(
        r"self\.__next_f\.push\(\[\d+,(?P<payload>\".*\")\]\)\s*;?\s*$",
        re.DOTALL,
    )

    def _sanitize_title(self, value):
        sanitized = (value or "").strip()
        sanitized = sanitized.replace(":", " - ")
        sanitized = re.sub(r'[\\/*?"<>|]+', " ", sanitized)
        sanitized = re.sub(r"\s+", " ", sanitized).strip(" .")
        return sanitized

    def _extract_series_slug(self, url):
        path_parts = [part for part in urlparse(url).path.split("/") if part]
        if len(path_parts) >= 2 and path_parts[0] == "comic":
            return path_parts[1]
        return ""

    def _load_json_ld(self, soup):
        items = []
        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            raw_text = script.string or script.get_text()
            if not raw_text:
                continue
            try:
                payload = json.loads(raw_text)
            except json.JSONDecodeError:
                continue

            if isinstance(payload, dict):
                items.append(payload)
            elif isinstance(payload, list):
                items.extend(item for item in payload if isinstance(item, dict))

        return items

    def _extract_next_payloads(self, html):
        soup = BeautifulSoup(html, "html.parser")
        payloads = []

        for script in soup.find_all("script"):
            raw_text = script.string or script.get_text()
            if not raw_text or "self.__next_f.push" not in raw_text:
                continue

            match = self.NEXT_PUSH_PATTERN.search(raw_text.strip())
            if not match:
                continue

            try:
                payload = json.loads(match.group("payload"))
            except json.JSONDecodeError:
                continue

            if isinstance(payload, str):
                payloads.append(payload)

        return payloads

    def _extract_json_array(self, text, start_index):
        if start_index < 0 or start_index >= len(text) or text[start_index] != "[":
            return None

        depth = 0
        in_string = False
        escaped = False

        for index in range(start_index, len(text)):
            char = text[index]

            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
                continue

            if char == "[":
                depth += 1
            elif char == "]":
                depth -= 1
                if depth == 0:
                    return text[start_index : index + 1]

        return None

    def _extract_array_from_payloads(self, payloads, key):
        marker = f'"{key}":['

        for payload in payloads:
            offset = payload.find(marker)
            while offset != -1:
                array_start = offset + len(f'"{key}":')
                raw_array = self._extract_json_array(payload, array_start)
                if raw_array:
                    try:
                        return json.loads(raw_array)
                    except json.JSONDecodeError:
                        pass

                offset = payload.find(marker, offset + 1)

        return []

    def _extract_series_title(self, soup, url):
        for payload in self._load_json_ld(soup):
            if payload.get("@type") == "ComicSeries" and payload.get("name"):
                return self._sanitize_title(payload["name"])

            if payload.get("@type") == "ComicIssue":
                part_of = payload.get("isPartOf")
                if isinstance(part_of, dict) and part_of.get("name"):
                    return self._sanitize_title(part_of["name"])

        og_title = soup.find("meta", {"property": "og:title"})
        if og_title and og_title.get("content"):
            title = og_title["content"].strip()
            title = re.sub(r"^\s*Read\s+", "", title, flags=re.IGNORECASE)
            title = re.sub(r"\s+Online\s+Free\s*$", "", title, flags=re.IGNORECASE)
            if title:
                return self._sanitize_title(title)

        title_tag = soup.find("title")
        if title_tag:
            title = title_tag.get_text(" ", strip=True)
            title = re.sub(r"^\s*Read\s+", "", title, flags=re.IGNORECASE)
            title = re.sub(r"\s+Online\s+Free\s*\|\s*ReadComicsOnline\s*$", "", title, flags=re.IGNORECASE)
            title = re.sub(r"\s*\|\s*ReadComicsOnline\s*$", "", title, flags=re.IGNORECASE)
            if title:
                return self._sanitize_title(title)

        slug = self._extract_series_slug(url)
        if slug:
            return self._sanitize_title(slug.replace("-", " ").title())

        return "Unknown Comic"

    def _extract_issue_title(self, soup, url):
        for payload in self._load_json_ld(soup):
            if payload.get("@type") == "ComicIssue" and payload.get("name"):
                return self._sanitize_title(payload["name"])

        title_tag = soup.find("title")
        if title_tag:
            title = title_tag.get_text(" ", strip=True)
            title = title.split("|", 1)[0].strip()
            if title:
                return self._sanitize_title(title)

        slug = urlparse(url).path.rstrip("/").split("/")[-1]
        if slug:
            return self._sanitize_title(slug.replace("-", " ").title())

        return "Unknown Issue"

    def _build_issue_links(self, issues, series_slug):
        links = []
        seen = set()

        for issue in issues:
            if not isinstance(issue, dict):
                continue

            issue_slug = str(issue.get("slug") or "").strip()
            issue_title = self._sanitize_title(str(issue.get("title") or "").strip())
            if not issue_slug or not issue_title:
                continue

            issue_url = urljoin(self.BASE_URL, f"/comic/{series_slug}/{issue_slug}")
            if issue_url in seen:
                continue

            seen.add(issue_url)
            links.append((issue_title, issue_url))

        return links

    def _extract_issue_links_from_dom(self, soup, series_slug):
        prefix = f"/comic/{series_slug}/"
        links = []
        seen = set()

        for anchor in soup.find_all("a", href=True):
            href = anchor.get("href", "").strip()
            if not href.startswith(prefix):
                continue

            suffix = href[len(prefix) :].strip("/")
            if not suffix or "/" in suffix:
                continue

            issue_url = urljoin(self.BASE_URL, href)
            issue_title = self._sanitize_title(anchor.get_text(" ", strip=True) or suffix)
            if issue_url in seen or not issue_title:
                continue

            seen.add(issue_url)
            links.append((issue_title, issue_url))

        return links

    def get_comic_info(self, url):
        logger.info("Fetching ReadComicsOnline.lol comic info: %s", url)
        try:
            response = self.scraper.get(url, timeout=30)
            response.raise_for_status()

            resolved_url = response.url
            soup = BeautifulSoup(response.text, "html.parser")
            title = self._extract_series_title(soup, resolved_url)

            path_parts = [part for part in urlparse(resolved_url).path.split("/") if part]
            if len(path_parts) >= 3 and path_parts[0] == "comic":
                issue_title = self._extract_issue_title(soup, resolved_url)
                return title, [(issue_title, resolved_url)]

            series_slug = self._extract_series_slug(resolved_url)
            payloads = self._extract_next_payloads(response.text)
            issues = self._extract_array_from_payloads(payloads, "issues")
            chapter_links = self._build_issue_links(issues, series_slug)

            if not chapter_links and series_slug:
                chapter_links = self._extract_issue_links_from_dom(soup, series_slug)

            return title, chapter_links
        except Exception as exc:
            logger.error("Failed to fetch ReadComicsOnline.lol comic info: %s", exc)
            return None, []

    def get_chapter_images(self, chapter_url, progress_callback=None):
        logger.info("Fetching ReadComicsOnline.lol chapter images: %s", chapter_url)
        try:
            response = self.scraper.get(chapter_url, timeout=30)
            response.raise_for_status()

            payloads = self._extract_next_payloads(response.text)
            pages = self._extract_array_from_payloads(payloads, "pages")
            ordered_pages = sorted(
                (
                    page
                    for page in pages
                    if isinstance(page, dict) and page.get("url")
                ),
                key=lambda page: int(page.get("pageNumber") or 0),
            )

            image_urls = []
            seen = set()
            for page in ordered_pages:
                image_url = str(page.get("url") or "").strip()
                if not image_url:
                    continue
                if not image_url.startswith(("http://", "https://")):
                    image_url = urljoin(response.url, image_url)
                if image_url in seen:
                    continue

                seen.add(image_url)
                image_urls.append(image_url)

            return image_urls
        except Exception as exc:
            logger.error("Failed to fetch ReadComicsOnline.lol chapter images: %s", exc)
            return []

    def get_site_name(self):
        return "readcomicsonline.lol"
