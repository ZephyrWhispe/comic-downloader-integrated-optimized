from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest import mock
import zipfile

from PIL import Image

from core import comic_reader as comic_reader_module
from core.comic_reader import (
    build_comic_entry,
    calculate_reader_image_size,
    clamp_reader_zoom_percent,
    count_comic_pages,
    discover_comics,
    format_bytes,
    get_comic_source_requirement_message,
    iter_cbz_export_entries,
    list_archive_comic_pages,
    list_comic_pages,
    list_folder_comic_pages,
    load_comic_page_image,
    normalize_reader_zoom_mode,
)


def build_image_bytes(size=(120, 180), color=(255, 0, 0)):
    buffer = BytesIO()
    image = Image.new("RGB", size, color)
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def build_pdf_file(path, size=(120, 180), color=(255, 255, 255)):
    image = Image.new("RGB", size, color)
    image.save(path, format="PDF")


class ComicReaderTests(unittest.TestCase):
    def test_list_folder_comic_pages_sorts_naturally(self):
        with TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir) / "Issue 001"
            folder.mkdir()
            (folder / "10.png").write_bytes(build_image_bytes())
            (folder / "2.png").write_bytes(build_image_bytes())
            (folder / "1.png").write_bytes(build_image_bytes())
            (folder / "notes.txt").write_text("ignore", encoding="utf-8")

            self.assertEqual(
                ["1.png", "2.png", "10.png"],
                list_folder_comic_pages(folder),
            )

    def test_list_archive_comic_pages_sorts_naturally(self):
        with TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "Batman.cbz"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("10.png", build_image_bytes())
                archive.writestr("2.png", build_image_bytes())
                archive.writestr("1.png", build_image_bytes())
                archive.writestr("README.txt", "ignore")

            self.assertEqual(
                ["1.png", "2.png", "10.png"],
                list_archive_comic_pages(archive_path),
            )

    def test_discover_comics_finds_folder_and_archive_entries(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            folder_comic = root / "Series A" / "Issue 001"
            folder_comic.mkdir(parents=True)
            (folder_comic / "1.png").write_bytes(build_image_bytes())
            (folder_comic / "2.png").write_bytes(build_image_bytes())

            archive_path = root / "Series B.cbz"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("1.png", build_image_bytes())

            discovered = discover_comics(root)

            self.assertEqual(2, len(discovered))
            self.assertEqual(
                ["Issue 001", "Series B"],
                [item["name"] for item in discovered],
            )
            self.assertEqual(
                [2, 1],
                [item["page_count"] for item in discovered],
            )

    def test_build_comic_entry_returns_none_for_unsupported_source(self):
        with TemporaryDirectory() as temp_dir:
            text_path = Path(temp_dir) / "notes.txt"
            text_path.write_text("ignore", encoding="utf-8")

            self.assertIsNone(build_comic_entry(text_path))

    def test_count_comic_pages_and_list_comic_pages_support_archive(self):
        with TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "WonderWoman.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("001.png", build_image_bytes())
                archive.writestr("002.png", build_image_bytes())

            self.assertEqual(2, count_comic_pages(archive_path))
            self.assertEqual(["001.png", "002.png"], list_comic_pages(archive_path))

    def test_load_comic_page_image_reads_from_folder_and_archive(self):
        with TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir) / "Issue 002"
            folder.mkdir()
            (folder / "1.png").write_bytes(build_image_bytes(size=(90, 140), color=(0, 255, 0)))

            archive_path = Path(temp_dir) / "Issue 003.cbz"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("1.png", build_image_bytes(size=(80, 120), color=(0, 0, 255)))

            folder_image = load_comic_page_image(folder, "1.png")
            archive_image = load_comic_page_image(archive_path, "1.png")

            self.assertEqual((90, 140), folder_image.size)
            self.assertEqual((80, 120), archive_image.size)

    def test_iter_cbz_export_entries_reads_recursive_folder_images(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "Series"
            nested = root / "Chapter 001"
            nested.mkdir(parents=True)
            (nested / "02.png").write_bytes(build_image_bytes(size=(20, 30)))
            (nested / "01.png").write_bytes(build_image_bytes(size=(10, 20)))

            exported = list(iter_cbz_export_entries(root))

            self.assertEqual(
                ["Chapter 001/01.png", "Chapter 001/02.png"],
                [name for name, _ in exported],
            )

    def test_iter_cbz_export_entries_reads_zip_archives(self):
        with TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "Issue 010.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("a/002.png", build_image_bytes())
                archive.writestr("a/001.png", build_image_bytes())

            exported = list(iter_cbz_export_entries(archive_path))

            self.assertEqual(
                ["a/001.png", "a/002.png"],
                [name for name, _ in exported],
            )

    @unittest.skipIf(comic_reader_module.py7zr is None, "py7zr not installed")
    def test_sevenzip_archives_are_listed_and_loaded(self):
        with TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "Issue 004.7z"
            with comic_reader_module.py7zr.SevenZipFile(archive_path, "w") as archive:
                archive.writestr(build_image_bytes(size=(64, 96), color=(255, 255, 0)), "1.png")
                archive.writestr(build_image_bytes(size=(66, 98), color=(255, 0, 255)), "2.png")

            self.assertEqual(2, count_comic_pages(archive_path))
            self.assertEqual(["1.png", "2.png"], list_comic_pages(archive_path))
            loaded_image = load_comic_page_image(archive_path, "2.png")
            self.assertEqual((66, 98), loaded_image.size)

            exported = list(iter_cbz_export_entries(archive_path))
            self.assertEqual(["1.png", "2.png"], [name for name, _ in exported])

    @unittest.skipIf(comic_reader_module.pdfium is None, "pypdfium2 not installed")
    def test_pdf_documents_are_counted_and_rendered(self):
        with TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "Issue 005.pdf"
            build_pdf_file(pdf_path, size=(50, 80), color=(200, 200, 255))

            self.assertEqual(["1"], list_comic_pages(pdf_path))
            self.assertEqual(1, count_comic_pages(pdf_path))

            entry = build_comic_entry(pdf_path)
            self.assertIsNotNone(entry)
            self.assertEqual("pdf", entry["kind"])
            self.assertEqual("PDF", entry["format"])

            loaded_image = load_comic_page_image(pdf_path, "1")
            self.assertGreaterEqual(loaded_image.size[0], 50)
            self.assertGreaterEqual(loaded_image.size[1], 80)

            exported = list(iter_cbz_export_entries(pdf_path))
            self.assertEqual(["001.png"], [name for name, _ in exported])

    @unittest.skipIf(
        comic_reader_module.py7zr is None or comic_reader_module.pdfium is None,
        "py7zr or pypdfium2 not installed",
    )
    def test_discover_comics_includes_pdf_and_sevenzip_entries(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pdf_path = root / "Archive A.pdf"
            build_pdf_file(pdf_path)

            archive_path = root / "Archive B.7z"
            with comic_reader_module.py7zr.SevenZipFile(archive_path, "w") as archive:
                archive.writestr(build_image_bytes(), "001.png")

            discovered = discover_comics(root)
            self.assertEqual(
                ["Archive A", "Archive B"],
                [item["name"] for item in discovered],
            )

    def test_get_comic_source_requirement_message_explains_missing_rar_tools(self):
        with mock.patch(
            "core.comic_reader.get_optional_comic_support_status",
            return_value={
                "pdf": {"available": True, "message": "ok"},
                "sevenzip": {"available": True, "message": "ok"},
                "rar": {"available": False, "message": "缺少外部解包工具。"},
            },
        ):
            message = get_comic_source_requirement_message("Batman.cbr", action="打开")

        self.assertIn("打开 CBR 文件前", message)
        self.assertIn("缺少外部解包工具", message)

    def test_format_bytes_is_readable(self):
        self.assertEqual("0 B", format_bytes(None))
        self.assertEqual("999 B", format_bytes(999))
        self.assertEqual("1.5 KB", format_bytes(1536))

    def test_calculate_reader_image_size_supports_fit_modes_and_manual_zoom(self):
        self.assertEqual(
            (533, 800),
            calculate_reader_image_size((1200, 1800), (600, 800), zoom_mode="fit_window"),
        )
        self.assertEqual(
            (600, 900),
            calculate_reader_image_size((1200, 1800), (600, 800), zoom_mode="fit_width"),
        )
        self.assertEqual(
            (600, 900),
            calculate_reader_image_size((400, 600), (600, 800), zoom_mode="manual", zoom_percent=150),
        )

    def test_reader_zoom_normalization_clamps_invalid_values(self):
        self.assertEqual("fit_width", normalize_reader_zoom_mode(" FIT_WIDTH "))
        self.assertEqual("fit_window", normalize_reader_zoom_mode("unsupported"))
        self.assertEqual(25, clamp_reader_zoom_percent("0"))
        self.assertEqual(400, clamp_reader_zoom_percent("999"))
        self.assertEqual(100, clamp_reader_zoom_percent("invalid"))


if __name__ == "__main__":
    unittest.main()
