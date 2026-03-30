from parsers.batcave_biz_parser import BatCaveBizParser

from .base import SiteModule


SITE = SiteModule(
    key="batcave.biz",
    display_name="BatCave",
    domains=("batcave.biz",),
    parser_factory=BatCaveBizParser,
    default_max_workers=2,
    default_max_retries=4,
    default_download_delay=0.15,
    default_request_timeout=45.0,
    default_chapter_failure_policy="continue",
    requires_browser=True,
    notes="Cloudflare 站点。先通过浏览器验证，再复用 cookies 下载图片。",
)
