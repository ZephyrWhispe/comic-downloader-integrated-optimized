import unittest

from core.getcomics_gui_helpers import (
    collect_selected_getcomics_results,
    format_getcomics_results_for_clipboard,
    remove_getcomics_results,
    upsert_getcomics_results,
)


class GetComicsGuiHelpersTests(unittest.TestCase):
    def test_collect_selected_getcomics_results_filters_invalid_indices_and_duplicates(self):
        results = [
            ("https://example.com/a", "Batman #1"),
            ("https://example.com/b", "Batman #2"),
            ("https://example.com/b", "Batman #2 Duplicate"),
            ("", "Missing URL"),
        ]

        selected = collect_selected_getcomics_results(
            results,
            [1, "0", 99, -1, "bad", 2, 3],
        )

        self.assertEqual(
            [
                ("https://example.com/b", "Batman #2"),
                ("https://example.com/a", "Batman #1"),
            ],
            selected,
        )

    def test_format_getcomics_results_for_clipboard_builds_readable_blocks(self):
        clipboard_text = format_getcomics_results_for_clipboard(
            [
                ("https://example.com/a", "Batman #1"),
                ("", "Missing URL"),
                ("https://example.com/b", "Batman #2"),
            ]
        )

        self.assertEqual(
            "Batman #1\nhttps://example.com/a\n\nBatman #2\nhttps://example.com/b",
            clipboard_text,
        )

    def test_upsert_getcomics_results_prepends_new_items_and_deduplicates(self):
        merged = upsert_getcomics_results(
            [
                ("https://example.com/a", "Batman #1"),
                ("https://example.com/b", "Batman #2"),
            ],
            [
                ("https://example.com/c", "Batman #3"),
                ("https://example.com/b", "Batman #2 updated"),
            ],
        )

        self.assertEqual(
            [
                ("https://example.com/c", "Batman #3"),
                ("https://example.com/b", "Batman #2 updated"),
                ("https://example.com/a", "Batman #1"),
            ],
            merged,
        )

    def test_remove_getcomics_results_filters_by_url(self):
        remaining = remove_getcomics_results(
            [
                ("https://example.com/a", "Batman #1"),
                ("https://example.com/b", "Batman #2"),
                ("https://example.com/c", "Batman #3"),
            ],
            [
                ("https://example.com/b", "Batman #2"),
                ("https://example.com/missing", "Missing"),
            ],
        )

        self.assertEqual(
            [
                ("https://example.com/a", "Batman #1"),
                ("https://example.com/c", "Batman #3"),
            ],
            remaining,
        )


if __name__ == "__main__":
    unittest.main()
