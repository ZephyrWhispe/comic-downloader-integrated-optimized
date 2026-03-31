from io import BytesIO
from pathlib import Path, PurePosixPath
import re
from tempfile import TemporaryDirectory
import zipfile

from PIL import Image, ImageOps

try:
    import py7zr
except ModuleNotFoundError:
    py7zr = None

try:
    import pypdfium2 as pdfium
except ModuleNotFoundError:
    pdfium = None

try:
    import rarfile
except ModuleNotFoundError:
    rarfile = None


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
    ".cbr",
    ".cb7",
    ".rar",
    ".7z",
    ".zip",
}
PDF_EXTENSIONS = {
    ".pdf",
}
DEFAULT_READER_ZOOM_MODE = "fit_window"
READER_ZOOM_MODES = {
    "fit_window",
    "fit_width",
    "manual",
}
MIN_READER_ZOOM_PERCENT = 25
MAX_READER_ZOOM_PERCENT = 400
PDF_RENDER_SCALE = 2
RAR_TOOL_NAMES = ("unrar", "7z", "unar", "bsdtar")
RAR_TOOL_HINT = ", ".join(RAR_TOOL_NAMES)
ZIP_ARCHIVE_EXTENSIONS = {".cbz", ".zip"}
RAR_ARCHIVE_EXTENSIONS = {".cbr", ".rar"}
SEVENZIP_ARCHIVE_EXTENSIONS = {".cb7", ".7z"}


class ComicReaderSupportError(RuntimeError):
    pass


def natural_sort_key(value):
    text = str(value or "").casefold()
    return [
        int(part) if part.isdigit() else part
        for part in re.split(r"(\d+)", text)
    ]


def is_supported_comic_archive(path):
    return Path(path).suffix.casefold() in ARCHIVE_EXTENSIONS


def is_supported_comic_document(path):
    return Path(path).suffix.casefold() in PDF_EXTENSIONS


def is_supported_comic_source(path):
    source = Path(path)
    return source.is_dir() or is_supported_comic_archive(source) or is_supported_comic_document(source)


def is_image_name(name):
    pure_name = PurePosixPath(str(name or "")).name
    if not pure_name or pure_name.startswith("."):
        return False
    return PurePosixPath(pure_name).suffix.casefold() in IMAGE_EXTENSIONS


def get_comic_source_kind(path):
    source = Path(path)
    if source.is_dir():
        return "folder"
    if is_supported_comic_archive(source):
        return "archive"
    if is_supported_comic_document(source):
        return "pdf"
    return None


def get_comic_source_format(path):
    source = Path(path)
    if source.is_dir():
        return "Folder"

    suffix = source.suffix.casefold()
    if not suffix:
        return ""
    return suffix.lstrip(".").upper()


def normalize_loaded_image(image):
    normalized = ImageOps.exif_transpose(image)
    if normalized.mode not in ("RGB", "RGBA"):
        normalized = normalized.convert("RGB")
    return normalized.copy()


def require_py7zr():
    if py7zr is None:
        raise ComicReaderSupportError(
            "7z/CB7 support requires the optional dependency 'py7zr'. Please run install.bat first."
        )
    return py7zr


def require_pdfium():
    if pdfium is None:
        raise ComicReaderSupportError(
            "PDF support requires the optional dependency 'pypdfium2'. Please run install.bat first."
        )
    return pdfium


def require_rarfile():
    if rarfile is None:
        raise ComicReaderSupportError(
            "RAR/CBR support requires the optional dependency 'rarfile'. Please run install.bat first."
        )
    return rarfile


def ensure_rar_tool_available():
    rar_module = require_rarfile()
    try:
        return rar_module.tool_setup(force=True)
    except rar_module.RarCannotExec as exc:
        raise ComicReaderSupportError(
            f"RAR/CBR support requires one of these tools in PATH: {RAR_TOOL_HINT}."
        ) from exc


def get_optional_comic_support_status():
    pdf_available = pdfium is not None
    sevenzip_available = py7zr is not None
    rar_dependency_available = rarfile is not None
    rar_tool_available = False
    rar_message = ""

    if not rar_dependency_available:
        rar_message = "缺少 rarfile 依赖，请先运行 install.bat。"
    else:
        try:
            ensure_rar_tool_available()
            rar_tool_available = True
            rar_message = "已检测到可用的外部解包工具。"
        except ComicReaderSupportError as exc:
            rar_message = str(exc)

    return {
        "pdf": {
            "available": pdf_available,
            "message": "已启用。" if pdf_available else "缺少 pypdfium2 依赖，请先运行 install.bat。",
        },
        "sevenzip": {
            "available": sevenzip_available,
            "message": "已启用。" if sevenzip_available else "缺少 py7zr 依赖，请先运行 install.bat。",
        },
        "rar": {
            "available": rar_dependency_available and rar_tool_available,
            "dependency_available": rar_dependency_available,
            "tool_available": rar_tool_available,
            "message": rar_message,
        },
    }


def get_format_support_notice_lines():
    status = get_optional_comic_support_status()
    direct_formats = ["图片文件夹", "CBZ", "ZIP"]
    if status["pdf"]["available"]:
        direct_formats.append("PDF")
    if status["sevenzip"]["available"]:
        direct_formats.append("7z")

    lines = [
        f"直接支持：{' / '.join(direct_formats)}",
    ]

    if status["rar"]["available"]:
        lines.append("CBR / RAR：已启用")
    else:
        lines.append(f"CBR / RAR：{status['rar']['message']}")

    if not status["pdf"]["available"]:
        lines.append(f"PDF：{status['pdf']['message']}")
    if not status["sevenzip"]["available"]:
        lines.append(f"7z：{status['sevenzip']['message']}")

    return lines


def get_comic_source_requirement_message(path, action="处理"):
    source = Path(path)
    suffix = source.suffix.casefold()

    if suffix in RAR_ARCHIVE_EXTENSIONS:
        status = get_optional_comic_support_status()["rar"]
        if not status["available"]:
            return f"{action} {suffix.lstrip('.').upper()} 文件前，需要可用的外部解包工具。{status['message']}"
    elif suffix in SEVENZIP_ARCHIVE_EXTENSIONS and py7zr is None:
        return f"{action} 7z / CB7 文件前，请先运行 install.bat 安装 py7zr。"
    elif suffix in PDF_EXTENSIONS and pdfium is None:
        return f"{action} PDF 文件前，请先运行 install.bat 安装 pypdfium2。"

    return ""


def parse_pdf_page_number(page_name):
    try:
        page_number = int(str(page_name or "").strip())
    except (TypeError, ValueError):
        raise ValueError(f"Invalid PDF page identifier: {page_name}") from None

    if page_number <= 0:
        raise ValueError(f"Invalid PDF page number: {page_number}")
    return page_number


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


def list_recursive_folder_image_members(path):
    root_path = Path(path)
    if not root_path.is_dir():
        return []

    members = []
    for current_root, _, file_names in root_path.walk():
        current_path = Path(current_root)
        for file_name in file_names:
            if not is_image_name(file_name):
                continue
            relative_path = (current_path / file_name).relative_to(root_path).as_posix()
            members.append(relative_path)

    return sorted(members, key=natural_sort_key)


def list_zip_comic_pages(path):
    archive_path = Path(path)
    with zipfile.ZipFile(archive_path) as archive:
        pages = [
            member_name
            for member_name in archive.namelist()
            if not member_name.endswith("/")
            and "__MACOSX/" not in member_name
            and is_image_name(member_name)
        ]
    return sorted(pages, key=natural_sort_key)


def list_rar_comic_pages(path):
    archive_path = Path(path)
    rar_module = require_rarfile()
    with rar_module.RarFile(archive_path) as archive:
        pages = [
            member.filename
            for member in archive.infolist()
            if not member.is_dir()
            and "__MACOSX/" not in member.filename
            and is_image_name(member.filename)
        ]
    return sorted(pages, key=natural_sort_key)


def list_sevenzip_comic_pages(path):
    archive_path = Path(path)
    py7zr_module = require_py7zr()
    with py7zr_module.SevenZipFile(archive_path, "r") as archive:
        pages = [
            member_name
            for member_name in archive.getnames()
            if not member_name.endswith("/")
            and "__MACOSX/" not in member_name
            and is_image_name(member_name)
        ]
    return sorted(pages, key=natural_sort_key)


def list_archive_comic_pages(path):
    archive_path = Path(path)
    if not archive_path.is_file() or not is_supported_comic_archive(archive_path):
        return []

    suffix = archive_path.suffix.casefold()
    if suffix in ZIP_ARCHIVE_EXTENSIONS:
        return list_zip_comic_pages(archive_path)
    if suffix in RAR_ARCHIVE_EXTENSIONS:
        return list_rar_comic_pages(archive_path)
    if suffix in SEVENZIP_ARCHIVE_EXTENSIONS:
        return list_sevenzip_comic_pages(archive_path)
    return []


def list_pdf_comic_pages(path):
    pdf_path = Path(path)
    if not pdf_path.is_file() or not is_supported_comic_document(pdf_path):
        return []

    pdfium_module = require_pdfium()
    document = pdfium_module.PdfDocument(str(pdf_path))
    try:
        return [str(index) for index in range(1, len(document) + 1)]
    finally:
        document.close()


def list_comic_pages(path):
    source = Path(path)
    if source.is_dir():
        return list_folder_comic_pages(source)
    if source.is_file() and is_supported_comic_archive(source):
        return list_archive_comic_pages(source)
    if source.is_file() and is_supported_comic_document(source):
        return list_pdf_comic_pages(source)
    return []


def count_comic_pages(path):
    return len(list_comic_pages(path))


def iter_cbz_export_entries(path):
    source = Path(path)

    if source.is_dir():
        for relative_name in list_recursive_folder_image_members(source):
            yield relative_name, (source / Path(relative_name)).read_bytes()
        return

    if source.is_file() and is_supported_comic_archive(source):
        suffix = source.suffix.casefold()
        page_names = list_archive_comic_pages(source)

        if suffix in ZIP_ARCHIVE_EXTENSIONS:
            with zipfile.ZipFile(source) as archive:
                for page_name in page_names:
                    yield page_name, archive.read(page_name)
            return

        if suffix in RAR_ARCHIVE_EXTENSIONS:
            rar_module = require_rarfile()
            ensure_rar_tool_available()
            with rar_module.RarFile(source) as archive:
                for page_name in page_names:
                    yield page_name, archive.read(page_name)
            return

        if suffix in SEVENZIP_ARCHIVE_EXTENSIONS:
            py7zr_module = require_py7zr()
            with TemporaryDirectory() as temp_dir:
                with py7zr_module.SevenZipFile(source, "r") as archive:
                    archive.extract(path=temp_dir, targets=page_names)
                for page_name in page_names:
                    extracted_path = Path(temp_dir) / Path(*PurePosixPath(page_name).parts)
                    yield page_name, extracted_path.read_bytes()
            return

    if source.is_file() and is_supported_comic_document(source):
        page_names = list_pdf_comic_pages(source)
        width = max(3, len(str(len(page_names))))
        for index, page_name in enumerate(page_names, 1):
            image = load_comic_page_image(source, page_name)
            buffer = BytesIO()
            image.save(buffer, format="PNG")
            yield f"{index:0{width}d}.png", buffer.getvalue()
        return

    raise ValueError(f"Unsupported comic source: {source}")


def build_comic_entry(path):
    source = Path(path)
    pages = list_comic_pages(source)
    if not pages:
        return None

    kind = get_comic_source_kind(source)
    display_name = source.name if source.is_dir() else source.stem
    return {
        "path": str(source),
        "name": display_name,
        "kind": kind,
        "format": get_comic_source_format(source),
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
            if not is_supported_comic_source(child_path):
                continue
            try:
                entry = build_comic_entry(child_path)
            except Exception:
                continue
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


def normalize_reader_zoom_mode(value, fallback=DEFAULT_READER_ZOOM_MODE):
    mode = str(value or "").strip().lower()
    if mode in READER_ZOOM_MODES:
        return mode
    return str(fallback or DEFAULT_READER_ZOOM_MODE).strip().lower() or DEFAULT_READER_ZOOM_MODE


def clamp_reader_zoom_percent(value, fallback=100):
    try:
        zoom_percent = int(round(float(value)))
    except (TypeError, ValueError):
        zoom_percent = int(fallback)

    return max(MIN_READER_ZOOM_PERCENT, min(MAX_READER_ZOOM_PERCENT, zoom_percent))


def calculate_reader_image_size(
    image_size,
    viewport_size,
    zoom_mode=DEFAULT_READER_ZOOM_MODE,
    zoom_percent=100,
):
    image_width, image_height = image_size
    viewport_width, viewport_height = viewport_size

    image_width = max(int(image_width or 0), 1)
    image_height = max(int(image_height or 0), 1)
    viewport_width = max(int(viewport_width or 0), 1)
    viewport_height = max(int(viewport_height or 0), 1)

    normalized_mode = normalize_reader_zoom_mode(zoom_mode)
    if normalized_mode == "fit_width":
        scale = viewport_width / image_width
    elif normalized_mode == "manual":
        scale = clamp_reader_zoom_percent(zoom_percent) / 100
    else:
        scale = min(viewport_width / image_width, viewport_height / image_height)

    target_width = max(1, int(round(image_width * scale)))
    target_height = max(1, int(round(image_height * scale)))
    return target_width, target_height


def load_comic_page_image(path, page_name):
    source = Path(path)
    page_key = str(page_name or "").strip()
    if not page_key:
        raise ValueError("Missing page name")

    if source.is_dir():
        page_path = source / page_key
        with Image.open(page_path) as image:
            return normalize_loaded_image(image)

    if source.is_file() and is_supported_comic_archive(source):
        suffix = source.suffix.casefold()

        if suffix in ZIP_ARCHIVE_EXTENSIONS:
            with zipfile.ZipFile(source) as archive:
                with archive.open(page_key) as handle:
                    data = handle.read()
            with Image.open(BytesIO(data)) as image:
                return normalize_loaded_image(image)

        if suffix in RAR_ARCHIVE_EXTENSIONS:
            rar_module = require_rarfile()
            ensure_rar_tool_available()
            with rar_module.RarFile(source) as archive:
                with archive.open(page_key) as handle:
                    data = handle.read()
            with Image.open(BytesIO(data)) as image:
                return normalize_loaded_image(image)

        if suffix in SEVENZIP_ARCHIVE_EXTENSIONS:
            py7zr_module = require_py7zr()
            with TemporaryDirectory() as temp_dir:
                with py7zr_module.SevenZipFile(source, "r") as archive:
                    archive.extract(path=temp_dir, targets=[page_key])
                extracted_path = Path(temp_dir) / PurePosixPath(page_key)
                with Image.open(extracted_path) as image:
                    return normalize_loaded_image(image)

    if source.is_file() and is_supported_comic_document(source):
        pdfium_module = require_pdfium()
        page_number = parse_pdf_page_number(page_key)
        document = pdfium_module.PdfDocument(str(source))
        bitmap = None
        page = None
        try:
            if page_number > len(document):
                raise ValueError(f"PDF page out of range: {page_number}")
            page = document.get_page(page_number - 1)
            bitmap = page.render(scale=PDF_RENDER_SCALE)
            rendered_image = bitmap.to_pil()
            return normalize_loaded_image(rendered_image)
        finally:
            if bitmap is not None:
                bitmap.close()
            if page is not None:
                page.close()
            document.close()

    raise ValueError(f"Unsupported comic source: {source}")
