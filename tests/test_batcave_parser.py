import unittest
from unittest.mock import patch

from parsers.batcave_biz_parser import BatCaveBizParser
from sites.registry import get_site_module


class FakeBrowserManager:
    def __init__(self, headless=True):
        self.headless = headless
        self.closed = False

    def close(self):
        self.closed = True


class BatCaveParserHelperTests(unittest.TestCase):
    def test_build_chapter_links_uses_reader_route(self):
        parser = BatCaveBizParser.__new__(BatCaveBizParser)

        chapter_links = parser._build_chapter_links(
            24320,
            [
                {"id": 167946, "title_en": "Robin (1993) Issue #1000000"},
                {"id": 167945, "title": "Robin (1993) Issue #0"},
                {"title": "Missing id should be skipped"},
            ],
        )

        self.assertEqual(
            [
                ("Robin (1993) Issue #1000000", "https://batcave.biz/reader/24320/167946"),
                ("Robin (1993) Issue #0", "https://batcave.biz/reader/24320/167945"),
            ],
            chapter_links,
        )

    def test_sanitize_title_replaces_windows_invalid_chars(self):
        parser = BatCaveBizParser.__new__(BatCaveBizParser)

        self.assertEqual(
            "Robin _ Special Edition_ _One_",
            parser._sanitize_title('Robin / Special Edition: "One"'),
        )
        self.assertEqual("Unknown Comic", parser._sanitize_title("   "))

    def test_site_registry_matches_batcave(self):
        site = get_site_module("https://batcave.biz/24320-robin-1993-2009.html")

        self.assertIsNotNone(site)
        self.assertEqual("batcave.biz", site.key)

    def test_browser_manager_is_isolated_per_thread(self):
        with patch("parsers.batcave_biz_parser.BrowserManager", FakeBrowserManager):
            parser = BatCaveBizParser()

            with patch("parsers.batcave_biz_parser.threading.get_ident", return_value=101):
                manager_a = parser._get_browser_manager()
                manager_a_repeat = parser._get_browser_manager()

            with patch("parsers.batcave_biz_parser.threading.get_ident", return_value=202):
                manager_b = parser._get_browser_manager()

            self.assertIs(manager_a, manager_a_repeat)
            self.assertIsNot(manager_a, manager_b)

            with patch("parsers.batcave_biz_parser.threading.get_ident", return_value=101):
                parser.close()

            self.assertTrue(manager_a.closed)
            self.assertFalse(manager_b.closed)

            parser.close_all()
            self.assertTrue(manager_b.closed)


if __name__ == "__main__":
    unittest.main()
