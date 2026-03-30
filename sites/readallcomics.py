from parsers.readallcomics_parser import ReadAllComicsParser

from .base import SiteModule


SITE = SiteModule(
    key="readallcomics.com",
    display_name="ReadAllComics",
    domains=("readallcomics.com",),
    parser_factory=ReadAllComicsParser,
    default_max_workers=6,
    default_max_retries=3,
    default_download_delay=0.1,
    default_request_timeout=30.0,
    default_chapter_failure_policy="continue",
    notes="常规站点，适合默认并发下载。",
)
