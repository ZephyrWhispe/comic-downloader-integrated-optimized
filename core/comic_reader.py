from io import BytesIO
from pathlib import Path, PurePosixPath
import re
import zipfile

from PIL import Image, ImageOps


IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".gif",
    ".bmp",
}
ARCHIVE_EXTENSIONS = {
    ".cbz",
    ".zip",
}


def natural_sort_key(value):
    text = str(value or "").casefold()
    return [
        int(part) if part.isdigit() else part
        for part in re.split(r"(\d+)", text)
    ]


def is_supported_comic_archive(path):
    return Path(path).suffix.casefold() in ARCHIVE_EXTENSIONS


def is_image_name(name):
    pure_name = PurePosixPath(str(name or "")).name
    if not pure_name or pure_name.startswith("."):
        return False
    return PurePosixPath(pure_name).suffix.casefold() in IMAGE_EXTENSIONS


def list_folder_comic_pages(path):
    folder = Path(path)
    if not folder.is_dir():
        return []

    pages = [
        child.name
        for child in folder.iterdir()
        if child.is_file() and is_image_name(child.name)
    ]
    return sorted(pages, key=natural_sort_key)


def list_archive_comic_pages(path):
    archive_path = Path(path)
    if not archive_path.is_file() or not is_supported_comic_archive(archive_path):
        return []

    with zipfile.ZipFile(archive_path) as archive:
        pages = [
            member_name
            for member_name in archive.namelist()
            if not member_name.endswith("/")
            and "__MACOSX/" not in member_name
            and is_image_name(member_name)
        ]
    return sorted(pages, key=natural_sort_key)


def list_comic_pages(path):
    source = Path(path)
    if source.is_dir():
        return list_folder_comic_pages(source)
    if source.is_file():
        return list_archive_comic_pages(source)
    return []


def count_comic_pages(path):
    return len(list_comic_pages(path))


def build_comic_entry(path):
    source = Path(path)
    pages = list_comic_pages(source)
    if not pages:
        return None

    kind = "folder" if source.is_dir() else "archive"
    display_name = source.name if source.is_dir() else source.stem
    return {
        "path": str(source),
        "name": display_name,
        "kind": kind,
        "page_count": len(pages),
        "size_bytes": source.stat().st_size if source.exists() else 0,
        "modified_ts": source.stat().st_mtime if source.exists() else 0,
    }


def discover_comics(root_path):
    source = Path(root_path).expanduser()
    if not source.exists():
        return []

    if source.is_file():
        entry = build_comic_entry(source)
        return [entry] if entry else []

    discovered = []
    for current_root, dir_names, file_names in source.walk():
        current_path = Path(current_root)

        direct_image_files = [
            file_name
            for file_name in file_names
            if is_image_name(file_name)
        ]
        if direct_image_files:
            entry = build_comic_entry(current_path)
            if entry:
                discovered.append(entry)
            dir_names[:] = []
            continue

        for child_name in file_names:
            child_path = current_path / child_name
            if not is_supported_comic_archive(child_path):
                continue
            entry = build_comic_entry(child_path)
            if entry:
                discovered.append(entry)

    return sorted(
        discovered,
        key=lambda item: (
            natural_sort_key(item["name"]),
            natural_sort_key(item["path"]),
        ),
    )


def format_bytes(size_bytes):
    try:
        size = float(size_bytes)
    except (TypeError, ValueError):
        return "0 B"

    units = ["B", "KB", "MB", "GB", "TB"]
    unit_index = 0
    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1

    if unit_index == 0:
        return f"{int(size)} {units[unit_index]}"
    return f"{size:.1f} {units[unit_index]}"


def load_comic_page_image(path, page_name):
    source = Path(path)
    page_key = str(page_name or "").strip()
    if not page_key:
        raise ValueError("Missing page name")

    if source.is_dir():
        page_path = source / page_key
        with Image.open(page_path) as image:
            normalized = ImageOps.exif_transpose(image)
            if normalized.mode not in ("RGB", "RGBA"):
                normalized = normalized.convert("RGB")
            return normalized.copy()

    if source.is_file() and is_supported_comic_archive(source):
        with zipfile.ZipFile(source) as archive:
            with archive.open(page_key) as handle:
                data = handle.read()
        with Image.open(BytesIO(data)) as image:
            normalized = ImageOps.exif_transpose(image)
            if normalized.mode not in ("RGB", "RGBA"):
                normalized = normalized.convert("RGB")
            return normalized.copy()

    raise ValueError(f"Unsupported comic source: {source}")
