import unittest
from bs4 import BeautifulSoup

from core.getinfo import GetComics


class GetComicsFilterTests(unittest.TestCase):
    def test_page_and_download_filters_respect_year_and_issue_range(self):
        comics = GetComics("Batman", 10, False, min_issue=2, max_issue=5, date=2024)

        page_entries = {
            "u1": {"title": "Batman #1 (2023)", "year": 2023},
            "u2": {"title": "Batman #4 (2024)", "year": 2024},
            "u3": {"title": "Batman #7 (2025)", "year": 2025},
        }
        filtered_pages = comics._apply_page_filters(page_entries)
        self.assertEqual({"u2": "Batman #4 (2024)"}, filtered_pages)

        download_links = {
            "u1": "Batman #1 (2023)",
            "u2": "Batman #4 (2024)",
            "u3": "Batman #7 (2025)",
        }
        filtered_downloads = comics._apply_download_filters(download_links)
        self.assertEqual({"u2": "Batman #4 (2024)"}, filtered_downloads)

    def test_reversed_issue_range_is_normalized(self):
        comics = GetComics("Batman", 10, False, min_issue=8, max_issue=3)
        self.assertEqual(3, comics.min_issue)
        self.assertEqual(8, comics.max_issue)

    def test_get_loaded_page_reflects_last_completed_search_page(self):
        comics = GetComics("Batman", 10, False)
        self.assertEqual(0, comics.get_loaded_page())
        comics.page = 3
        self.assertEqual(2, comics.get_loaded_page())

    def test_extract_article_year_falls_back_to_title_and_body_year(self):
        comics = GetComics("Batman", 10, False, date=2024)
        article = BeautifulSoup(
            """
            <article>
                <h1 class="post-title"><a href="https://example.com">Batman Deluxe Edition (2018)</a></h1>
                <time>3 days ago</time>
                <div>Year : 2018 | Size : 940 MB</div>
            </article>
            """,
            "html.parser",
        ).find("article")

        self.assertEqual(2018, comics._extract_article_year(article))

    def test_extract_post_download_links_prefers_current_direct_hosts(self):
        comics = GetComics("Batman", 10, False)
        soup = BeautifulSoup(
            """
            <html><body>
                <a href="https://getcomics.org/dlds/example-pixeldrain" title="PIXELDRAIN">PIXELDRAIN</a>
                <a href="https://getcomics.org/dlds/example-mega" title="MEGA">MEGA</a>
            </body></html>
            """,
            "html.parser",
        )

        links = comics._extract_post_download_links(soup, "Batman Example")

        self.assertEqual(
            {"https://getcomics.org/dlds/example-pixeldrain": "Batman Example"},
            links,
        )


if __name__ == "__main__":
    unittest.main()
