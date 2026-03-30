import unittest

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


if __name__ == "__main__":
    unittest.main()
