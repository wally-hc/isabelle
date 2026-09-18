import json
import os
from datetime import datetime
from datetime import timedelta

import pytest
import pytest_asyncio
from starlette.testclient import TestClient

from app import api
from isabelle.tables import Event
from isabelle.tables import Series

pytestmark = pytest.mark.db

SECRET = os.environ["EVENTS_RSVP_SECRET"]
LEADER = "U0FEEDLEAD"


@pytest.fixture
def client():
    return TestClient(api)


@pytest_asyncio.fixture
async def clean_series():
    await Series.delete(force=True)
    yield
    await Series.delete(force=True)


def payload(count=3):
    start = datetime.now() + timedelta(days=7)
    return {
        "title": "Feed Circle",
        "description": "Weekly build session.",
        "start_time": start.isoformat(),
        "end_time": (start + timedelta(hours=1)).isoformat(),
        "leader_slack_id": LEADER,
        "submitted_by": {"email": "organiser@hackclub.com"},
        "recurrence": {"frequency": "weekly", "count": count, "timezone": "UTC"},
    }


def create(client, count=3):
    return client.post(
        "/internal/events",
        content=json.dumps(payload(count)),
        headers={"x-internal-secret": SECRET, "content-type": "application/json"},
    )


def feed(client):
    return client.get("/events/?__page_size=1000").json()["rows"]


class TestTheFeedExpandsRules:
    async def test_a_series_appears_in_the_feed(
        self, client, clean_events, clean_series
    ):
        create(client)

        rows = [r for r in feed(client) if r["Title"] == "Feed Circle"]
        assert len(rows) == 3

    async def test_an_occurrence_with_no_row_is_still_listed(
        self, client, clean_events, clean_series
    ):
        create(client)

        stored = await Event.select(Event.id, Event.StartTime).where(
            Event.LeaderSlackID == LEADER
        )
        middle = sorted(stored, key=lambda r: r["StartTime"])[1]
        await Event.delete().where(Event.id == middle["id"])

        assert (
            await Event.count().where(Event.LeaderSlackID == LEADER)
        ) == 2

        rows = [r for r in feed(client) if r.get("SeriesID")]
        assert len(rows) == 3

    async def test_the_filled_in_occurrence_lands_on_the_right_date(
        self, client, clean_events, clean_series
    ):
        create(client)

        stored = await Event.select(Event.id, Event.StartTime).where(
            Event.LeaderSlackID == LEADER
        )
        ordered = sorted(stored, key=lambda r: r["StartTime"])
        missing = ordered[1]["StartTime"]
        await Event.delete().where(Event.id == ordered[1]["id"])

        rows = [r for r in feed(client) if r.get("SeriesID")]
        starts = sorted(r["StartTime"] for r in rows)
        assert missing.isoformat() in starts

    async def test_a_cancelled_occurrence_stays_out_of_the_public_shape(
        self, client, clean_events, clean_series
    ):
        create(client)

        stored = await Event.select(Event.id, Event.StartTime).where(
            Event.LeaderSlackID == LEADER
        )
        ordered = sorted(stored, key=lambda r: r["StartTime"])
        await Event.update({Event.Cancelled: True}).where(
            Event.id == ordered[0]["id"]
        )

        rows = [r for r in feed(client) if r.get("SeriesID")]
        cancelled = [r for r in rows if r["Cancelled"]]
        assert len(cancelled) == 1

    async def test_the_feed_never_ships_the_secret_columns(
        self, client, clean_events, clean_series
    ):
        create(client)

        for row in feed(client):
            assert "RSVPData" not in row
            assert "InterestedUsers" not in row

    async def test_a_one_off_is_untouched_by_any_of_this(
        self, client, clean_events, clean_series
    ):
        client.post(
            "/internal/events",
            content=json.dumps({**payload(), "recurrence": None}),
            headers={
                "x-internal-secret": SECRET,
                "content-type": "application/json",
            },
        )

        rows = [r for r in feed(client) if r["Title"] == "Feed Circle"]
        assert len(rows) == 1
        assert not rows[0].get("SeriesID")
