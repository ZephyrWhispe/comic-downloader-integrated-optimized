import os
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication
    from core.qt_gui import ComicDownloaderQtWindow
except Exception as exc:  # pragma: no cover - environment dependent import guard
    QApplication = None
    ComicDownloaderQtWindow = None
    QT_IMPORT_ERROR = exc
else:
    QT_IMPORT_ERROR = None


class FakeParser:
    def __init__(self, result):
        self.result = result
        self.closed = False

    def get_comic_info(self, _url):
        return self.result

    def close(self):
        self.closed = True


@unittest.skipIf(ComicDownloaderQtWindow is None, f"Qt GUI import unavailable: {QT_IMPORT_ERROR}")
class QtGuiBackgroundTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = ComicDownloaderQtWindow()

    def tearDown(self):
        try:
            self.window.close()
        finally:
            self.process_events(0.05)

    def process_events(self, duration=0.2):
        deadline = time.time() + duration
        while time.time() < deadline:
            self.app.processEvents()
            time.sleep(0.01)

    def test_fetch_comic_info_updates_ui_even_when_worker_finishes_immediately(self):
        parser = FakeParser(
            (
                "Regression Test Comic",
                [
                    ("Chapter 1", "https://example.com/chapter-1"),
                    ("Chapter 2", "https://example.com/chapter-2"),
                ],
            )
        )
        self.window.comic_dl_url_edit.setText("https://readcomicsonline.ru/comic/regression-test")

        with patch.object(self.window.comic_dl_downloader, "get_parser", return_value=parser):
            with patch("core.qt_gui.QMessageBox.warning") as warning_mock:
                self.window.fetch_comic_info()
                time.sleep(0.1)
                self.process_events(0.2)

        self.assertFalse(warning_mock.called)
        self.assertTrue(parser.closed)
        self.assertEqual("Regression Test Comic", self.window.comic_title)
        self.assertEqual(2, len(self.window.chapter_data))
        self.assertEqual(2, self.window.comic_dl_chapter_list.count())
        self.assertIn("Regression Test Comic", self.window.status_label.text())
        self.assertIn("2", self.window.status_label.text())
        self.assertTrue(self.window.comic_dl_fetch_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
