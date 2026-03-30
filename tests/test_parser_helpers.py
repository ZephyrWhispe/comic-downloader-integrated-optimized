import unittest

from bs4 import BeautifulSoup

from parsers.readallcomics_parser import ReadAllComicsParser
from parsers.readcomicsonline_ru_parser import ReadComicsOnlineRuParser
from parsers.xoxocomic_parser import XoxoComicParser


class ParserHelperTests(unittest.TestCase):
    def test_readallcomics_category_chapter_extraction(self):
        parser = ReadAllComicsParser()
        soup = BeautifulSoup(
            """
            <html><body>
                <h1>Gunslinger Spawn</h1>
                <a href="/gunslinger-spawn-51-2026/">#051 (2026)</a>
                <a href="/category/gunslinger-spawn/">Category</a>
            </body></html>
            """,
            "html.parser",
        )

        chapters = parser._extract_category_chapters(
            soup,
            "https://readallcomics.com/category/gunslinger-spawn/",
            "Gunslinger Spawn",
        )

        self.assertEqual(
            [("Gunslinger Spawn #051 (2026)", "https://readallcomics.com/gunslinger-spawn-51-2026/")],
            chapters,
        )

    def test_readcomicsonline_ru_chapter_extraction(self):
        parser = ReadComicsOnlineRuParser()
        soup = BeautifulSoup(
            """
            <html><body>
                <a href="/comic/batman-2016/162">Batman (2016-) #162</a>
                <a href="/comic/batman-2016/Annual5">Batman (2016-) #Annual 5</a>
                <a href="/comic/other-series/1">Other Series #1</a>
            </body></html>
            """,
            "html.parser",
        )

        chapters = parser._extract_chapter_links(
            soup,
            "https://readcomicsonline.ru/comic/batman-2016",
        )

        self.assertEqual(
            [
                ("Batman (2016-) #162", "https://readcomicsonline.ru/comic/batman-2016/162"),
                ("Batman (2016-) #Annual 5", "https://readcomicsonline.ru/comic/batman-2016/Annual5"),
            ],
            chapters,
        )

    def test_readcomicsonline_ru_relative_image_normalization(self):
        parser = ReadComicsOnlineRuParser()
        image_url = parser._normalize_image_url(
            "https://readcomicsonline.ru/comic/batman-2016/157",
            "01.jpg",
        )

        self.assertEqual(
            "https://readcomicsonline.ru/uploads/manga/batman-2016/chapters/157/01.jpg",
            image_url,
        )

    def test_xoxocomic_page_url_and_image_extraction(self):
        parser = XoxoComicParser()
        soup = BeautifulSoup(
            """
            <html><body>
                <select id="selectPage">
                    <option value="https://xoxocomic.com/comic/test/issue-1/1" selected>1</option>
                    <option value="https://xoxocomic.com/comic/test/issue-1/2">2</option>
                </select>
                <img class="single-page lazy" data-original="https://xoxocomic.com/comic/test/issue-1/111/1.jpg" />
            </body></html>
            """,
            "html.parser",
        )

        page_urls = parser._extract_page_urls(soup, "https://xoxocomic.com/comic/test/issue-1")
        image_url = parser._extract_page_image(soup, page_urls[0])

        self.assertEqual(
            [
                "https://xoxocomic.com/comic/test/issue-1/1",
                "https://xoxocomic.com/comic/test/issue-1/2",
            ],
            page_urls,
        )
        self.assertEqual("https://xoxocomic.com/comic/test/issue-1/111/1.jpg", image_url)


if __name__ == "__main__":
    unittest.main()
