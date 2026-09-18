import json
import logging
import secrets
from datetime import datetime
from datetime import timezone

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from isabelle.authz import can_edit_event
from isabelle.authz import can_submit
from isabelle.authz import is_leader
from isabelle.authz import can_reassign_leader
from isabelle.authz import is_reviewer
from isabelle import audit
from isabelle.attendance import followers_of
from isabelle.occurrences import expand
from isabelle.occurrences import merge
from isabelle.occurrences import row_values_for
from isabelle.tables import Event
from isabelle.scopes import changed_fields
from isabelle.scopes import merge_overrides
from isabelle.scopes import read_scope
from isabelle.scopes import siblings_in_scope
from isabelle.scopes import time_shift
from isabelle.scopes import updates_for_sibling
from isabelle.scopes import ALL
from isabelle.scopes import THIS
from isabelle.slugs import slug_for
from isabelle.tables import AuditEntry
from isabelle.tables import Series
from isabelle.tables import Submitter
from isabelle.utils.slack_names import search_channels
from isabelle.utils.slack_names import slack_names
from isabelle.utils.database import get_cachet_pfp
from isabelle.utils.env import env
from isabelle.utils.notify import notify_attendees_cancelled
from isabelle.utils.notify import notify_event_approved
from isabelle.utils.notify import notify_event_cancelled
from isabelle.utils.notify import notify_event_edited
from isabelle.utils.rich_text import column_to_markdown
from isabelle.utils.rich_text import from_rich_text_column
from isabelle.utils.slack import app
from isabelle.web_submission import as_rich_text
from isabelle.web_submission import validate

class WriteFailed(Exception):
    pass


MAX_REASON = 2000
MAX_PENDING_PER_SUBMITTER = 5

LIST_COLUMNS = (
    "id",
    "Title",
    "Description",
    "StartTime",
    "EndTime",
    "LeaderSlackID",
    "Leader",
    "Avatar",
    "EventLink",
    "RSVPFormURL",
    "Tags",
    "Approved",
    "SeriesID",
    "OccurrenceStart",
    "OverriddenFields",
    "Cancelled",
    "CancellationType",
    "RawCancellation",
    "InterestCount",
    "CalendarLink",
    "Calculation",
)


def _unauthorized():
    return JSONResponse({"error": "unauthorized"}, status_code=401)


def _forbidden(message="forbidden"):
    return JSONResponse({"error": message}, status_code=403)


def _not_found():
    return JSONResponse({"error": "event not found"}, status_code=404)


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _check_secret(req: Request) -> bool:
    provided = req.headers.get("x-internal-secret", "")
    return secrets.compare_digest(provided, env.events_rsvp_secret)


async def _body(req: Request):
    try:
        return await req.json()
    except Exception:
        return None


def serialise(event) -> dict:
    return {
        "id": str(event.get("id")),
        "title": event.get("Title"),
        "description": event.get("Description"),
        "startTime": _utc_iso(event.get("StartTime")),
        "endTime": _utc_iso(event.get("EndTime")),
        "leaderSlackId": event.get("LeaderSlackID"),
        "leader": event.get("Leader"),
        "avatar": event.get("Avatar"),
        "eventLink": event.get("EventLink"),
        "rsvpFormUrl": event.get("RSVPFormURL"),
        "tags": event.get("Tags") or [],
        "approved": bool(event.get("Approved")),
        "cancelled": bool(event.get("Cancelled")),
        "cancellationType": event.get("CancellationType") or None,
        "cancellationReason": column_to_markdown(event.get("RawCancellation")),
        "interestCount": event.get("InterestCount") or 0,
        "calendarLink": event.get("CalendarLink"),
        "slug": event.get("Calculation"),
        "seriesId": event.get("SeriesID") or None,
        "occurrenceStart": _utc_iso(event.get("OccurrenceStart")),
        "overriddenFields": list(event.get("OverriddenFields") or []),
    }


def _utc_iso(value):
    if not value:
        return None
    return value.isoformat() + "Z"


def _attendee_slack_ids(event) -> list:
    rsvp_data = event.get("RSVPData") or {}
    if not isinstance(rsvp_data, dict):
        return []
    ids = [v.get("slackId") for v in rsvp_data.values() if isinstance(v, dict)]
    legacy = event.get("InterestedUsers") or []
    return list(dict.fromkeys([i for i in ids + list(legacy) if i]))


def _scope_of(body):
    asked = (body.get("scope") or "").strip().lower()
    return ALL if asked == "series" else asked


async def materialise(series_id, occurrence_start):
    if not series_id or occurrence_start is None:
        return None

    existing = (
        await Event.select()
        .where(
            Event.SeriesID == series_id,
            Event.OccurrenceStart == occurrence_start,
        )
        .output(load_json=True)
        .first()
    )
    if existing:
        return existing

    series = await Series.select().where(Series.SeriesID == series_id).first()
    if not series:
        return None

    rows = await _series_rows(series_id)
    anchor = series.get("AnchorStart") or (
        min(
            (r.get("OccurrenceStart") or r.get("StartTime") for r in rows),
            default=None,
        )
    )

    slots = expand(series, anchor, occurrence_start, occurrence_start)
    if occurrence_start not in slots:
        return None

    occurrence = next(
        (
            o
            for o in merge([(series_id, occurrence_start)], rows)
            if o.get("Synthetic")
        ),
        None,
    )
    if occurrence is None:
        return None

    values = row_values_for(occurrence)
    values["Calculation"] = slug_for(
        values.get("Title"), values.get("StartTime"), series_id
    )

    await Event.insert(Event(**values))

    return (
        await Event.select()
        .where(
            Event.SeriesID == series_id,
            Event.OccurrenceStart == occurrence_start,
        )
        .output(load_json=True)
        .first()
    )


async def approve_event(req: Request):
    if not _check_secret(req):
        return _unauthorized()

    body = await _body(req)
    if body is None:
        return JSONResponse({"error": "invalid json"}, status_code=400)

    actor = (body.get("actor_slack_id") or "").strip()
    if not actor:
        return JSONResponse({"error": "actor_slack_id is required"}, status_code=422)

    if not is_reviewer(actor):
        return _forbidden()

    event_id = req.path_params["event_id"]
    event = await env.database.get_event(event_id)
    if not event:
        return _not_found()

    if event.get("Cancelled"):
        return JSONResponse({"error": "event is cancelled"}, status_code=409)
    if event.get("Approved"):
        return JSONResponse({"error": "already approved"}, status_code=409)

    scope = read_scope(_scope_of(body))
    series_id = event.get("SeriesID") or ""
    also = 0
    updated = None

    rows = await _series_rows(series_id) if scope != THIS and series_id else []

    try:
        async with Event._meta.db.transaction():
            updated = await env.database.update_event(event_id, Approved=True)
            if not updated:
                raise WriteFailed()

            for sibling in siblings_in_scope(scope, event, rows):
                if sibling.get("Approved"):
                    continue
                if await env.database.update_event(
                    str(sibling["id"]), Approved=True
                ):
                    also += 1

            await audit.record(
                audit.APPROVED, actor, updated, scope=scope, count=also + 1
            )
    except WriteFailed:
        return JSONResponse({"error": "could not approve event"}, status_code=500)

    await notify_event_approved(updated, actor, series_count=also + 1)

    return JSONResponse({**serialise(updated), "seriesApproved": also + 1})


async def cancel_event(req: Request):
    if not _check_secret(req):
        return _unauthorized()

    body = await _body(req)
    if body is None:
        return JSONResponse({"error": "invalid json"}, status_code=400)

    actor = (body.get("actor_slack_id") or "").strip()
    if not actor:
        return JSONResponse({"error": "actor_slack_id is required"}, status_code=422)

    event_id = req.path_params["event_id"]
    event = await env.database.get_event(event_id)
    if not event:
        return _not_found()

    if event.get("Cancelled"):
        return JSONResponse({"error": "already cancelled"}, status_code=409)

    withdrawing = is_leader(actor, event) and not event.get("Approved")

    if not is_reviewer(actor) and not withdrawing:
        return _forbidden()

    end_time = event.get("EndTime")
    if event.get("Approved") and end_time and end_time < _now():
        return JSONResponse({"error": "event has already ended"}, status_code=409)

    reason = (body.get("reason") or "").strip()
    if not reason and not withdrawing:
        return JSONResponse(
            {"error": "invalid submission", "errors": {"reason": "reason is required"}},
            status_code=422,
        )
    if len(reason) > MAX_REASON:
        return JSONResponse(
            {
                "error": "invalid submission",
                "errors": {"reason": f"reason must be under {MAX_REASON} characters"},
            },
            status_code=422,
        )

    kind = body.get("kind")
    if withdrawing:
        kind = "withdrawn"
    elif kind not in ("rejected", "cancelled"):
        kind = "cancelled" if event.get("Approved") else "rejected"

    was_public = bool(event.get("Approved"))
    attendees = _attendee_slack_ids(event) if was_public else []
    series_id = event.get("SeriesID") or ""

    scope = read_scope(_scope_of(body))
    pending_only = kind in ("rejected", "withdrawn")
    also = 0
    updated = None

    rows = await _series_rows(series_id) if scope != THIS and series_id else []

    try:
        async with Event._meta.db.transaction():
            updated = await env.database.cancel_event(
                event_id, reason=reason, kind=kind
            )
            if not updated:
                raise WriteFailed()

            for sibling in siblings_in_scope(scope, event, rows):
                if pending_only and sibling.get("Approved"):
                    continue
                if not pending_only and sibling.get("EndTime") is not None:
                    if sibling["EndTime"] < _now():
                        continue

                if kind == "cancelled":
                    attendees += _attendee_slack_ids(sibling)

                if await env.database.cancel_event(
                    str(sibling["id"]), reason=reason, kind=kind
                ):
                    also += 1

            await audit.record(
                kind if kind in audit.ACTIONS else audit.CANCELLED,
                actor,
                updated,
                scope=scope,
                reason=reason,
                count=also + 1,
            )
    except WriteFailed:
        return JSONResponse({"error": "could not cancel event"}, status_code=500)

    reason_block = from_rich_text_column(updated.get("RawCancellation"))
    await notify_event_cancelled(updated, actor, reason_block, kind=kind)

    if kind == "cancelled" and attendees:
        await notify_attendees_cancelled(
            updated, list(dict.fromkeys(attendees)), reason
        )

    return JSONResponse({**serialise(updated), "seriesCancelled": also + 1})


async def _series_rows(series_id):
    if not series_id:
        return []

    return (
        await Event.select()
        .where(Event.SeriesID == series_id)
        .order_by(Event.StartTime)
        .output(load_json=True)
    )


async def edit_event(req: Request):
    if not _check_secret(req):
        return _unauthorized()

    body = await _body(req)
    if body is None:
        return JSONResponse({"error": "invalid json"}, status_code=400)

    actor = (body.get("actor_slack_id") or "").strip()
    if not actor:
        return JSONResponse({"error": "actor_slack_id is required"}, status_code=422)

    event_id = req.path_params["event_id"]
    event = await env.database.get_event(event_id)
    if not event:
        return _not_found()

    if not can_edit_event(actor, event):
        return _forbidden()

    if event.get("Cancelled"):
        return JSONResponse({"error": "event is cancelled"}, status_code=409)

    requested_leader = (body.get("leader_slack_id") or "").strip()
    current_leader = event.get("LeaderSlackID")
    if requested_leader and requested_leader != current_leader:
        if not can_reassign_leader(actor):
            return _forbidden("only reviewers can reassign the event leader")
    else:
        requested_leader = current_leader

    errors, values = validate(
        {**body, "leader_slack_id": requested_leader}, env.event_tags
    )
    if errors:
        return JSONResponse(
            {"error": "invalid submission", "errors": errors}, status_code=422
        )

    updates = {
        "Title": values["title"],
        "Description": values["description"],
        "RawDescription": json.dumps(
            {"type": "rich_text", "elements": as_rich_text(values["description"])}
        ),
        "StartTime": values["start_time"],
        "EndTime": values["end_time"],
        "EventLink": values["event_link"],
        "RSVPFormURL": values["rsvp_form_url"],
        "Tags": values["tags"],
    }

    if requested_leader != current_leader:
        leader_name = event.get("Leader")
        try:
            slack_user = await app._async_client.users_info(user=requested_leader)
            profile = slack_user["user"]["profile"]
            leader_name = (
                profile.get("real_name") or profile.get("display_name") or leader_name
            )
        except Exception as error:
            logging.warning(
                "Could not resolve Slack name for %s: %s", requested_leader, error
            )
        updates["LeaderSlackID"] = requested_leader
        updates["Leader"] = leader_name
        updates["Avatar"] = get_cachet_pfp(requested_leader)

    scope = read_scope(body.get("scope"))
    series_id = event.get("SeriesID") or ""

    if scope != THIS and not series_id:
        scope = THIS

    touched = changed_fields(event, updates)
    shift = time_shift(event, updates)

    if scope == THIS and series_id:
        updates["OverriddenFields"] = merge_overrides(
            event.get("OverriddenFields"), touched
        )

    also = 0
    updated = None

    rows = await _series_rows(series_id) if scope != THIS else []

    try:
        async with Event._meta.db.transaction():
            updated = await env.database.update_event(event_id, **updates)
            if not updated:
                raise WriteFailed()

            for sibling in siblings_in_scope(scope, event, rows):
                changes = updates_for_sibling(sibling, updates, shift)
                if not changes:
                    continue
                if await env.database.update_event(str(sibling["id"]), **changes):
                    also += 1

            await audit.record(
                audit.EDITED, actor, updated, scope=scope, count=also + 1
            )
    except WriteFailed:
        return JSONResponse({"error": "could not update event"}, status_code=500)

    await notify_event_edited(updated, actor)

    return JSONResponse({**serialise(updated), "alsoChanged": also})


async def get_manageable_event(req: Request):
    if not _check_secret(req):
        return _unauthorized()

    actor = (req.query_params.get("actor_slack_id") or "").strip()
    if not actor:
        return JSONResponse({"error": "actor_slack_id is required"}, status_code=422)

    event = await env.database.get_event(req.path_params["event_id"])
    if not event:
        return _not_found()

    if not can_edit_event(actor, event):
        return _forbidden()

    return JSONResponse(serialise(event))


async def list_events(req: Request):
    if not _check_secret(req):
        return _unauthorized()

    actor = (req.query_params.get("actor_slack_id") or "").strip()
    if not actor:
        return JSONResponse({"error": "actor_slack_id is required"}, status_code=422)

    scope = req.query_params.get("scope", "mine")
    if scope not in ("mine", "pending", "running"):
        return JSONResponse({"error": "unknown scope"}, status_code=422)

    columns = [getattr(Event, name) for name in LIST_COLUMNS]
    query = Event.select(*columns)

    if scope == "mine":
        query = query.where(Event.LeaderSlackID == actor)
    elif scope == "running":
        if not is_reviewer(actor):
            return _forbidden()
        query = query.where(
            Event.Approved == True,
            Event.Cancelled == False,
            Event.EndTime >= _now(),
        )
    else:
        if not is_reviewer(actor):
            return _forbidden()
        query = query.where(Event.Approved == False, Event.Cancelled == False)
        if req.query_params.get("include_past") != "true":
            query = query.where(Event.EndTime >= _now())

    rows = await query.order_by(Event.StartTime).output(load_json=True)

    follower_counts = {}
    series_ids = {row.get("SeriesID") for row in rows if row.get("SeriesID")}
    if series_ids:
        for series in await Series.select().where(
            Series.SeriesID.is_in(list(series_ids))
        ):
            follower_counts[series["SeriesID"]] = len(followers_of(series))

    return JSONResponse(
        {
            "events": [
                {
                    **serialise(row),
                    "followerCount": follower_counts.get(row.get("SeriesID"), 0),
                }
                for row in rows
            ]
        }
    )


async def allowlisted_ids() -> list:
    rows = await Submitter.select(Submitter.SlackID)
    return [row["SlackID"] for row in rows if row.get("SlackID")]


async def may_submit(email, slack_id) -> bool:
    return can_submit(email, slack_id, await allowlisted_ids())


async def pending_submission_count(slack_id) -> int:
    rows = await Event.select(Event.id, Event.SeriesID).where(
        Event.LeaderSlackID == slack_id,
        Event.Approved == False,
        Event.Cancelled == False,
    )

    waiting = set()
    for row in rows:
        series = row.get("SeriesID")
        waiting.add(f"series:{series}" if series else str(row.get("id")))

    return len(waiting)


async def list_submitters(req: Request):
    if not _check_secret(req):
        return _unauthorized()

    actor = (req.query_params.get("actor_slack_id") or "").strip()
    if not actor:
        return JSONResponse({"error": "actor_slack_id is required"}, status_code=422)
    if not is_reviewer(actor):
        return _forbidden()

    rows = await Submitter.select().order_by(Submitter.AddedAt, ascending=False)
    return JSONResponse(
        {
            "submitters": [
                {
                    "slackId": r.get("SlackID"),
                    "name": r.get("Name"),
                    "note": r.get("Note"),
                    "addedBySlackId": r.get("AddedBySlackID"),
                    "addedAt": _utc_iso(r.get("AddedAt")),
                }
                for r in rows
            ]
        }
    )


async def add_submitter(req: Request):
    if not _check_secret(req):
        return _unauthorized()

    body = await _body(req)
    if body is None:
        return JSONResponse({"error": "invalid json"}, status_code=400)

    actor = (body.get("actor_slack_id") or "").strip()
    if not actor:
        return JSONResponse({"error": "actor_slack_id is required"}, status_code=422)
    if not is_reviewer(actor):
        return _forbidden()

    slack_id = (body.get("slack_id") or "").strip().upper()
    if not slack_id:
        return JSONResponse(
            {"error": "invalid submission", "errors": {"slack_id": "required"}},
            status_code=422,
        )

    existing = await Submitter.select().where(Submitter.SlackID == slack_id).first()
    if existing:
        return JSONResponse({"error": "already on the list"}, status_code=409)

    await Submitter.insert(
        Submitter(
            SlackID=slack_id,
            Name=(body.get("name") or "").strip() or None,
            Note=(body.get("note") or "").strip() or None,
            AddedBySlackID=actor,
            AddedAt=_now(),
        )
    )

    return JSONResponse({"slackId": slack_id}, status_code=201)


async def remove_submitter(req: Request):
    if not _check_secret(req):
        return _unauthorized()

    actor = (req.query_params.get("actor_slack_id") or "").strip()
    if not actor:
        return JSONResponse({"error": "actor_slack_id is required"}, status_code=422)
    if not is_reviewer(actor):
        return _forbidden()

    slack_id = req.path_params["slack_id"]
    await Submitter.delete().where(Submitter.SlackID == slack_id)
    return JSONResponse({"slackId": slack_id})


async def list_tags(req: Request):
    if not _check_secret(req):
        return _unauthorized()

    rows = await Event.select(Event.Tags, Event.Approved).where(
        Event.Cancelled == False
    )

    counts: dict[str, int] = {}
    approved_counts: dict[str, int] = {}
    for row in rows:
        for tag in row.get("Tags") or []:
            if not tag:
                continue
            counts[tag] = counts.get(tag, 0) + 1
            if row.get("Approved"):
                approved_counts[tag] = approved_counts.get(tag, 0) + 1

    curated = set(env.event_tags)
    for tag in curated:
        counts.setdefault(tag, 0)

    tags = [
        {
            "name": name,
            "count": count,
            "approvedCount": approved_counts.get(name, 0),
            "curated": name in curated,
        }
        for name, count in counts.items()
    ]
    tags.sort(key=lambda t: (not t["curated"], -t["count"], t["name"]))

    return JSONResponse({"tags": tags})


MAX_NAME_LOOKUPS = 200
MAX_CHANNEL_RESULTS = 25


async def list_channels(req: Request):
    if not _check_secret(req):
        return _unauthorized()

    query = req.query_params.get("q") or ""

    try:
        limit = int(req.query_params.get("limit") or MAX_CHANNEL_RESULTS)
    except ValueError:
        limit = MAX_CHANNEL_RESULTS

    limit = max(1, min(limit, MAX_CHANNEL_RESULTS))

    return JSONResponse({"channels": await search_channels(query, limit)})


async def list_slack_names(req: Request):
    if not _check_secret(req):
        return _unauthorized()

    raw = req.query_params.get("ids") or ""
    ids = [part.strip() for part in raw.split(",") if part.strip()]

    return JSONResponse({"names": await slack_names(ids[:MAX_NAME_LOOKUPS])})


async def permissions(req: Request):
    if not _check_secret(req):
        return _unauthorized()

    actor = (req.query_params.get("actor_slack_id") or "").strip()
    if not actor:
        return JSONResponse({"error": "actor_slack_id is required"}, status_code=422)

    return JSONResponse(
        {
            "reviewer": is_reviewer(actor),
            "submitter": await may_submit(req.query_params.get("email"), actor),
        }
    )


async def list_audit(req: Request):
    if not _check_secret(req):
        return _unauthorized()

    actor = (req.query_params.get("actor_slack_id") or "").strip()
    if not actor:
        return JSONResponse({"error": "actor_slack_id is required"}, status_code=422)

    if not is_reviewer(actor):
        return _forbidden()

    try:
        limit = int(req.query_params.get("limit") or 50)
    except ValueError:
        limit = 50
    limit = max(1, min(limit, audit.MAX_PAGE_SIZE))

    try:
        offset = int(req.query_params.get("offset") or 0)
    except ValueError:
        offset = 0
    offset = max(0, offset)

    rows = (
        await AuditEntry.select()
        .order_by(AuditEntry.At, ascending=False)
        .limit(limit)
        .offset(offset)
    )

    total = await AuditEntry.count()

    return JSONResponse(
        {
            "entries": [audit.serialise(row) for row in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    )


routes = [
    Route("/internal/permissions", endpoint=permissions, methods=["GET"]),
    Route("/internal/audit", endpoint=list_audit, methods=["GET"]),
    Route("/internal/tags", endpoint=list_tags, methods=["GET"]),
    Route("/internal/slack-names", endpoint=list_slack_names, methods=["GET"]),
    Route("/internal/channels", endpoint=list_channels, methods=["GET"]),
    Route("/internal/submitters", endpoint=list_submitters, methods=["GET"]),
    Route("/internal/submitters", endpoint=add_submitter, methods=["POST"]),
    Route(
        "/internal/submitters/{slack_id}",
        endpoint=remove_submitter,
        methods=["DELETE"],
    ),
    Route("/internal/events/manage", endpoint=list_events, methods=["GET"]),
    Route(
        "/internal/events/{event_id}/approve", endpoint=approve_event, methods=["POST"]
    ),
    Route(
        "/internal/events/{event_id}/cancel", endpoint=cancel_event, methods=["POST"]
    ),
    Route(
        "/internal/events/{event_id}/manage",
        endpoint=get_manageable_event,
        methods=["GET"],
    ),
    Route("/internal/events/{event_id}", endpoint=edit_event, methods=["PATCH"]),
]
