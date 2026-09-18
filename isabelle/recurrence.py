from datetime import datetime
from datetime import timezone
from zoneinfo import ZoneInfo
from zoneinfo import ZoneInfoNotFoundError

from dateutil.rrule import rrulestr

MAX_COUNT = 260
MAX_INTERVAL = 52
MAX_MATERIALISED = 104
MAX_HORIZON_YEARS = 5
DEFAULT_TIMEZONE = "UTC"

DAILY = "daily"
WEEKLY = "weekly"
MONTHLY = "monthly"
FORTNIGHTLY = "fortnightly"

FREQUENCIES = (DAILY, WEEKLY, MONTHLY)
WEEKDAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")

ENDS_COUNT = "count"
ENDS_UNTIL = "until"
ENDS_NEVER = "never"
ENDINGS = (ENDS_COUNT, ENDS_UNTIL, ENDS_NEVER)

_FREQ = {DAILY: "DAILY", WEEKLY: "WEEKLY", MONTHLY: "MONTHLY"}

_LABELS = {
    DAILY: ("Daily", "Every {n} days"),
    WEEKLY: ("Weekly", "Every {n} weeks"),
    MONTHLY: ("Monthly", "Every {n} months"),
}

_DAY_NAMES = {
    "MO": "Monday",
    "TU": "Tuesday",
    "WE": "Wednesday",
    "TH": "Thursday",
    "FR": "Friday",
    "SA": "Saturday",
    "SU": "Sunday",
}


def valid_timezone(name):
    if not name or not isinstance(name, str):
        return None
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return None
    return name


def _parse_until(value):
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo is None else (
            value.astimezone(timezone.utc).replace(tzinfo=None)
        )
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _error(message):
    return {"recurrence": message}, None


def _normalise_days(value):
    if value in (None, "", []):
        return []
    if not isinstance(value, (list, tuple)):
        return None

    days = []
    for raw in value:
        day = str(raw or "").strip().upper()[:2]
        if day not in WEEKDAYS:
            return None
        if day not in days:
            days.append(day)

    return sorted(days, key=WEEKDAYS.index)


def validate_recurrence(value, start=None):
    if value in (None, {}, ""):
        return {}, None

    if not isinstance(value, dict):
        return _error("recurrence must be an object")

    frequency = (value.get("frequency") or "").strip().lower()
    interval = value.get("interval", 1)

    if frequency == FORTNIGHTLY:
        frequency = WEEKLY
        interval = 2

    if frequency not in FREQUENCIES:
        return _error(f"frequency must be one of {', '.join(FREQUENCIES)}")

    if isinstance(interval, bool) or not isinstance(interval, int):
        return _error("interval must be a whole number")
    if interval < 1 or interval > MAX_INTERVAL:
        return _error(f"interval must be between 1 and {MAX_INTERVAL}")

    days = _normalise_days(value.get("byDay"))
    if days is None:
        return _error("byDay must be a list of weekdays like MO, TU")
    if days and frequency != WEEKLY:
        return _error("only a weekly series can pick weekdays")

    ends = value.get("ends")
    if ends is None:
        ends = {"type": ENDS_COUNT, "count": value.get("count")}
    if not isinstance(ends, dict):
        return _error("ends must be an object")

    kind = (ends.get("type") or "").strip().lower()
    if kind not in ENDINGS:
        return _error(f"ends.type must be one of {', '.join(ENDINGS)}")

    rule = {
        "frequency": frequency,
        "interval": interval,
        "byDay": days,
        "ends": {"type": kind},
        "timezone": value.get("timezone") or DEFAULT_TIMEZONE,
    }

    if valid_timezone(rule["timezone"]) is None:
        return _error("timezone must be an IANA name like Europe/London")

    if kind == ENDS_COUNT:
        count = ends.get("count")
        if isinstance(count, bool) or not isinstance(count, int):
            return _error("count must be a whole number")
        if count < 2:
            return _error("a series needs at least 2 dates")
        if count > MAX_COUNT:
            return _error(f"a series cannot run past {MAX_COUNT} dates")
        rule["ends"]["count"] = count

    if kind == ENDS_UNTIL:
        until = _parse_until(ends.get("until"))
        if until is None:
            return _error("ends.until must be a date")
        if start is not None and until <= start:
            return _error("ends.until must be after the first date")
        if start is not None and (until - start).days > MAX_HORIZON_YEARS * 366:
            return _error(f"a series cannot run past {MAX_HORIZON_YEARS} years")
        rule["ends"]["until"] = until

    return {}, rule


def _rrule_parts(rule):
    parts = [f"FREQ={_FREQ[rule['frequency']]}"]

    if rule.get("interval", 1) > 1:
        parts.append(f"INTERVAL={rule['interval']}")

    if rule.get("byDay"):
        parts.append(f"BYDAY={','.join(rule['byDay'])}")

    return parts


def to_rrule(rule) -> str:
    if not rule:
        return ""

    parts = _rrule_parts(rule)
    ends = rule.get("ends") or {}

    if ends.get("type") == ENDS_COUNT:
        parts.append(f"COUNT={ends['count']}")
    elif ends.get("type") == ENDS_UNTIL:
        parts.append(f"UNTIL={ends['until'].strftime('%Y%m%dT%H%M%SZ')}")

    return ";".join(parts)


def _local_rrule(rule, tz) -> str:
    parts = _rrule_parts(rule)
    ends = rule.get("ends") or {}

    if ends.get("type") == ENDS_COUNT:
        parts.append(f"COUNT={ends['count']}")
    elif ends.get("type") == ENDS_UNTIL:
        local_until = _to_local(ends["until"], tz)
        parts.append(f"UNTIL={local_until.strftime('%Y%m%dT%H%M%S')}")

    return ";".join(parts)


def is_endless(rule) -> bool:
    return bool(rule) and (rule.get("ends") or {}).get("type") == ENDS_NEVER


def _to_local(moment, tz):
    return moment.replace(tzinfo=timezone.utc).astimezone(tz).replace(tzinfo=None)


def _to_utc(moment, tz):
    return moment.replace(tzinfo=tz).astimezone(timezone.utc).replace(tzinfo=None)


def occurrences(start, end, rule, tz_name=None, limit=MAX_MATERIALISED):
    if not rule:
        return [(start, end)]

    tz = ZoneInfo(valid_timezone(tz_name or rule.get("timezone")) or DEFAULT_TIMEZONE)
    duration = end - start

    local_start = _to_local(start, tz)
    generator = rrulestr(_local_rrule(rule, tz), dtstart=local_start)

    out = []
    for local in generator:
        occurrence_start = _to_utc(local, tz)
        out.append((occurrence_start, occurrence_start + duration))
        if len(out) >= limit:
            break

    return out


def describe(rule):
    if not rule:
        return None

    singular, plural = _LABELS[rule["frequency"]]
    interval = rule.get("interval", 1)
    head = singular if interval == 1 else plural.format(n=interval)

    days = rule.get("byDay") or []
    if days:
        names = [_DAY_NAMES[day] for day in days]
        head = f"{head} on {', '.join(names[:-1])} and {names[-1]}" if len(
            names
        ) > 1 else f"{head} on {names[0]}"

    ends = rule.get("ends") or {}
    if ends.get("type") == ENDS_COUNT:
        return f"{head} · {ends['count']} dates"
    if ends.get("type") == ENDS_UNTIL:
        return f"{head} · until {ends['until'].date().isoformat()}"

    return f"{head} · ongoing"
