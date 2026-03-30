import queue as queue_module
import tkinter as tk
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch

try:
    from core.gui import ComicDownloaderGUI
except ModuleNotFoundError as exc:
    ComicDownloaderGUI = None
    GUI_IMPORT_ERROR = exc
else:
    GUI_IMPORT_ERROR = None


class FakeWidget:
    def __init__(self, **options):
        self.options = dict(options)

    def configure(self, **kwargs):
        self.options.update(kwargs)

    def cget(self, key):
        return self.options.get(key)


class FakeEntry(FakeWidget):
    def __init__(self, value="", **options):
        super().__init__(**options)
        self.value = value

    def get(self):
        return self.value

    def delete(self, start, end=None):
        self.value = ""

    def insert(self, index, value):
        self.value = str(value)


class FakeListbox:
    def __init__(self):
        self.items = []
        self.selected = ()

    def delete(self, start, end=None):
        self.items = []

    def insert(self, index, value):
        self.items.append(value)

    def selection_clear(self, start, end=None):
        self.selected = ()

    def selection_set(self, start, end=None):
        if end in (None, start):
            self.selected = (int(start),)
            return

        if end == tk.END:
            end_index = len(self.items) - 1
        else:
            end_index = int(end)

        start_index = int(start)
        if end_index < start_index:
            self.selected = ()
            return

        self.selected = tuple(range(start_index, end_index + 1))

    def select_set(self, start, end=None):
        self.selection_set(start, end=end)

    def curselection(self):
        return self.selected


class ImmediateThread:
    def __init__(self, target=None, daemon=None):
        self.target = target
        self.daemon = daemon
        self.started = False

    def start(self):
        self.started = True
        if self.target:
            self.target()

    def is_alive(self):
        return False


@unittest.skipIf(ComicDownloaderGUI is None, f"GUI import unavailable: {GUI_IMPORT_ERROR}")
class GuiQueueBehaviorTests(unittest.TestCase):
    class Harness:
        get_selected_getcomics_results = ComicDownloaderGUI.get_selected_getcomics_results
        get_getcomics_favorite_urls = ComicDownloaderGUI.get_getcomics_favorite_urls
        get_getcomics_queue_urls = ComicDownloaderGUI.get_getcomics_queue_urls
        update_getcomics_view_toggle_button = ComicDownloaderGUI.update_getcomics_view_toggle_button
        update_getcomics_result_actions = ComicDownloaderGUI.update_getcomics_result_actions
        populate_getcomics_results_list = ComicDownloaderGUI.populate_getcomics_results_list
        update_getcomics_page_status = ComicDownloaderGUI.update_getcomics_page_status
        update_getcomics_pagination_controls = ComicDownloaderGUI.update_getcomics_pagination_controls
        set_getcomics_view_mode = ComicDownloaderGUI.set_getcomics_view_mode
        add_selected_getcomics_to_queue = ComicDownloaderGUI.add_selected_getcomics_to_queue
        remove_selected_getcomics_from_queue = ComicDownloaderGUI.remove_selected_getcomics_from_queue
        start_getcomics_download_for_results = ComicDownloaderGUI.start_getcomics_download_for_results
        start_getcomics_queue_download = ComicDownloaderGUI.start_getcomics_queue_download

        def __init__(self):
            self.getcomics_favorites = []
            self.getcomics_download_queue = []
            self.getcomics_view_mode = "search"
            self.getcomics_search_results_data = [
                ("https://example.com/search-1", "Search Result #1"),
                ("https://example.com/search-2", "Search Result #2"),
            ]
            self.getcomics_results_data = []
            self.getcomics_search_current_page = 2
            self.getcomics_current_page = 2
            self.getcomics_results_restored_from_cache = False
            self.getcomics_downloader = object()
            self.getcomics_thread = None
            self.is_getcomics_cancelled = False
            self.persist_count = 0
            self.logs = []
            self.queue = queue_module.Queue()

            self.status_label = FakeWidget(text="")
            self.getcomics_page_label = FakeWidget(text="")
            self.getcomics_jump_entry = FakeEntry("", state="disabled")
            self.getcomics_save_entry = FakeEntry("", state="normal")

            self.getcomics_listbox = FakeListbox()

            self.getcomics_open_result_button = FakeWidget(state="disabled")
            self.getcomics_copy_links_button = FakeWidget(state="disabled")
            self.getcomics_select_all_button = FakeWidget(state="disabled")
            self.getcomics_add_favorite_button = FakeWidget(state="disabled")
            self.getcomics_remove_favorite_button = FakeWidget(state="disabled")
            self.getcomics_toggle_view_button = FakeWidget(state="disabled", text="查看收藏")
            self.getcomics_export_favorites_button = FakeWidget(state="disabled")
            self.getcomics_add_queue_button = FakeWidget(state="disabled")
            self.getcomics_remove_queue_button = FakeWidget(state="disabled")
            self.getcomics_toggle_queue_button = FakeWidget(state="disabled", text="查看队列")
            self.getcomics_clear_queue_button = FakeWidget(state="disabled")

            self.getcomics_search_button = FakeWidget(state="normal")
            self.getcomics_prev_button = FakeWidget(state="disabled")
            self.getcomics_jump_button = FakeWidget(state="disabled")
            self.getcomics_next_button = FakeWidget(state="disabled")

            self.getcomics_download_button = FakeWidget(state="normal")
            self.getcomics_download_queue_button = FakeWidget(state="disabled")
            self.getcomics_cancel_button = FakeWidget(state="disabled")

            self.populate_getcomics_results_list(self.getcomics_search_results_data)
            self.update_getcomics_page_status(self.getcomics_search_current_page)
            self.update_getcomics_pagination_controls(searching=False)

        def persist_gui_state_snapshot(self):
            self.persist_count += 1

        def log(self, message):
            self.logs.append(message)

        def reset_progress(self):
            return None

    def test_queue_items_can_be_added_viewed_removed_and_fallback_to_search(self):
        harness = self.Harness()
        harness.getcomics_listbox.selection_set(0)
        harness.update_getcomics_result_actions()

        self.assertEqual("normal", harness.getcomics_add_queue_button.cget("state"))

        harness.add_selected_getcomics_to_queue()

        self.assertEqual(
            [("https://example.com/search-1", "Search Result #1")],
            harness.getcomics_download_queue,
        )
        self.assertEqual(1, harness.persist_count)
        self.assertEqual("normal", harness.getcomics_toggle_queue_button.cget("state"))
        self.assertEqual("normal", harness.getcomics_download_queue_button.cget("state"))

        harness.set_getcomics_view_mode("queue")
        self.assertEqual("queue", harness.getcomics_view_mode)
        self.assertEqual(harness.getcomics_download_queue, harness.getcomics_results_data)
        self.assertIn("1", harness.getcomics_page_label.cget("text"))

        harness.getcomics_listbox.selection_set(0)
        harness.update_getcomics_result_actions()
        self.assertEqual("normal", harness.getcomics_remove_queue_button.cget("state"))

        harness.remove_selected_getcomics_from_queue()

        self.assertEqual([], harness.getcomics_download_queue)
        self.assertEqual("search", harness.getcomics_view_mode)
        self.assertEqual(harness.getcomics_search_results_data, harness.getcomics_results_data)
        self.assertEqual(2, harness.getcomics_search_current_page)
        self.assertEqual("disabled", harness.getcomics_toggle_queue_button.cget("state"))
        self.assertEqual("disabled", harness.getcomics_download_queue_button.cget("state"))
        self.assertEqual(3, harness.persist_count)

    def test_queue_download_uses_snapshot_and_emits_completion_messages(self):
        harness = self.Harness()
        harness.getcomics_download_queue = [
            ("https://example.com/queue-1", "Queue Item #1"),
            ("https://example.com/queue-2", "Queue Item #2"),
        ]

        with TemporaryDirectory() as temp_dir:
            harness.getcomics_save_entry.insert(0, temp_dir)
            download_calls = []

            def fake_download_comics(selected_comics, save_dir, *args, **kwargs):
                download_calls.append((selected_comics, save_dir, kwargs))
                progress_callback = kwargs["progress_callback"]
                progress_callback(("progress", 25))
                progress_callback("downloading queue")

            with patch("core.gui.download_comics", side_effect=fake_download_comics):
                with patch("core.gui.threading.Thread", ImmediateThread):
                    harness.start_getcomics_queue_download()

            self.assertEqual(1, len(download_calls))
            selected_comics, save_dir, kwargs = download_calls[0]
            self.assertEqual(
                {
                    "https://example.com/queue-1": "Queue Item #1",
                    "https://example.com/queue-2": "Queue Item #2",
                },
                selected_comics,
            )
            self.assertEqual(temp_dir, str(save_dir))
            self.assertTrue(kwargs["use_aria2c"])
            self.assertFalse(kwargs["rename_downloaded_files"])

        queued_messages = []
        while not harness.queue.empty():
            queued_messages.append(harness.queue.get_nowait())

        self.assertIn(("progress", 25), queued_messages)
        self.assertIn(("progress", 100), queued_messages)
        self.assertIn(("getcomics_done", None), queued_messages)
        self.assertTrue(any(message == ("info", "downloading queue") for message in queued_messages))
        self.assertTrue(any(message[0] == "complete" for message in queued_messages))


if __name__ == "__main__":
    unittest.main()
