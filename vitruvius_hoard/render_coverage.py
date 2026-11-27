"""Size and coverage metadata for rendered screenshots."""

MAX_FULL_PAGE_HEIGHT = 16_000


def capture_full_page(page, path, width):
    page_height = page.evaluate("() => document.documentElement.scrollHeight")
    height = min(page_height, MAX_FULL_PAGE_HEIGHT)
    png = page.screenshot(path=str(path), full_page=True, clip={
        "x": 0, "y": 0, "width": width, "height": height,
    })
    # PNG's IHDR carries the height that Chromium actually wrote.
    captured_height = int.from_bytes(png[20:24], "big")
    return {"h": captured_height, "page_height": page_height, "captured_height": captured_height,
            "truncated": captured_height < page_height}


def restore_capture_coverage(files, probe):
    """Recover coverage of earlier screenshots when their DOM height was saved."""
    dom = probe.get("dom") or {}
    for file in files:
        if not file.get("full_page") or "truncated" in file:
            continue
        page_height = dom.get(str(file["width"]), {}).get("page_height")
        captured_height = file.get("h")
        if isinstance(page_height, int) and page_height > 0 and isinstance(captured_height, int) and captured_height > 0:
            file.update(page_height=page_height, captured_height=captured_height, truncated=captured_height < page_height)


def capture_coverage(files):
    cropped = [
        {key: file[key] for key in ("width", "truncated", "page_height", "captured_height")}
        for file in files if file.get("truncated")
    ]
    return {"capture_truncation": cropped} if cropped else {}
