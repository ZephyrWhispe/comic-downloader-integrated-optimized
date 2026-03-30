import json
import os
import unittest
from tempfile import TemporaryDirectory

from core.gui_state import (
    build_getcomics_history_label,
    load_gui_state,
    load_getcomics_favorites_file,
    normalize_cached_getcomics_results,
    normalize_gui_state,
    normalize_recent_getcomics_searches,
    save_gui_state,
    save_getcomics_favorites_file,
    upsert_recent_getcomics_search,
)


class GuiStateTests(unittest.TestCase):
    def test_normalize_gui_state_applies_defaults_and_filters_invalid_entries(self):
        state = normalize_gui_state(
            {
                "getcomics": {
                    "query": " Batman ",
                    "date": " 2024 ",
                    "results": "999",
                    "save_dir": "",
                    "recent_searches": [
                        {"query": " Batman ", "date": "2024", "results": "20"},
                        {"query": "batman", "date": "2024", "results": "20"},
                        {"query": "", "date": "2024", "results": "20"},
                        "invalid",
                    ],
                }
            },
            default_save_dir="F:/Comics",
        )

        self.assertEqual("Batman", state["getcomics"]["query"])
        self.assertEqual("2024", state["getcomics"]["date"])
        self.assertEqual("10", state["getcomics"]["results"])
        self.assertEqual("F:/Comics", state["getcomics"]["save_dir"])
        self.assertEqual(
            [{"query": "Batman", "date": "2024", "results": "20"}],
            state["getcomics"]["recent_searches"],
        )
        self.assertEqual("search", state["getcomics"]["view_mode"])
        self.assertEqual([], state["getcomics"]["favorites"])
        self.assertEqual([], state["getcomics"]["queue_items"])
        self.assertEqual(0, state["getcomics"]["last_page"])
        self.assertEqual([], state["getcomics"]["last_results"])
        self.assertEqual("F:/Comics", state["reader"]["source_path"])
        self.assertEqual("", state["reader"]["selected_path"])
        self.assertEqual("", state["reader"]["active_path"])
        self.assertEqual(0, state["reader"]["active_page"])

    def test_upsert_recent_getcomics_search_moves_existing_item_to_front(self):
        history = [
            {"query": "Spider-Man", "date": "", "results": "10"},
            {"query": "Batman", "date": "2024", "results": "20"},
        ]

        updated = upsert_recent_getcomics_search(
            history,
            {"query": "Batman", "date": "2024", "results": "20"},
        )

        self.assertEqual(
            [
                {"query": "Batman", "date": "2024", "results": "20"},
                {"query": "Spider-Man", "date": "", "results": "10"},
            ],
            updated,
        )

    def test_build_getcomics_history_label_includes_date_and_results(self):
        label = build_getcomics_history_label(
            {"query": "Batman", "date": "2024-01", "results": "5"}
        )

        self.assertEqual("Batman (2024-01 / 5 results)", label)

    def test_normalize_cached_getcomics_results_deduplicates_and_filters_invalid_entries(self):
        normalized = normalize_cached_getcomics_results(
            [
                {"url": "https://example.com/a", "title": "Batman #1"},
                {"url": "https://example.com/a", "title": "Batman #1 duplicate"},
                {"url": "", "title": "Missing URL"},
                {"url": "https://example.com/b", "title": ""},
                ("https://example.com/c", "Batman #3"),
                "invalid",
            ]
        )

        self.assertEqual(
            [
                {"url": "https://example.com/a", "title": "Batman #1"},
                {"url": "https://example.com/c", "title": "Batman #3"},
            ],
            normalized,
        )

    def test_normalize_gui_state_sets_default_page_for_cached_results(self):
        state = normalize_gui_state(
            {
                "getcomics": {
                    "last_page": "invalid",
                    "last_results": [
                        {"url": "https://example.com/a", "title": "Batman #1"},
                    ],
                }
            },
            default_save_dir="F:/Comics",
        )

        self.assertEqual(1, state["getcomics"]["last_page"])
        self.assertEqual(
            [{"url": "https://example.com/a", "title": "Batman #1"}],
            state["getcomics"]["last_results"],
        )

    def test_normalize_gui_state_falls_back_from_empty_favorites_view(self):
        state = normalize_gui_state(
            {
                "getcomics": {
                    "view_mode": "favorites",
                    "favorites": [],
                }
            },
            default_save_dir="F:/Comics",
        )

        self.assertEqual("search", state["getcomics"]["view_mode"])

    def test_normalize_gui_state_keeps_favorites_and_view_mode(self):
        state = normalize_gui_state(
            {
                "getcomics": {
                    "view_mode": "favorites",
                    "favorites": [
                        {"url": "https://example.com/a", "title": "Batman #1"},
                        {"url": "https://example.com/a", "title": "Batman #1 duplicate"},
                    ],
                }
            },
            default_save_dir="F:/Comics",
        )

        self.assertEqual("favorites", state["getcomics"]["view_mode"])
        self.assertEqual(
            [{"url": "https://example.com/a", "title": "Batman #1"}],
            state["getcomics"]["favorites"],
        )

    def test_normalize_gui_state_falls_back_from_empty_queue_view(self):
        state = normalize_gui_state(
            {
                "getcomics": {
                    "view_mode": "queue",
                    "queue_items": [],
                }
            },
            default_save_dir="F:/Comics",
        )

        self.assertEqual("search", state["getcomics"]["view_mode"])

    def test_normalize_gui_state_keeps_queue_items_and_queue_view(self):
        state = normalize_gui_state(
            {
                "getcomics": {
                    "view_mode": "queue",
                    "queue_items": [
                        {"url": "https://example.com/a", "title": "Batman #1"},
                        {"url": "https://example.com/a", "title": "Batman #1 duplicate"},
                    ],
                }
            },
            default_save_dir="F:/Comics",
        )

        self.assertEqual("queue", state["getcomics"]["view_mode"])
        self.assertEqual(
            [{"url": "https://example.com/a", "title": "Batman #1"}],
            state["getcomics"]["queue_items"],
        )

    def test_normalize_gui_state_keeps_reader_state(self):
        state = normalize_gui_state(
            {
                "reader": {
                    "source_path": "F:/Books",
                    "selected_path": "F:/Books/Series 001.cbz",
                    "active_path": "F:/Books/Series 001.cbz",
                    "active_page": "7",
                }
            },
            default_save_dir="F:/Comics",
        )

        self.assertEqual("F:/Books", state["reader"]["source_path"])
        self.assertEqual("F:/Books/Series 001.cbz", state["reader"]["selected_path"])
        self.assertEqual("F:/Books/Series 001.cbz", state["reader"]["active_path"])
        self.assertEqual(7, state["reader"]["active_page"])

    def test_normalize_gui_state_fills_reader_defaults(self):
        state = normalize_gui_state(
            {
                "reader": {
                    "source_path": "",
                    "selected_path": "",
                    "active_path": "F:/Books/Series 002.cbz",
                    "active_page": "invalid",
                }
            },
            default_save_dir="F:/Comics",
        )

        self.assertEqual("F:/Comics", state["reader"]["source_path"])
        self.assertEqual("F:/Books/Series 002.cbz", state["reader"]["selected_path"])
        self.assertEqual("F:/Books/Series 002.cbz", state["reader"]["active_path"])
        self.assertEqual(1, state["reader"]["active_page"])

    def test_load_and_save_gui_state_round_trip(self):
        with TemporaryDirectory() as temp_dir:
            state_path = os.path.join(temp_dir, ".gui_state.json")
            state = {
                "getcomics": {
                    "query": "Superman",
                    "date": "2023",
                    "results": "20",
                    "save_dir": "F:/Books",
                    "recent_searches": [
                        {"query": "Superman", "date": "2023", "results": "20"},
                        {"query": "Batman", "date": "", "results": "10"},
                    ],
                    "view_mode": "favorites",
                    "favorites": [
                        {"url": "https://example.com/batman-1", "title": "Batman #1"},
                        {"url": "https://example.com/batman-2", "title": "Batman #2"},
                    ],
                    "queue_items": [
                        {"url": "https://example.com/queue-1", "title": "Queue #1"},
                        {"url": "https://example.com/queue-2", "title": "Queue #2"},
                    ],
                    "last_page": 3,
                    "last_results": [
                        {"url": "https://example.com/superman-1", "title": "Superman #1"},
                        {"url": "https://example.com/superman-2", "title": "Superman #2"},
                    ],
                },
                "reader": {
                    "source_path": "F:/Books",
                    "selected_path": "F:/Books/Series 001.cbz",
                    "active_path": "F:/Books/Series 001.cbz",
                    "active_page": 4,
                },
            }

            self.assertTrue(save_gui_state(state_path, state, default_save_dir="F:/Comics"))

            with open(state_path, "r", encoding="utf-8") as file_handle:
                payload = json.load(file_handle)

            self.assertEqual("Superman", payload["getcomics"]["query"])
            self.assertEqual("F:/Books", payload["getcomics"]["save_dir"])
            self.assertEqual("favorites", payload["getcomics"]["view_mode"])
            self.assertEqual(3, payload["getcomics"]["last_page"])
            self.assertEqual("F:/Books", payload["reader"]["source_path"])
            self.assertEqual(4, payload["reader"]["active_page"])

            loaded = load_gui_state(state_path, default_save_dir="F:/Comics")
            self.assertEqual(state, loaded)

    def test_load_gui_state_returns_defaults_for_invalid_json(self):
        with TemporaryDirectory() as temp_dir:
            state_path = os.path.join(temp_dir, ".gui_state.json")
            with open(state_path, "w", encoding="utf-8") as file_handle:
                file_handle.write("{broken")

            loaded = load_gui_state(state_path, default_save_dir="F:/Comics")

            self.assertEqual(
                {
                    "getcomics": {
                        "query": "",
                        "date": "",
                        "results": "10",
                        "save_dir": "F:/Comics",
                        "recent_searches": [],
                        "view_mode": "search",
                        "favorites": [],
                        "queue_items": [],
                        "last_page": 0,
                        "last_results": [],
                    },
                    "reader": {
                        "source_path": "F:/Comics",
                        "selected_path": "",
                        "active_path": "",
                        "active_page": 0,
                    },
                },
                loaded,
            )

    def test_load_and_save_getcomics_favorites_file_round_trip(self):
        with TemporaryDirectory() as temp_dir:
            favorites_path = os.path.join(temp_dir, "favorites.json")
            favorites = [
                {"url": "https://example.com/a", "title": "Batman #1"},
                {"url": "https://example.com/b", "title": "Batman #2"},
            ]

            self.assertTrue(save_getcomics_favorites_file(favorites_path, favorites))
            loaded = load_getcomics_favorites_file(favorites_path)

            self.assertEqual(favorites, loaded)

    def test_load_getcomics_favorites_file_supports_plain_list_payload(self):
        with TemporaryDirectory() as temp_dir:
            favorites_path = os.path.join(temp_dir, "favorites.json")
            with open(favorites_path, "w", encoding="utf-8") as file_handle:
                json.dump(
                    [
                        {"url": "https://example.com/a", "title": "Batman #1"},
                        {"url": "https://example.com/a", "title": "Batman #1 duplicate"},
                    ],
                    file_handle,
                    ensure_ascii=False,
                    indent=2,
                )

            loaded = load_getcomics_favorites_file(favorites_path)

            self.assertEqual(
                [{"url": "https://example.com/a", "title": "Batman #1"}],
                loaded,
            )

    def test_load_getcomics_favorites_file_returns_empty_for_invalid_payload(self):
        with TemporaryDirectory() as temp_dir:
            favorites_path = os.path.join(temp_dir, "favorites.json")
            with open(favorites_path, "w", encoding="utf-8") as file_handle:
                file_handle.write("{broken")

            self.assertEqual([], load_getcomics_favorites_file(favorites_path))


if __name__ == "__main__":
    unittest.main()
