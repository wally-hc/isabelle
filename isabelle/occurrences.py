from datetime import timedelta
from datetime import timezone
from zoneinfo import ZoneInfo

from dateutil.rrule import rrulestr

from isabelle.recurrence import DEFAULT_TIMEZONE
from isabelle.recurrence import valid_timezone

MAX_PER_SERIES = 500
DEFAULT_DURATION = timedelta(hours=1)


def _to_local(moment, tz):
    return moment.replace(tzinfo=timezone.utc).astimezone(tz).replace(tzinfo=None)


def _to_utc(moment, tz):
    return moment.replace(tzinfo=tz).astimezone(timezone.utc).replace(tzinfo=None)


def expand(series, anchor, window_start, window_end, limit=MAX_PER_SERIES):
    rule = (series.get("Rule") or "").strip()
    if not rule or anchor is None or window_end < window_start:
        return []

    tz = ZoneInfo(valid_timezone(series.get("Timezone")) or DEFAULT_TIMEZONE)

    local_anchor = _to_local(anchor, tz)
    local_from = _to_local(window_start, tz)
    local_to = _to_local(window_end, tz)

    dates = rrulestr(rule, dtstart=local_anchor).between(
        local_from, local_to, inc=True
    )

    return [_to_utc(local, tz) for local in dates[:limit]]


def _key(series_id, moment):
    return f"{series_id}@{moment.isoformat()}"


PER_OCCURRENCE = (
    "id",
    "StartTime",
    "EndTime",
    "OccurrenceStart",
    "OverriddenFields",
    "RSVPData",
    "InterestedUsers",
    "InterestCount",
    "Calculation",
    "CalendarLink",
    "Cancelled",
    "CancellationType",
    "RawCancellation",
    "Sent1DayReminder",
    "Sent1HourReminder",
    "SentStartingReminder",
    "HasHappened",
    "rsvpMsg",
)


def template_from(rows):
    ordered = sorted(
        (r for r in rows if r.get("OccurrenceStart") or r.get("StartTime")),
        key=lambda r: r.get("OccurrenceStart") or r.get("StartTime"),
    )
    if not ordered:
        return {}

    anchor = ordered[0]
    return {
        key: value
        for key, value in anchor.items()
        if key not in PER_OCCURRENCE
    }


def synthesise(series_id, slot, template, duration):
    occurrence = dict(template)
    occurrence.update(
        {
            "id": None,
            "SeriesID": series_id,
            "OccurrenceStart": slot,
            "StartTime": slot,
            "EndTime": slot + (duration or DEFAULT_DURATION),
            "Cancelled": False,
            "InterestCount": 0,
            "Synthetic": True,
        }
    )
    return occurrence


def _duration_of(rows):
    for row in rows:
        start, end = row.get("StartTime"), row.get("EndTime")
        if start is not None and end is not None:
            return end - start
    return None


def merge(expanded, rows, *, include_cancelled=False):
    by_slot = {}
    loose = []
    by_series = {}

    for row in rows:
        series_id = row.get("SeriesID") or ""
        slot = row.get("OccurrenceStart")
        if series_id and slot is not None:
            by_slot[_key(series_id, slot)] = row
            by_series.setdefault(series_id, []).append(row)
        else:
            loose.append(row)

    templates = {
        series_id: template_from(group) for series_id, group in by_series.items()
    }
    durations = {
        series_id: _duration_of(group) for series_id, group in by_series.items()
    }

    out = list(loose)
    seen = set()

    for series_id, slot in expanded:
        key = _key(series_id, slot)
        seen.add(key)
        row = by_slot.get(key)

        if row is None:
            out.append(
                synthesise(
                    series_id,
                    slot,
                    templates.get(series_id, {}),
                    durations.get(series_id),
                )
            )
            continue

        out.append(row)

    for key, row in by_slot.items():
        if key not in seen:
            out.append(row)

    if not include_cancelled:
        out = [row for row in out if not row.get("Cancelled")]

    return sorted(
        out,
        key=lambda row: (row.get("StartTime") is None, row.get("StartTime")),
    )


MATERIALISE_FIELDS = (
    "Title",
    "Description",
    "RawDescription",
    "Leader",
    "LeaderSlackID",
    "Avatar",
    "EventLink",
    "RSVPFormURL",
    "Tags",
    "Approved",
    "AMA",
    "SeriesID",
)


def row_values_for(occurrence):
    values = {
        key: occurrence.get(key)
        for key in MATERIALISE_FIELDS
        if occurrence.get(key) is not None
    }

    values.update(
        {
            "StartTime": occurrence.get("StartTime"),
            "EndTime": occurrence.get("EndTime"),
            "OccurrenceStart": occurrence.get("OccurrenceStart"),
            "Cancelled": False,
            "InterestCount": 0,
            "RSVPData": {},
            "InterestedUsers": [],
            "OverriddenFields": [],
            "Sent1DayReminder": False,
            "Sent1HourReminder": False,
            "SentStartingReminder": False,
            "HasHappened": False,
        }
    )

    return values
