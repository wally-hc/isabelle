import json

THIS = "this"
ALL = "all"
RSVP_SCOPES = (THIS, ALL)


def read_rsvp_scope(value, default=THIS) -> str:
    scope = (value or "").strip().lower()
    return scope if scope in RSVP_SCOPES else default


def _as_mapping(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


def attendees_of(event) -> list:
    rsvp_data = _as_mapping(event.get("RSVPData"))
    legacy = event.get("InterestedUsers") or []

    ids = []
    seen = set()

    for entry in rsvp_data.values():
        slack_id = (entry or {}).get("slackId") if isinstance(entry, dict) else None
        if slack_id and slack_id not in seen:
            ids.append(slack_id)
            seen.add(slack_id)

    for slack_id in legacy:
        if slack_id and slack_id not in seen:
            ids.append(slack_id)
            seen.add(slack_id)

    return ids


def followers_of(series) -> list:
    if not series:
        return []

    out = []
    seen = set()
    for slack_id in series.get("Followers") or []:
        if slack_id and slack_id not in seen:
            out.append(slack_id)
            seen.add(slack_id)

    return out


def recipients_for(event, series=None) -> list:
    out = []
    seen = set()

    for slack_id in attendees_of(event) + followers_of(series):
        if slack_id not in seen:
            out.append(slack_id)
            seen.add(slack_id)

    return out


def toggle_follower(series, slack_id):
    current = followers_of(series)

    if not slack_id:
        return current, False

    if slack_id in current:
        return [existing for existing in current if existing != slack_id], False

    return current + [slack_id], True


def public_count(event) -> int:
    return len(attendees_of(event))
