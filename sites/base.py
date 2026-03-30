from dataclasses import dataclass
from typing import Callable
from urllib.parse import urljoin


@dataclass(frozen=True)
class SiteModule:
    key: str
    display_name: str
    domains: tuple[str, ...]
    parser_factory: Callable[[], object]
    match_domains: tuple[str, ...] | None = None
    default_max_workers: int = 6
    default_max_retries: int = 3
    default_download_delay: float = 0.1
    default_request_timeout: float = 30.0
    default_chapter_failure_policy: str = "continue"
    requires_browser: bool = False
    notes: str = ""

    def matches(self, url: str) -> bool:
        if not url:
            return False
        candidate_domains = self.match_domains or self.domains
        return any(domain in url for domain in candidate_domains)

    def create_parser(self):
        return self.parser_factory()

    def resolve_chapter_url(self, base_url: str, chapter_url: str) -> str:
        if not chapter_url:
            return chapter_url

        chapter_url = chapter_url.strip()
        if chapter_url.startswith(("http://", "https://")):
            return chapter_url

        return urljoin(base_url, chapter_url)
