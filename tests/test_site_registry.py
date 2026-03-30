import unittest
import json
import os
from tempfile import TemporaryDirectory

from core.comic_downloader import ComicDownloader


class DummySiteModule:
    def __init__(self):
        self.key = "example.com"
        self.display_name = "Example Site"
        self.domains = ("example.com", "mirror.example.com")
        self.default_max_workers = 4
        self.default_max_retries = 5
        self.default_download_delay = 0.25
        self.default_request_timeout = 35.0
        self.default_chapter_failure_policy = "continue"
        self.requires_browser = True
        self.notes = "Uses browser-assisted extraction."

    def resolve_chapter_url(self, base_url, chapter_url):
        return f"{base_url.rstrip('/')}/{chapter_url.lstrip('/')}"


class ComicDownloaderSiteRegistryTests(unittest.TestCase):
    def test_resolve_chapter_url_uses_site_module(self):
        downloader = ComicDownloader.__new__(ComicDownloader)
        downloader.parsers = {"example.com": object()}
        downloader.get_site_module = lambda url: DummySiteModule() if "example.com" in (url or "") else None

        resolved = ComicDownloader.resolve_chapter_url(
            downloader,
            "https://example.com/series",
            "/chapter-1",
        )

        self.assertEqual("https://example.com/series/chapter-1", resolved)

    def test_describe_site_returns_display_name_and_domains(self):
        downloader = ComicDownloader.__new__(ComicDownloader)
        downloader.site_modules = [DummySiteModule()]
        downloader.parsers = {"example.com": object()}
        downloader.get_site_module = lambda url: DummySiteModule() if "example.com" in (url or "") else None

        site_info = ComicDownloader.describe_site(downloader, "https://example.com/series")

        self.assertEqual(
            {
                "key": "example.com",
                "display_name": "Example Site",
                "domains": ("example.com", "mirror.example.com"),
                "default_max_workers": 4,
                "default_max_retries": 5,
                "default_download_delay": 0.25,
                "default_request_timeout": 35.0,
                "default_chapter_failure_policy": "continue",
                "override_max_workers": None,
                "override_max_retries": None,
                "override_download_delay": None,
                "override_request_timeout": None,
                "override_chapter_failure_policy": None,
                "max_workers": 4,
                "max_retries": 5,
                "download_delay": 0.25,
                "request_timeout": 35.0,
                "chapter_failure_policy": "continue",
                "has_override": False,
                "requires_browser": True,
                "notes": "Uses browser-assisted extraction.",
            },
            site_info,
        )

    def test_supported_sites_summary_lists_registered_modules(self):
        downloader = ComicDownloader.__new__(ComicDownloader)
        downloader.site_modules = [DummySiteModule()]

        summary = ComicDownloader.get_supported_sites_summary(downloader)

        self.assertEqual("Example Site (example.com, mirror.example.com，默认并发 4，浏览器辅助)", summary)

    def test_get_default_max_workers_uses_site_module_setting(self):
        downloader = ComicDownloader.__new__(ComicDownloader)
        downloader.site_modules = [DummySiteModule()]
        downloader.parsers = {"example.com": object()}
        downloader.site_overrides = {}
        downloader.get_site_module = lambda url: DummySiteModule() if "example.com" in (url or "") else None

        self.assertEqual(4, ComicDownloader.get_default_max_workers(downloader, "https://example.com/series"))
        self.assertEqual(5, ComicDownloader.get_default_max_retries(downloader, "https://example.com/series"))
        self.assertEqual(0.25, ComicDownloader.get_default_download_delay(downloader, "https://example.com/series"))
        self.assertEqual(35.0, ComicDownloader.get_default_request_timeout(downloader, "https://example.com/series"))
        self.assertEqual("continue", ComicDownloader.get_default_chapter_failure_policy(downloader, "https://example.com/series"))
        self.assertEqual(6, ComicDownloader.get_default_max_workers(downloader, "https://unknown-site.example/series"))
        self.assertEqual(3, ComicDownloader.get_default_max_retries(downloader, "https://unknown-site.example/series"))
        self.assertEqual(0.1, ComicDownloader.get_default_download_delay(downloader, "https://unknown-site.example/series"))
        self.assertEqual(30.0, ComicDownloader.get_default_request_timeout(downloader, "https://unknown-site.example/series"))
        self.assertEqual("continue", ComicDownloader.get_default_chapter_failure_policy(downloader, "https://unknown-site.example/series"))

    def test_set_site_override_updates_effective_worker_count(self):
        downloader = ComicDownloader.__new__(ComicDownloader)
        downloader.site_modules = [DummySiteModule()]
        downloader.parsers = {"example.com": object()}
        downloader.site_overrides = {}
        downloader.save_site_overrides = lambda: True

        site_info = ComicDownloader.set_site_override(
            downloader,
            "example.com",
            max_workers=2,
            max_retries=7,
            download_delay=0.4,
            request_timeout=55.0,
            chapter_failure_policy="stop",
        )

        self.assertEqual(
            {
                "example.com": {
                    "max_workers": 2,
                    "max_retries": 7,
                    "download_delay": 0.4,
                    "request_timeout": 55.0,
                    "chapter_failure_policy": "stop",
                }
            },
            downloader.site_overrides,
        )
        self.assertTrue(site_info["has_override"])
        self.assertEqual(2, site_info["max_workers"])
        self.assertEqual(7, site_info["max_retries"])
        self.assertEqual(0.4, site_info["download_delay"])
        self.assertEqual(55.0, site_info["request_timeout"])
        self.assertEqual("stop", site_info["chapter_failure_policy"])

    def test_reset_site_override_restores_default_worker_count(self):
        downloader = ComicDownloader.__new__(ComicDownloader)
        downloader.site_modules = [DummySiteModule()]
        downloader.parsers = {"example.com": object()}
        downloader.site_overrides = {
            "example.com": {
                "max_workers": 2,
                "max_retries": 7,
                "download_delay": 0.4,
                "request_timeout": 55.0,
                "chapter_failure_policy": "stop",
            }
        }
        downloader.save_site_overrides = lambda: True

        site_info = ComicDownloader.reset_site_override(downloader, "example.com")

        self.assertEqual({}, downloader.site_overrides)
        self.assertFalse(site_info["has_override"])
        self.assertEqual(4, site_info["max_workers"])
        self.assertEqual(5, site_info["max_retries"])
        self.assertEqual(0.25, site_info["download_delay"])
        self.assertEqual(35.0, site_info["request_timeout"])
        self.assertEqual("continue", site_info["chapter_failure_policy"])

    def test_load_and_save_site_overrides_round_trip(self):
        downloader = ComicDownloader.__new__(ComicDownloader)
        downloader.site_modules = [DummySiteModule()]
        downloader.parsers = {"example.com": object()}

        with TemporaryDirectory() as temp_dir:
            config_path = os.path.join(temp_dir, ".site_overrides.json")
            downloader.site_overrides_path = config_path
            downloader.site_overrides = {
                "example.com": {
                    "max_workers": 3,
                    "max_retries": 6,
                    "download_delay": 0.3,
                    "request_timeout": 45.0,
                    "chapter_failure_policy": "stop",
                }
            }

            self.assertTrue(ComicDownloader.save_site_overrides(downloader))

            with open(config_path, "r", encoding="utf-8") as file_handle:
                payload = json.load(file_handle)

            self.assertEqual(
                {
                    "sites": {
                        "example.com": {
                            "max_workers": 3,
                            "max_retries": 6,
                            "download_delay": 0.3,
                            "request_timeout": 45.0,
                            "chapter_failure_policy": "stop",
                        }
                    }
                },
                payload,
            )

            downloader.site_overrides = {}
            loaded = ComicDownloader.load_site_overrides(downloader)
            self.assertEqual(
                {
                    "example.com": {
                        "max_workers": 3,
                        "max_retries": 6,
                        "download_delay": 0.3,
                        "request_timeout": 45.0,
                        "chapter_failure_policy": "stop",
                    }
                },
                loaded,
            )


if __name__ == "__main__":
    unittest.main()
