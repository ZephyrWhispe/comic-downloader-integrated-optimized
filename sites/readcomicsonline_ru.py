from parsers.readcomicsonline_ru_parser import ReadComicsOnlineRuParser

from .base import SiteModule


SITE = SiteModule(
    key="readcomicsonline.ru",
    display_name="ReadComicsOnline.ru",
    domains=("readcomicsonline.ru",),
    parser_factory=ReadComicsOnlineRuParser,
    default_max_workers=6,
    default_max_retries=3,
    default_download_delay=0.1,
    default_request_timeout=30.0,
    default_chapter_failure_policy="continue",
    notes="常规站点，图片链接可直接提取。",
)
