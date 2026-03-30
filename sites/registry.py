from .batcave import SITE as BATCAVE_SITE
from .readallcomics import SITE as READALLCOMICS_SITE
from .readcomiconline_li import SITE as READCOMICONLINE_LI_SITE
from .readcomicsonline_ru import SITE as READCOMICSONLINE_RU_SITE
from .xoxocomic import SITE as XOXOCOMIC_SITE

SITE_MODULES = (
    BATCAVE_SITE,
    READALLCOMICS_SITE,
    READCOMICONLINE_LI_SITE,
    READCOMICSONLINE_RU_SITE,
    XOXOCOMIC_SITE,
)


def get_site_module(url: str):
    for site in SITE_MODULES:
        if site.matches(url):
            return site
    return None
