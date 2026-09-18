from datetime import datetime
from datetime import timezone

from isabelle.tables import AuditEntry

APPROVED = "approved"
REJECTED = "rejected"
CANCELLED = "cancelled"
WITHDRAWN = "withdrawn"
EDITED = "edited"

ACTIONS = (APPROVED, REJECTED, CANCELLED, WITHDRAWN, EDITED)

MAX_REASON = 2000
MAX_PAGE_SIZE = 100


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def entry_for(action, actor, event, *, scope=None, reason=None, count=1):
    return {
        "At": _now(),
        "ActorSlackID": (actor or "")[:32],
        "Action": action if action in ACTIONS else EDITED,
        "EventID": str(event.get("id") or "")[:36],
        "SeriesID": (event.get("SeriesID") or "")[:36],
        "EventTitle": event.get("Title") or "",
        "Scope": (scope or "this")[:16],
        "Reason": (reason or "")[:MAX_REASON],
        "Affected": max(int(count or 1), 0),
    }


async def record(action, actor, event, *, scope=None, reason=None, count=1):
    await AuditEntry.insert(
        AuditEntry(
            **entry_for(
                action, actor, event, scope=scope, reason=reason, count=count
            )
        )
    )


def serialise(row):
    at = row.get("At")
    return {
        "id": str(row.get("id")),
        "at": at.isoformat() + "Z" if at else None,
        "actorSlackId": row.get("ActorSlackID") or None,
        "action": row.get("Action"),
        "eventId": row.get("EventID") or None,
        "seriesId": row.get("SeriesID") or None,
        "eventTitle": row.get("EventTitle") or None,
        "scope": row.get("Scope") or None,
        "reason": row.get("Reason") or None,
        "affected": row.get("Affected") or 1,
    }


def describe(row):
    action = row.get("Action")
    title = row.get("EventTitle") or "an event"
    affected = row.get("Affected") or 1
    dates = f" ({affected} dates)" if affected > 1 else ""

    verbs = {
        APPROVED: "approved",
        REJECTED: "rejected",
        CANCELLED: "cancelled",
        WITHDRAWN: "withdrew",
        EDITED: "edited",
    }

    return f"{verbs.get(action, 'changed')} {title}{dates}"
