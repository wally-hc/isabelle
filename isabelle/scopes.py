THIS = "this"
FOLLOWING = "following"
ALL = "all"
SCOPES = (THIS, FOLLOWING, ALL)

SHARED_FIELDS = (
    "Title",
    "Description",
    "RawDescription",
    "EventLink",
    "RSVPFormURL",
    "Tags",
    "LeaderSlackID",
    "Leader",
    "Avatar",
)

TIME_FIELDS = ("StartTime", "EndTime")


def read_scope(value, default=THIS) -> str:
    scope = (value or "").strip().lower()
    return scope if scope in SCOPES else default


def changed_fields(before, updates) -> list:
    out = []
    for field in SHARED_FIELDS + TIME_FIELDS:
        if field not in updates:
            continue
        if before.get(field) != updates[field]:
            out.append(field)
    return out


def merge_overrides(existing, newly_changed) -> list:
    out = list(existing or [])
    for field in newly_changed:
        if field not in out:
            out.append(field)
    return sorted(out)


def time_shift(before, updates):
    start_before = before.get("StartTime")
    start_after = updates.get("StartTime")
    if start_before is None or start_after is None:
        return None

    delta = start_after - start_before
    return delta if delta else None


def updates_for_sibling(sibling, updates, shift):
    overridden = set(sibling.get("OverriddenFields") or [])

    out = {}
    for field in SHARED_FIELDS:
        if field in updates and field not in overridden:
            out[field] = updates[field]

    if shift and "StartTime" not in overridden:
        start = sibling.get("StartTime")
        end = sibling.get("EndTime")
        if start is not None:
            out["StartTime"] = start + shift
        if end is not None:
            out["EndTime"] = end + shift

    return out


def siblings_in_scope(scope, anchor, rows):
    if scope == THIS:
        return []

    anchor_id = anchor.get("id")
    pivot = anchor.get("OccurrenceStart") or anchor.get("StartTime")

    out = []
    for row in rows:
        if row.get("id") == anchor_id:
            continue
        if row.get("Cancelled"):
            continue

        slot = row.get("OccurrenceStart") or row.get("StartTime")
        if scope == FOLLOWING and (slot is None or pivot is None or slot <= pivot):
            continue

        out.append(row)

    return out
