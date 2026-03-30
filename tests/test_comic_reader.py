from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import zipfile

from PIL import Image

from core.comic_reader import (
    build_comic_entry,
    count_comic_pages,
    discover_comics,
    format_bytes,
    list_archive_comic_pages,
    list_comic_pages,
    list_folder_comic_pages,
    load_comic_page_image,
)


def build_image_bytes(size=(120, 180), color=(255, 0, 0)):
    buffer = BytesIO()
    image = Image.new("RGB", size, color)
    image.save(buffer, format="PNG")
    return buffer.getvalue()


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

    def test_format_bytes_is_readable(self):
        self.assertEqual("0 B", format_bytes(None))
        self.assertEqual("999 B", format_bytes(999))
        self.assertEqual("1.5 KB", format_bytes(1536))


if __name__ == "__main__":
    unittest.main()
