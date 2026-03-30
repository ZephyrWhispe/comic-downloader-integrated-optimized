from parsers.xoxocomic_parser import XoxoComicParser

from .base import SiteModule


SITE = SiteModule(
    key="xoxocomic.com",
    display_name="XoxoComic",
    domains=("xoxocomic.com",),
    parser_factory=XoxoComicParser,
    default_max_workers=3,
    default_max_retries=4,
    default_download_delay=0.2,
    default_request_timeout=35.0,
    default_chapter_failure_policy="continue",
    notes="分页较多，默认降低并发避免触发站点限速。",
)
