import json
from pathlib import Path


DEFAULT_GETCOMICS_RESULTS = "10"
GETCOMICS_RESULTS_OPTIONS = ("5", "10", "20", "50")
GETCOMICS_VIEW_MODES = ("search", "favorites", "queue")
MAX_RECENT_GETCOMICS_SEARCHES = 10
MAX_CACHED_GETCOMICS_RESULTS = 100
DEFAULT_APPEARANCE_MODE = "Dark"
APPEARANCE_MODE_OPTIONS = ("Light", "Dark", "System")
DEFAULT_READER_ZOOM_MODE = "fit_window"
READER_ZOOM_MODE_OPTIONS = ("fit_window", "fit_width", "manual")
DEFAULT_READER_ZOOM_PERCENT = 100
MIN_READER_ZOOM_PERCENT = 25
MAX_READER_ZOOM_PERCENT = 400
DEFAULT_READER_FOCUS_MODE = False
DEFAULT_READER_SCROLL_FRACTION = 0.0
DEFAULT_WINDOWS_READER_FULLSCREEN_MODE = "smooth"
WINDOWS_READER_FULLSCREEN_MODE_OPTIONS = ("smooth", "exclusive")
DEFAULT_RENAME_API_URL = "https://api.deepseek.com/v1/chat/completions"
DEFAULT_RENAME_API_MODEL = "deepseek-chat"
DEFAULT_RENAME_API_TIMEOUT = 20
MIN_RENAME_API_TIMEOUT = 5
MAX_RENAME_API_TIMEOUT = 300


def normalize_reader_path_value(value, fallback=""):
    text = str(value or "").strip()
    if text:
        return text
    return str(fallback or "").strip()


def normalize_getcomics_results_value(value):
    text = str(value or "").strip()
    if text in GETCOMICS_RESULTS_OPTIONS:
        return text
    return DEFAULT_GETCOMICS_RESULTS


def normalize_appearance_mode(value):
    mode = str(value or "").strip()
    if mode in APPEARANCE_MODE_OPTIONS:
        return mode
    return DEFAULT_APPEARANCE_MODE


def normalize_recent_getcomics_searches(items):
    normalized = []
    seen = set()

    for item in items or []:
        if not isinstance(item, dict):
            continue

        query = str(item.get("query") or "").strip()
        if not query:
            continue

        date = str(item.get("date") or "").strip()
        results = normalize_getcomics_results_value(item.get("results"))
        key = (query.casefold(), date, results)
        if key in seen:
            continue

        seen.add(key)
        normalized.append(
            {
                "query": query,
                "date": date,
                "results": results,
            }
        )

        if len(normalized) >= MAX_RECENT_GETCOMICS_SEARCHES:
            break

    return normalized


def normalize_getcomics_page_value(value):
    try:
        page = int(value)
    except (TypeError, ValueError):
        return 0

    return max(0, page)


def normalize_reader_page_value(value):
    try:
        page = int(value)
    except (TypeError, ValueError):
        return 0

    return max(0, page)


def normalize_reader_zoom_mode(value):
    mode = str(value or "").strip().lower()
    if mode in READER_ZOOM_MODE_OPTIONS:
        return mode
    return DEFAULT_READER_ZOOM_MODE


def normalize_reader_zoom_percent(value):
    try:
        zoom_percent = int(round(float(value)))
    except (TypeError, ValueError):
        zoom_percent = DEFAULT_READER_ZOOM_PERCENT

    return max(MIN_READER_ZOOM_PERCENT, min(MAX_READER_ZOOM_PERCENT, zoom_percent))


def normalize_reader_focus_mode(value):
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off", ""}:
            return False
    if value is None:
        return DEFAULT_READER_FOCUS_MODE
    return bool(value)


def normalize_reader_scroll_fraction(value):
    try:
        fraction = float(value)
    except (TypeError, ValueError):
        return DEFAULT_READER_SCROLL_FRACTION

    if fraction != fraction:
        return DEFAULT_READER_SCROLL_FRACTION
    return max(0.0, min(1.0, fraction))


def normalize_getcomics_view_mode(value):
    mode = str(value or "").strip().lower()
    if mode in GETCOMICS_VIEW_MODES:
        return mode
    return "search"


def normalize_windows_reader_fullscreen_mode(value):
    mode = str(value or "").strip().lower()
    if mode in WINDOWS_READER_FULLSCREEN_MODE_OPTIONS:
        return mode
    return DEFAULT_WINDOWS_READER_FULLSCREEN_MODE


def normalize_rename_api_text_value(value, fallback=""):
    text = str(value or "").strip()
    if text:
        return text
    return str(fallback or "").strip()


def normalize_rename_api_timeout(value):
    try:
        timeout = int(round(float(value)))
    except (TypeError, ValueError):
        timeout = DEFAULT_RENAME_API_TIMEOUT

    return max(MIN_RENAME_API_TIMEOUT, min(MAX_RENAME_API_TIMEOUT, timeout))


def normalize_cached_getcomics_results(items):
    normalized = []
    seen_urls = set()

    for item in items or []:
        if isinstance(item, dict):
            url = str(item.get("url") or "").strip()
            title = str(item.get("title") or "").strip()
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            url = str(item[0] or "").strip()
            title = str(item[1] or "").strip()
        else:
            continue

        if not url or not title or url in seen_urls:
            continue

        seen_urls.add(url)
        normalized.append({"url": url, "title": title})

        if len(normalized) >= MAX_CACHED_GETCOMICS_RESULTS:
            break

    return normalized


def normalize_gui_state(payload, default_save_dir=""):
    source = payload if isinstance(payload, dict) else {}
    getcomics = source.get("getcomics") if isinstance(source.get("getcomics"), dict) else {}
    reader = source.get("reader") if isinstance(source.get("reader"), dict) else {}
    settings = source.get("settings") if isinstance(source.get("settings"), dict) else {}
    save_dir = str(getcomics.get("save_dir") or "").strip() or str(default_save_dir or "").strip()
    last_results = normalize_cached_getcomics_results(getcomics.get("last_results"))
    last_page = normalize_getcomics_page_value(getcomics.get("last_page"))
    favorites = normalize_cached_getcomics_results(getcomics.get("favorites"))
    queue_items = normalize_cached_getcomics_results(getcomics.get("queue_items"))
    view_mode = normalize_getcomics_view_mode(getcomics.get("view_mode"))
    reader_source_path = normalize_reader_path_value(reader.get("source_path"), fallback=default_save_dir)
    reader_selected_path = normalize_reader_path_value(reader.get("selected_path"))
    reader_active_path = normalize_reader_path_value(reader.get("active_path"))
    reader_active_page = normalize_reader_page_value(reader.get("active_page"))
    reader_zoom_mode = normalize_reader_zoom_mode(reader.get("zoom_mode"))
    reader_zoom_percent = normalize_reader_zoom_percent(reader.get("zoom_percent"))
    reader_focus_mode = normalize_reader_focus_mode(reader.get("focus_mode"))
    reader_scroll_x = normalize_reader_scroll_fraction(reader.get("scroll_x"))
    reader_scroll_y = normalize_reader_scroll_fraction(reader.get("scroll_y"))
    appearance_mode = normalize_appearance_mode(settings.get("appearance_mode"))
    reader_windows_fullscreen_mode = normalize_windows_reader_fullscreen_mode(
        settings.get("reader_windows_fullscreen_mode")
    )
    rename_api_key = normalize_rename_api_text_value(settings.get("rename_api_key"))
    rename_api_url = normalize_rename_api_text_value(
        settings.get("rename_api_url"),
        fallback=DEFAULT_RENAME_API_URL,
    )
    rename_api_model = normalize_rename_api_text_value(
        settings.get("rename_api_model"),
        fallback=DEFAULT_RENAME_API_MODEL,
    )
    rename_api_timeout = normalize_rename_api_timeout(settings.get("rename_api_timeout"))

    if last_results and last_page <= 0:
        last_page = 1
    if not last_results:
        last_page = 0
    if view_mode == "favorites" and not favorites:
        view_mode = "search"
    if view_mode == "queue" and not queue_items:
        view_mode = "search"
    if reader_active_path and reader_active_page <= 0:
        reader_active_page = 1
    if reader_active_path and not reader_selected_path:
        reader_selected_path = reader_active_path
    if not reader_active_path:
        reader_scroll_x = DEFAULT_READER_SCROLL_FRACTION
        reader_scroll_y = DEFAULT_READER_SCROLL_FRACTION

    return {
        "getcomics": {
            "query": str(getcomics.get("query") or "").strip(),
            "date": str(getcomics.get("date") or "").strip(),
            "results": normalize_getcomics_results_value(getcomics.get("results")),
            "save_dir": save_dir,
            "recent_searches": normalize_recent_getcomics_searches(getcomics.get("recent_searches")),
            "view_mode": view_mode,
            "favorites": favorites,
            "queue_items": queue_items,
            "last_page": last_page,
            "last_results": last_results,
        },
        "reader": {
            "source_path": reader_source_path,
            "selected_path": reader_selected_path,
            "active_path": reader_active_path,
            "active_page": reader_active_page,
            "zoom_mode": reader_zoom_mode,
            "zoom_percent": reader_zoom_percent,
            "focus_mode": reader_focus_mode,
            "scroll_x": reader_scroll_x,
            "scroll_y": reader_scroll_y,
        },
        "settings": {
            "appearance_mode": appearance_mode,
            "reader_windows_fullscreen_mode": reader_windows_fullscreen_mode,
            "rename_api_key": rename_api_key,
            "rename_api_url": rename_api_url,
            "rename_api_model": rename_api_model,
            "rename_api_timeout": rename_api_timeout,
        },
    }


def load_gui_state(path, default_save_dir=""):
    state_path = Path(path)
    if not state_path.exists():
        return normalize_gui_state({}, default_save_dir=default_save_dir)

    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return normalize_gui_state({}, default_save_dir=default_save_dir)

    return normalize_gui_state(payload, default_save_dir=default_save_dir)


def save_gui_state(path, state, default_save_dir=""):
    state_path = Path(path)
    payload = normalize_gui_state(state, default_save_dir=default_save_dir)

    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        return False

    return True


def load_getcomics_favorites_file(path):
    favorites_path = Path(path)

    try:
        payload = json.loads(favorites_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return []

    if isinstance(payload, dict):
        items = payload.get("favorites")
    else:
        items = payload

    return normalize_cached_getcomics_results(items)


def save_getcomics_favorites_file(path, favorites):
    favorites_path = Path(path)
    payload = {
        "favorites": normalize_cached_getcomics_results(favorites),
    }

    try:
        favorites_path.parent.mkdir(parents=True, exist_ok=True)
        favorites_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        return False

    return True


def build_getcomics_history_label(item):
    query = str(item.get("query") or "").strip()
    date = str(item.get("date") or "").strip()
    results = normalize_getcomics_results_value(item.get("results"))

    parts = []
    if date:
        parts.append(date)
    parts.append(f"{results} results")

    if not query:
        return "Recent Search"
    return f"{query} ({' / '.join(parts)})"


def upsert_recent_getcomics_search(history, item):
    normalized_history = normalize_recent_getcomics_searches(history)
    normalized_item = normalize_recent_getcomics_searches([item])
    if not normalized_item:
        return normalized_history

    candidate = normalized_item[0]
    candidate_key = (
        candidate["query"].casefold(),
        candidate["date"],
        candidate["results"],
    )

    remaining = [
        entry
        for entry in normalized_history
        if (
            entry["query"].casefold(),
            entry["date"],
            entry["results"],
        ) != candidate_key
    ]
    return [candidate, *remaining][:MAX_RECENT_GETCOMICS_SEARCHES]
