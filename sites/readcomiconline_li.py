from parsers.readcomiconline_li_parser import ReadComicOnlineLiParser

from .base import SiteModule


SITE = SiteModule(
    key="readcomiconline.li",
    display_name="ReadComicOnline.li",
    domains=("readcomiconline.li",),
    parser_factory=ReadComicOnlineLiParser,
    default_max_workers=4,
    default_max_retries=4,
    default_download_delay=0.12,
    default_request_timeout=40.0,
    default_chapter_failure_policy="continue",
    requires_browser=True,
    notes="章节图片列表需要浏览器滚动辅助提取。",
)
