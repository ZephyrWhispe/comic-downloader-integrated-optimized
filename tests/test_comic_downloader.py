import unittest
from tempfile import TemporaryDirectory

from core.comic_downloader import ComicDownloader


class DummyParser:
    def __init__(self):
        self.closed = False

    def get_comic_info(self, url):
        return "Test Comic", [("Chapter 1", "https://example.com/ch1")]

    def close(self):
        self.closed = True


class DummyImageParser:
    def __init__(self):
        self.calls = []

    def download_image(self, image_url, save_path, headers=None, timeout=30):
        self.calls.append(
            {
                "image_url": image_url,
                "save_path": save_path,
                "headers": headers or {},
                "timeout": timeout,
            }
        )
        with open(save_path, "wb") as file_handle:
            file_handle.write(b"fake-image")
        return True


class ComicDownloaderRunTests(unittest.TestCase):
    def test_run_passes_resolved_parser_into_download_and_closes_it(self):
        downloader = ComicDownloader.__new__(ComicDownloader)
        dummy = DummyParser()
        downloader.site_modules = []
        downloader.parsers = {"example.com": dummy}

        captured = {}

        def fake_download(comic_title, chapter_name, chapter_url, parser, progress_callback=None, max_workers=None):
            captured["comic_title"] = comic_title
            captured["chapter_name"] = chapter_name
            captured["chapter_url"] = chapter_url
            captured["parser"] = parser
            return True

        downloader.download_chapter = fake_download

        result = ComicDownloader.run(downloader, "https://example.com/book")

        self.assertTrue(result)
        self.assertEqual("Test Comic", captured["comic_title"])
        self.assertEqual("Chapter 1", captured["chapter_name"])
        self.assertEqual("https://example.com/ch1", captured["chapter_url"])
        self.assertIs(dummy, captured["parser"])
        self.assertTrue(dummy.closed)

    def test_download_image_uses_parser_download_hook(self):
        downloader = ComicDownloader.__new__(ComicDownloader)
        parser = DummyImageParser()

        with TemporaryDirectory() as temp_dir:
            image_path = f"{temp_dir}/page-001.jpg"
            result = ComicDownloader.download_image(
                downloader,
                "https://img.example.com/page-001.jpg",
                image_path,
                parser=parser,
                referer="https://example.com/chapter-1",
                delay_seconds=0,
                request_timeout=42,
            )

            self.assertTrue(result)
            self.assertEqual(1, len(parser.calls))
            self.assertEqual("https://img.example.com/page-001.jpg", parser.calls[0]["image_url"])
            self.assertEqual("https://example.com/chapter-1", parser.calls[0]["headers"]["Referer"])
            self.assertEqual(42, parser.calls[0]["timeout"])


if __name__ == "__main__":
    unittest.main()
