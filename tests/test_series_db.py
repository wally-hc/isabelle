import json
import os
from datetime import datetime
from datetime import timedelta

import pytest
from starlette.testclient import TestClient

from app import api
from isabelle.internal_events import pending_submission_count
from isabelle.tables import Event
from isabelle.utils.env import env

pytestmark = pytest.mark.db

SECRET = os.environ["EVENTS_RSVP_SECRET"]
REVIEWER = env.authorised_users[0]
LEADER = "U0SERIESLEAD"


@pytest.fixture
def client():
    return TestClient(api)


def payload(**overrides):
    start = datetime.now() + timedelta(days=7)
    body = {
        "title": "Website Circle",
        "description": "Weekly build session.",
        "start_time": start.isoformat(),
        "end_time": (start + timedelta(hours=1)).isoformat(),
        "leader_slack_id": LEADER,
        "submitted_by": {"email": "organiser@hackclub.com"},
        "recurrence": {"frequency": "weekly", "count": 4},
    }
    body.update(overrides)
    return body


async def create(client, **overrides):
    return client.post(
        "/internal/events",
        content=json.dumps(payload(**overrides)),
        headers={"x-internal-secret": SECRET, "content-type": "application/json"},
    )


class TestCreatingASeries:
    async def test_every_date_becomes_its_own_event(self, client, clean_events):
        response = await create(client)
        assert response.status_code == 201

        rows = await Event.select().where(Event.LeaderSlackID == LEADER)
        assert len(rows) == 4

    async def test_the_dates_share_one_series_id(self, client, clean_events):
        await create(client)

        rows = await Event.select(Event.SeriesID).where(
            Event.LeaderSlackID == LEADER
        )
        series_ids = {row["SeriesID"] for row in rows}
        assert len(series_ids) == 1
        assert series_ids.pop()

    async def test_the_dates_are_a_week_apart(self, client, clean_events):
        await create(client)

        rows = await Event.select(Event.StartTime).where(
            Event.LeaderSlackID == LEADER
        )
        starts = sorted(row["StartTime"] for row in rows)
        gaps = {(b - a).days for a, b in zip(starts, starts[1:])}
        assert gaps == {7}

    async def test_a_one_off_has_no_series_id(self, client, clean_events):
        await create(client, recurrence=None)

        rows = await Event.select(Event.SeriesID).where(
            Event.LeaderSlackID == LEADER
        )
        assert len(rows) == 1
        assert not rows[0]["SeriesID"]

    async def test_a_bad_rule_creates_nothing(self, client, clean_events):
        response = await create(client, recurrence={"frequency": "hourly", "count": 3})
        assert response.status_code == 422

        rows = await Event.select().where(Event.LeaderSlackID == LEADER)
        assert rows == []

    async def test_a_daily_series_is_allowed(self, client, clean_events):
        response = await create(client, recurrence={"frequency": "daily", "count": 3})
        assert response.status_code == 201

        rows = await Event.select(Event.StartTime).where(
            Event.LeaderSlackID == LEADER
        )
        starts = sorted(row["StartTime"] for row in rows)
        assert len(starts) == 3
        assert {(b - a).days for a, b in zip(starts, starts[1:])} == {1}

    async def test_a_series_counts_as_one_pending_submission(
        self, client, clean_events
    ):
        await create(client)
        assert await pending_submission_count(LEADER) == 1


class TestActingOnASeries:
    async def _series(self, client):
        await create(client)
        rows = await Event.select(Event.id, Event.StartTime).where(
            Event.LeaderSlackID == LEADER
        )
        return sorted(rows, key=lambda r: r["StartTime"])

    async def test_approving_one_date_leaves_the_rest_alone(
        self, client, clean_events
    ):
        rows = await self._series(client)

        response = client.post(
            f"/internal/events/{rows[0]['id']}/approve",
            content=json.dumps({"actor_slack_id": REVIEWER}),
            headers={"x-internal-secret": SECRET, "content-type": "application/json"},
        )
        assert response.status_code == 200

        approved = await Event.select(Event.Approved).where(
            Event.LeaderSlackID == LEADER
        )
        assert sum(1 for row in approved if row["Approved"]) == 1

    async def test_approving_the_series_approves_every_date(
        self, client, clean_events
    ):
        rows = await self._series(client)

        response = client.post(
            f"/internal/events/{rows[0]['id']}/approve",
            content=json.dumps({"actor_slack_id": REVIEWER, "scope": "series"}),
            headers={"x-internal-secret": SECRET, "content-type": "application/json"},
        )
        assert response.status_code == 200
        assert response.json()["seriesApproved"] == 4

        approved = await Event.select(Event.Approved).where(
            Event.LeaderSlackID == LEADER
        )
        assert all(row["Approved"] for row in approved)

    async def test_rejecting_the_series_rejects_every_date(
        self, client, clean_events
    ):
        rows = await self._series(client)

        response = client.post(
            f"/internal/events/{rows[0]['id']}/cancel",
            content=json.dumps(
                {
                    "actor_slack_id": REVIEWER,
                    "scope": "series",
                    "reason": "Clashes with the weekly standup.",
                    "kind": "rejected",
                }
            ),
            headers={"x-internal-secret": SECRET, "content-type": "application/json"},
        )
        assert response.status_code == 200

        rows = await Event.select(Event.Cancelled, Event.CancellationType).where(
            Event.LeaderSlackID == LEADER
        )
        assert all(row["Cancelled"] for row in rows)
        assert {row["CancellationType"] for row in rows} == {"rejected"}

    async def test_a_reviewer_is_still_required(self, client, clean_events):
        rows = await self._series(client)

        response = client.post(
            f"/internal/events/{rows[0]['id']}/approve",
            content=json.dumps({"actor_slack_id": "U0STRANGER", "scope": "series"}),
            headers={"x-internal-secret": SECRET, "content-type": "application/json"},
        )
        assert response.status_code == 403

        approved = await Event.select(Event.Approved).where(
            Event.LeaderSlackID == LEADER
        )
        assert not any(row["Approved"] for row in approved)


class TestPhaseZero:
    async def test_every_date_of_a_series_has_its_own_slug(
        self, client, clean_events
    ):
        await create(client)

        rows = await Event.select(Event.Calculation).where(
            Event.LeaderSlackID == LEADER
        )
        slugs = [row["Calculation"] for row in rows]
        assert len(set(slugs)) == len(slugs) == 4

    async def test_a_one_off_keeps_its_plain_slug(self, client, clean_events):
        await create(client, recurrence=None, title="Code in the Dark")

        rows = await Event.select(Event.Calculation).where(
            Event.LeaderSlackID == LEADER
        )
        assert rows[0]["Calculation"] == "code-in-the-dark"

    async def test_a_failed_date_rolls_the_whole_series_back(
        self, client, clean_events, monkeypatch
    ):
        real = env.database.create_event
        calls = {"n": 0}

        async def fail_on_third(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 3:
                return None
            return await real(*args, **kwargs)

        monkeypatch.setattr(env.database, "create_event", fail_on_third)

        response = await create(client)
        assert response.status_code == 500
        assert "nothing was saved" in response.json()["error"]

        rows = await Event.select().where(Event.LeaderSlackID == LEADER)
        assert rows == []
