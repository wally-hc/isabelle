MONTHS = (
    "jan",
    "feb",
    "mar",
    "apr",
    "may",
    "jun",
    "jul",
    "aug",
    "sep",
    "oct",
    "nov",
    "dec",
)


def base_slug(title) -> str:
    return str(title or "").lower().replace(" ", "-").replace(":", "")


def date_suffix(start) -> str:
    if start is None:
        return ""
    try:
        return f"{MONTHS[start.month - 1]}-{start.day}-{start.year}"
    except (AttributeError, IndexError):
        return ""


def slug_for(title, start=None, series_id=None) -> str:
    base = base_slug(title)
    if not series_id:
        return base

    suffix = date_suffix(start)
    return f"{base}-{suffix}" if suffix else base
