import uuid
from datetime import date
from datetime import datetime
from datetime import timedelta
from datetime import timezone

from starlette.requests import Request
from starlette.responses import JSONResponse

from isabelle.occurrences import expand
from isabelle.occurrences import merge
from isabelle.tables import Event
from isabelle.tables import Series

SECRET_COLUMNS = ("RSVPData", "InterestedUsers")

DEFAULT_PAGE_SIZE = 1000
MAX_PAGE_SIZE = 1000
DEFAULT_WINDOW_DAYS = 365
MAX_WINDOW_DAYS = 365 * 5


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _public_columns():
    return [
        column
        for column in Event._meta.columns
        if column._meta.name not in SECRET_COLUMNS
    ]


def _parse_int(value, fallback):
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _parse_moment(value, fallback):
    if not value:
        return fallback
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return fallback
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _plain(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    return value


def _serialise(row):
    return {key: _plain(value) for key, value in row.items()}


async def occurrences_in(window_start, window_end, *, include_cancelled=False):
    rows = await Event.select(*_public_columns()).output(load_json=True)

    all_series = await Series.select()
    anchors = {}
    for row in rows:
        series_id = row.get("SeriesID") or ""
        slot = row.get("OccurrenceStart") or row.get("StartTime")
        if not series_id or slot is None:
            continue
        if series_id not in anchors or slot < anchors[series_id]:
            anchors[series_id] = slot

    expanded = []
    rules = {}
    for series in all_series:
        series_id = series.get("SeriesID")
        anchor = series.get("AnchorStart") or anchors.get(series_id)
        rules[series_id] = {
            "SeriesRule": series.get("Rule") or "",
            "SeriesTimezone": series.get("Timezone") or "",
            "SeriesAnchor": anchor,
        }
        for slot in expand(series, anchor, window_start, window_end):
            expanded.append((series_id, slot))

    merged = merge(expanded, rows, include_cancelled=include_cancelled)

    for row in merged:
        series_id = row.get("SeriesID")
        if series_id and series_id in rules:
            row.update(rules[series_id])

    return merged


async def events_feed(request: Request):
    params = request.query_params

    now = _now()
    window_start = _parse_moment(
        params.get("__from"), now - timedelta(days=DEFAULT_WINDOW_DAYS * 5)
    )
    window_end = _parse_moment(
        params.get("__to"), now + timedelta(days=DEFAULT_WINDOW_DAYS)
    )

    if (window_end - window_start).days > MAX_WINDOW_DAYS * 2:
        window_end = window_start + timedelta(days=MAX_WINDOW_DAYS * 2)

    rows = await occurrences_in(window_start, window_end, include_cancelled=True)

    order = params.get("__order") or ""
    if order.lstrip("-") == "StartTime" and order.startswith("-"):
        rows = list(reversed(rows))

    page_size = min(
        max(_parse_int(params.get("__page_size"), DEFAULT_PAGE_SIZE), 1), MAX_PAGE_SIZE
    )
    page = max(_parse_int(params.get("__page"), 1), 1)
    start = (page - 1) * page_size

    return JSONResponse(
        {"rows": [_serialise(row) for row in rows[start : start + page_size]]}
    )
