import json
import os
from datetime import datetime
from datetime import timedelta

import pytest
import pytest_asyncio
from starlette.testclient import TestClient

from app import api
from isabelle.tables import AuditEntry
from isabelle.tables import Event
from isabelle.tables import Series
from isabelle.utils.env import env

pytestmark = pytest.mark.db

SECRET = os.environ["EVENTS_RSVP_SECRET"]
REVIEWER = env.authorised_users[0]
STRANGER = "U0STRANGER"
LEADER = "U0AUDITLEAD"
AUTH = {"x-internal-secret": SECRET, "content-type": "application/json"}

START = (datetime.now() + timedelta(days=7)).replace(
    hour=18, minute=0, second=0, microsecond=0
)


@pytest.fixture
def client():
    return TestClient(api)


@pytest_asyncio.fixture
async def clean_audit():
    await AuditEntry.delete(force=True)
    await Series.delete(force=True)
    yield
    await AuditEntry.delete(force=True)
    await Series.delete(force=True)


def create(client, count=3):
    return client.post(
        "/internal/events",
        content=json.dumps(
            {
                "title": "Audit Circle",
                "description": "Weekly build session.",
                "start_time": START.isoformat(),
                "end_time": (START + timedelta(hours=1)).isoformat(),
                "leader_slack_id": LEADER,
                "submitted_by": {"email": "organiser@hackclub.com"},
                "recurrence": {
                    "frequency": "weekly",
                    "ends": {"type": "count", "count": count},
                    "timezone": "UTC",
                },
            }
        ),
        headers=AUTH,
    )


async def first_event():
    rows = await Event.select(Event.id, Event.StartTime).where(
        Event.LeaderSlackID == LEADER
    )
    return sorted(rows, key=lambda r: r["StartTime"])[0]


def log(client, actor=REVIEWER, **params):
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return client.get(
        f"/internal/audit?actor_slack_id={actor}" + (f"&{query}" if query else ""),
        headers=AUTH,
    )


class TestWhatGetsRecorded:
    async def test_approving_is_written_down(
        self, client, clean_events, clean_audit
    ):
        create(client)
        event = await first_event()

        client.post(
            f"/internal/events/{event['id']}/approve",
            content=json.dumps({"actor_slack_id": REVIEWER}),
            headers=AUTH,
        )

        entries = log(client).json()["entries"]
        assert len(entries) == 1
        assert entries[0]["action"] == "approved"
        assert entries[0]["actorSlackId"] == REVIEWER
        assert entries[0]["eventTitle"] == "Audit Circle"

    async def test_it_records_how_many_dates_were_affected(
        self, client, clean_events, clean_audit
    ):
        create(client)
        event = await first_event()

        client.post(
            f"/internal/events/{event['id']}/approve",
            content=json.dumps({"actor_slack_id": REVIEWER, "scope": "all"}),
            headers=AUTH,
        )

        entry = log(client).json()["entries"][0]
        assert entry["affected"] == 3
        assert entry["scope"] == "all"

    async def test_a_cancellation_keeps_its_reason(
        self, client, clean_events, clean_audit
    ):
        create(client)
        event = await first_event()

        client.post(
            f"/internal/events/{event['id']}/cancel",
            content=json.dumps(
                {
                    "actor_slack_id": REVIEWER,
                    "reason": "Clashes with the weekly standup.",
                    "kind": "rejected",
                }
            ),
            headers=AUTH,
        )

        entry = log(client).json()["entries"][0]
        assert entry["action"] == "rejected"
        assert entry["reason"] == "Clashes with the weekly standup."

    async def test_an_edit_is_written_down(self, client, clean_events, clean_audit):
        create(client)
        event = await first_event()

        client.patch(
            f"/internal/events/{event['id']}",
            content=json.dumps(
                {
                    "actor_slack_id": REVIEWER,
                    "title": "Renamed Circle",
                    "description": "Weekly build session.",
                    "start_time": START.isoformat(),
                    "end_time": (START + timedelta(hours=1)).isoformat(),
                    "leader_slack_id": LEADER,
                }
            ),
            headers=AUTH,
        )

        entry = log(client).json()["entries"][0]
        assert entry["action"] == "edited"
        assert entry["eventTitle"] == "Renamed Circle"

    async def test_every_action_lands_in_order_newest_first(
        self, client, clean_events, clean_audit
    ):
        create(client)
        event = await first_event()

        client.post(
            f"/internal/events/{event['id']}/approve",
            content=json.dumps({"actor_slack_id": REVIEWER}),
            headers=AUTH,
        )
        client.post(
            f"/internal/events/{event['id']}/cancel",
            content=json.dumps(
                {"actor_slack_id": REVIEWER, "reason": "Called off after all."}
            ),
            headers=AUTH,
        )

        actions = [e["action"] for e in log(client).json()["entries"]]
        assert actions == ["cancelled", "approved"]


class TestWhoCanRead:
    async def test_a_reviewer_can(self, client, clean_events, clean_audit):
        assert log(client).status_code == 200

    async def test_anyone_else_cannot(self, client, clean_events, clean_audit):
        assert log(client, actor=STRANGER).status_code == 403

    async def test_it_still_needs_the_shared_secret(
        self, client, clean_events, clean_audit
    ):
        response = client.get(f"/internal/audit?actor_slack_id={REVIEWER}")
        assert response.status_code == 401

    async def test_it_needs_to_know_who_is_asking(
        self, client, clean_events, clean_audit
    ):
        assert client.get("/internal/audit", headers=AUTH).status_code == 422


class TestPaging:
    async def test_it_pages(self, client, clean_events, clean_audit):
        create(client)
        event = await first_event()

        for _ in range(3):
            client.patch(
                f"/internal/events/{event['id']}",
                content=json.dumps(
                    {
                        "actor_slack_id": REVIEWER,
                        "title": "Audit Circle",
                        "description": "Weekly build session.",
                        "start_time": START.isoformat(),
                        "end_time": (START + timedelta(hours=1)).isoformat(),
                        "leader_slack_id": LEADER,
                    }
                ),
                headers=AUTH,
            )

        page = log(client, limit=2).json()
        assert len(page["entries"]) == 2
        assert page["total"] == 3

        second = log(client, limit=2, offset=2).json()
        assert len(second["entries"]) == 1

    async def test_it_refuses_to_hand_over_everything_at_once(
        self, client, clean_events, clean_audit
    ):
        assert log(client, limit=5000).json()["limit"] == 100


class TestTheLogIsPartOfTheAction:
    """If the log cannot be written, the action itself must not stand."""

    def _break_the_log(self, monkeypatch):
        def refuse(*args, **kwargs):
            raise RuntimeError("audit table unavailable")

        monkeypatch.setattr("isabelle.audit.AuditEntry.insert", refuse)

    async def test_nothing_is_approved_when_the_log_cannot_be_written(
        self, client, clean_events, clean_audit, monkeypatch
    ):
        create(client)
        event = await first_event()
        self._break_the_log(monkeypatch)

        try:
            client.post(
                f"/internal/events/{event['id']}/approve",
                content=json.dumps({"actor_slack_id": REVIEWER, "scope": "all"}),
                headers=AUTH,
            )
        except RuntimeError:
            pass

        approved = await Event.select(Event.Approved).where(
            Event.LeaderSlackID == LEADER
        )
        assert not any(row["Approved"] for row in approved)

    async def test_nothing_is_cancelled_when_the_log_cannot_be_written(
        self, client, clean_events, clean_audit, monkeypatch
    ):
        create(client)
        event = await first_event()
        self._break_the_log(monkeypatch)

        try:
            client.post(
                f"/internal/events/{event['id']}/cancel",
                content=json.dumps(
                    {"actor_slack_id": REVIEWER, "reason": "Never mind.", "scope": "all"}
                ),
                headers=AUTH,
            )
        except RuntimeError:
            pass

        rows = await Event.select(Event.Cancelled).where(
            Event.LeaderSlackID == LEADER
        )
        assert not any(row["Cancelled"] for row in rows)

    async def test_no_edit_survives_a_broken_log(
        self, client, clean_events, clean_audit, monkeypatch
    ):
        create(client)
        event = await first_event()
        self._break_the_log(monkeypatch)

        try:
            client.patch(
                f"/internal/events/{event['id']}",
                content=json.dumps(
                    {
                        "actor_slack_id": REVIEWER,
                        "title": "Should Not Stick",
                        "description": "Weekly build session.",
                        "start_time": START.isoformat(),
                        "end_time": (START + timedelta(hours=1)).isoformat(),
                        "leader_slack_id": LEADER,
                    }
                ),
                headers=AUTH,
            )
        except RuntimeError:
            pass

        titles = await Event.select(Event.Title).where(
            Event.LeaderSlackID == LEADER
        )
        assert all(row["Title"] == "Audit Circle" for row in titles)

    async def test_a_successful_action_writes_exactly_one_entry(
        self, client, clean_events, clean_audit
    ):
        create(client)
        event = await first_event()

        client.post(
            f"/internal/events/{event['id']}/approve",
            content=json.dumps({"actor_slack_id": REVIEWER, "scope": "all"}),
            headers=AUTH,
        )

        assert await AuditEntry.count() == 1
