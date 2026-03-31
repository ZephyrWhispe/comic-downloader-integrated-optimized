import json
import os
import unittest
from tempfile import TemporaryDirectory

from core.gui_state import (
    DEFAULT_RENAME_API_MODEL,
    DEFAULT_RENAME_API_TIMEOUT,
    DEFAULT_RENAME_API_URL,
    build_getcomics_history_label,
    load_gui_state,
    load_getcomics_favorites_file,
    normalize_appearance_mode,
    normalize_cached_getcomics_results,
    normalize_reader_focus_mode,
    normalize_reader_scroll_fraction,
    normalize_rename_api_timeout,
    normalize_gui_state,
    normalize_reader_zoom_mode,
    normalize_reader_zoom_percent,
    normalize_recent_getcomics_searches,
    normalize_windows_reader_fullscreen_mode,
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
        self.assertEqual("fit_window", state["reader"]["zoom_mode"])
        self.assertEqual(100, state["reader"]["zoom_percent"])
        self.assertFalse(state["reader"]["focus_mode"])
        self.assertEqual(0.0, state["reader"]["scroll_x"])
        self.assertEqual(0.0, state["reader"]["scroll_y"])
        self.assertEqual("Dark", state["settings"]["appearance_mode"])
        self.assertEqual("smooth", state["settings"]["reader_windows_fullscreen_mode"])
        self.assertEqual("", state["settings"]["rename_api_key"])
        self.assertEqual(DEFAULT_RENAME_API_URL, state["settings"]["rename_api_url"])
        self.assertEqual(DEFAULT_RENAME_API_MODEL, state["settings"]["rename_api_model"])
        self.assertEqual(DEFAULT_RENAME_API_TIMEOUT, state["settings"]["rename_api_timeout"])

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
                    "zoom_mode": "manual",
                    "zoom_percent": "150",
                    "focus_mode": "true",
                    "scroll_x": "0.25",
                    "scroll_y": "0.75",
                }
            },
            default_save_dir="F:/Comics",
        )

        self.assertEqual("F:/Books", state["reader"]["source_path"])
        self.assertEqual("F:/Books/Series 001.cbz", state["reader"]["selected_path"])
        self.assertEqual("F:/Books/Series 001.cbz", state["reader"]["active_path"])
        self.assertEqual(7, state["reader"]["active_page"])
        self.assertEqual("manual", state["reader"]["zoom_mode"])
        self.assertEqual(150, state["reader"]["zoom_percent"])
        self.assertTrue(state["reader"]["focus_mode"])
        self.assertEqual(0.25, state["reader"]["scroll_x"])
        self.assertEqual(0.75, state["reader"]["scroll_y"])

    def test_normalize_gui_state_fills_reader_defaults(self):
        state = normalize_gui_state(
            {
                "reader": {
                    "source_path": "",
                    "selected_path": "",
                    "active_path": "F:/Books/Series 002.cbz",
                    "active_page": "invalid",
                    "zoom_mode": "invalid",
                    "zoom_percent": "999",
                    "focus_mode": "off",
                    "scroll_x": "2",
                    "scroll_y": "-1",
                }
            },
            default_save_dir="F:/Comics",
        )

        self.assertEqual("F:/Comics", state["reader"]["source_path"])
        self.assertEqual("F:/Books/Series 002.cbz", state["reader"]["selected_path"])
        self.assertEqual("F:/Books/Series 002.cbz", state["reader"]["active_path"])
        self.assertEqual(1, state["reader"]["active_page"])
        self.assertEqual("fit_window", state["reader"]["zoom_mode"])
        self.assertEqual(400, state["reader"]["zoom_percent"])
        self.assertFalse(state["reader"]["focus_mode"])
        self.assertEqual(1.0, state["reader"]["scroll_x"])
        self.assertEqual(0.0, state["reader"]["scroll_y"])

    def test_normalize_gui_state_keeps_settings(self):
        state = normalize_gui_state(
            {
                "settings": {
                    "appearance_mode": "System",
                    "reader_windows_fullscreen_mode": "exclusive",
                    "rename_api_key": " sk-test ",
                    "rename_api_url": " https://example.com/v1/chat/completions ",
                    "rename_api_model": " custom-model ",
                    "rename_api_timeout": "45",
                }
            },
            default_save_dir="F:/Comics",
        )

        self.assertEqual("System", state["settings"]["appearance_mode"])
        self.assertEqual("exclusive", state["settings"]["reader_windows_fullscreen_mode"])
        self.assertEqual("sk-test", state["settings"]["rename_api_key"])
        self.assertEqual(
            "https://example.com/v1/chat/completions",
            state["settings"]["rename_api_url"],
        )
        self.assertEqual("custom-model", state["settings"]["rename_api_model"])
        self.assertEqual(45, state["settings"]["rename_api_timeout"])

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
                    "zoom_mode": "fit_width",
                    "zoom_percent": 125,
                    "focus_mode": True,
                    "scroll_x": 0.4,
                    "scroll_y": 0.6,
                },
                "settings": {
                    "appearance_mode": "System",
                    "reader_windows_fullscreen_mode": "exclusive",
                    "rename_api_key": "sk-test",
                    "rename_api_url": "https://example.com/v1/chat/completions",
                    "rename_api_model": "custom-model",
                    "rename_api_timeout": 45,
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
            self.assertEqual("fit_width", payload["reader"]["zoom_mode"])
            self.assertEqual(125, payload["reader"]["zoom_percent"])
            self.assertTrue(payload["reader"]["focus_mode"])
            self.assertEqual(0.4, payload["reader"]["scroll_x"])
            self.assertEqual(0.6, payload["reader"]["scroll_y"])
            self.assertEqual("System", payload["settings"]["appearance_mode"])
            self.assertEqual("exclusive", payload["settings"]["reader_windows_fullscreen_mode"])
            self.assertEqual("sk-test", payload["settings"]["rename_api_key"])
            self.assertEqual(
                "https://example.com/v1/chat/completions",
                payload["settings"]["rename_api_url"],
            )
            self.assertEqual("custom-model", payload["settings"]["rename_api_model"])
            self.assertEqual(45, payload["settings"]["rename_api_timeout"])

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
                        "zoom_mode": "fit_window",
                        "zoom_percent": 100,
                        "focus_mode": False,
                        "scroll_x": 0.0,
                        "scroll_y": 0.0,
                    },
                    "settings": {
                        "appearance_mode": "Dark",
                        "reader_windows_fullscreen_mode": "smooth",
                        "rename_api_key": "",
                        "rename_api_url": DEFAULT_RENAME_API_URL,
                        "rename_api_model": DEFAULT_RENAME_API_MODEL,
                        "rename_api_timeout": DEFAULT_RENAME_API_TIMEOUT,
                    },
                },
                loaded,
            )

    def test_reader_zoom_normalizers_apply_defaults_and_bounds(self):
        self.assertEqual("Dark", normalize_appearance_mode("invalid"))
        self.assertEqual("manual", normalize_reader_zoom_mode("MANUAL"))
        self.assertEqual("fit_window", normalize_reader_zoom_mode("invalid"))
        self.assertEqual(25, normalize_reader_zoom_percent("-10"))
        self.assertEqual(400, normalize_reader_zoom_percent("999"))
        self.assertEqual(100, normalize_reader_zoom_percent("not-a-number"))
        self.assertEqual("smooth", normalize_windows_reader_fullscreen_mode("bad"))
        self.assertEqual("exclusive", normalize_windows_reader_fullscreen_mode("exclusive"))
        self.assertEqual(5, normalize_rename_api_timeout("1"))
        self.assertEqual(300, normalize_rename_api_timeout("999"))
        self.assertEqual(DEFAULT_RENAME_API_TIMEOUT, normalize_rename_api_timeout("bad"))
        self.assertTrue(normalize_reader_focus_mode("yes"))
        self.assertFalse(normalize_reader_focus_mode("0"))
        self.assertEqual(0.0, normalize_reader_scroll_fraction("bad"))
        self.assertEqual(0.0, normalize_reader_scroll_fraction("-1"))
        self.assertEqual(1.0, normalize_reader_scroll_fraction("9"))
        self.assertEqual(0.5, normalize_reader_scroll_fraction("0.5"))

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
