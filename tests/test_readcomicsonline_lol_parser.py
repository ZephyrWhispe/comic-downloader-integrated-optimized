import json
import unittest

from parsers.readcomicsonline_lol_parser import ReadComicsOnlineLolParser


class DummyResponse:
    def __init__(self, url, text, status_code=200):
        self.url = url
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class DummyScraper:
    def __init__(self, responses):
        self.responses = responses

    def get(self, url, timeout=30):
        return self.responses[url]


def next_push(payload):
    return f"<script>self.__next_f.push([1,{json.dumps(payload)}])</script>"


class ReadComicsOnlineLolParserTests(unittest.TestCase):
    def test_sanitize_title_preserves_readable_separator(self):
        parser = ReadComicsOnlineLolParser()

        self.assertEqual("Superman - Godfall", parser._sanitize_title("Superman: Godfall"))

    def test_get_comic_info_extracts_issue_links_from_next_payload(self):
        parser = ReadComicsOnlineLolParser()
        series_url = "https://readcomicsonline.lol/comic/test-comic"
        html = f"""
        <html>
            <head>
                <title>Read Test Comic Online Free | ReadComicsOnline</title>
            </head>
            <body>
                <script type="application/ld+json">{json.dumps({"@context": "https://schema.org", "@type": "ComicSeries", "name": "Test Comic"})}</script>
                {next_push('66:{"issues":[{"id":"1","title":"Issue 001","slug":"issue-001"},{"id":"2","title":"Annual 1","slug":"annual-1"}],"comicSlug":"test-comic"}')}
            </body>
        </html>
        """
        parser.scraper = DummyScraper({series_url: DummyResponse(series_url, html)})

        title, chapters = parser.get_comic_info(series_url)

        self.assertEqual("Test Comic", title)
        self.assertEqual(
            [
                ("Issue 001", "https://readcomicsonline.lol/comic/test-comic/issue-001"),
                ("Annual 1", "https://readcomicsonline.lol/comic/test-comic/annual-1"),
            ],
            chapters,
        )

    def test_get_comic_info_for_issue_url_returns_current_issue(self):
        parser = ReadComicsOnlineLolParser()
        issue_url = "https://readcomicsonline.lol/comic/test-comic/issue-001"
        html = f"""
        <html>
            <head>
                <title>Issue 001 | Test Comic | ReadComicsOnline</title>
            </head>
            <body>
                <script type="application/ld+json">{json.dumps({"@context": "https://schema.org", "@type": "ComicIssue", "name": "Issue 001", "isPartOf": {"name": "Test Comic"}})}</script>
            </body>
        </html>
        """
        parser.scraper = DummyScraper({issue_url: DummyResponse(issue_url, html)})

        title, chapters = parser.get_comic_info(issue_url)

        self.assertEqual("Test Comic", title)
        self.assertEqual([("Issue 001", issue_url)], chapters)

    def test_get_chapter_images_extracts_pages_from_next_payload(self):
        parser = ReadComicsOnlineLolParser()
        issue_url = "https://readcomicsonline.lol/comic/test-comic/issue-001"
        html = f"""
        <html>
            <body>
                {next_push('59:{"pages":[{"id":"p2","pageNumber":2,"url":"https://cdn.readcomicsonline.lol/pages/test-comic/issue-001/p002.webp"},{"id":"p1","pageNumber":1,"url":"https://cdn.readcomicsonline.lol/pages/test-comic/issue-001/p001.webp"}]}')}
            </body>
        </html>
        """
        parser.scraper = DummyScraper({issue_url: DummyResponse(issue_url, html)})

        images = parser.get_chapter_images(issue_url)

        self.assertEqual(
            [
                "https://cdn.readcomicsonline.lol/pages/test-comic/issue-001/p001.webp",
                "https://cdn.readcomicsonline.lol/pages/test-comic/issue-001/p002.webp",
            ],
            images,
        )


if __name__ == "__main__":
    unittest.main()
