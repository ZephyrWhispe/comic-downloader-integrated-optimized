from parsers.readcomicsonline_lol_parser import ReadComicsOnlineLolParser

from .base import SiteModule


SITE = SiteModule(
    key="readcomicsonline.lol",
    display_name="ReadComicsOnline.lol",
    domains=("readcomicsonline.lol",),
    parser_factory=ReadComicsOnlineLolParser,
    match_domains=("readcomicsonline.lol", "cdn.readcomicsonline.lol"),
    default_max_workers=6,
    default_max_retries=3,
    default_download_delay=0.1,
    default_request_timeout=30.0,
    default_chapter_failure_policy="continue",
    notes="无需浏览器；直接从 Next.js 服务端渲染数据中提取章节与页图 URL。",
)
