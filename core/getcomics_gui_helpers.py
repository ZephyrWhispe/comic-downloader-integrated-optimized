def collect_selected_getcomics_results(results_data, selected_indices):
    selected_results = []
    seen_urls = set()

    for raw_index in selected_indices or []:
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            continue

        if index < 0 or index >= len(results_data):
            continue

        url, title = results_data[index]
        if not url or url in seen_urls:
            continue

        seen_urls.add(url)
        selected_results.append((url, title))

    return selected_results


def format_getcomics_results_for_clipboard(results):
    blocks = []

    for url, title in results or []:
        clean_url = str(url or "").strip()
        clean_title = str(title or "").strip()
        if not clean_url or not clean_title:
            continue
        blocks.append(f"{clean_title}\n{clean_url}")

    return "\n\n".join(blocks)


def normalize_getcomics_result_entries(results):
    normalized = []
    seen_urls = set()

    for item in results or []:
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
        normalized.append((url, title))

    return normalized


def upsert_getcomics_results(existing_results, new_results):
    normalized_new = normalize_getcomics_result_entries(new_results)
    normalized_existing = normalize_getcomics_result_entries(existing_results)
    new_urls = {url for url, _ in normalized_new}

    remaining_existing = [
        (url, title)
        for url, title in normalized_existing
        if url not in new_urls
    ]
    return [*normalized_new, *remaining_existing]


def remove_getcomics_results(existing_results, results_to_remove):
    normalized_existing = normalize_getcomics_result_entries(existing_results)
    remove_urls = {url for url, _ in normalize_getcomics_result_entries(results_to_remove)}
    if not remove_urls:
        return normalized_existing

    return [
        (url, title)
        for url, title in normalized_existing
        if url not in remove_urls
    ]
