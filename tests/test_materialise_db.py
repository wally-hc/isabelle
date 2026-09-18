import json
import os
from datetime import datetime
from datetime import timedelta

import pytest
import pytest_asyncio
from starlette.testclient import TestClient

from app import api
from isabelle.internal_events import materialise
from isabelle.tables import Event
from isabelle.tables import Series

pytestmark = pytest.mark.db

SECRET = os.environ["EVENTS_RSVP_SECRET"]
LEADER = "U0LAZYLEAD"
AUTH = {"x-internal-secret": SECRET, "content-type": "application/json"}

START = (datetime.now() + timedelta(days=7)).replace(
    hour=18, minute=0, second=0, microsecond=0
)


@pytest.fixture
def client():
    return TestClient(api)


@pytest_asyncio.fixture
async def clean_series():
    await Series.delete(force=True)
    yield
    await Series.delete(force=True)


def create(client, count=4):
    return client.post(
        "/internal/events",
        content=json.dumps(
            {
                "title": "Lazy Circle",
                "description": "Weekly build session.",
                "start_time": START.isoformat(),
                "end_time": (START + timedelta(hours=1)).isoformat(),
                "leader_slack_id": LEADER,
                "submitted_by": {"email": "organiser@hackclub.com"},
                "event_link": "https://hackclub.slack.com/app_redirect?channel=hq",
                "tags": ["workshop"],
                "recurrence": {
                    "frequency": "weekly",
                    "ends": {"type": "count", "count": count},
                    "timezone": "UTC",
                },
            }
        ),
        headers=AUTH,
    )


async def series_id():
    series = await Series.select().first()
    return series["SeriesID"]


async def drop_all_but_the_first():
    rows = await Event.select(Event.id, Event.OccurrenceStart).where(
        Event.LeaderSlackID == LEADER
    )
    ordered = sorted(rows, key=lambda r: r["OccurrenceStart"])
    for row in ordered[1:]:
        await Event.delete().where(Event.id == row["id"])
    return ordered


class TestMaterialise:
    async def test_it_creates_the_missing_row(self, client, clean_events, clean_series):
        create(client)
        ordered = await drop_all_but_the_first()
        assert await Event.count().where(Event.LeaderSlackID == LEADER) == 1

        made = await materialise(await series_id(), ordered[2]["OccurrenceStart"])

        assert made is not None
        assert await Event.count().where(Event.LeaderSlackID == LEADER) == 2

    async def test_the_new_row_lands_on_the_right_date(
        self, client, clean_events, clean_series
    ):
        create(client)
        ordered = await drop_all_but_the_first()
        slot = ordered[2]["OccurrenceStart"]

        made = await materialise(await series_id(), slot)

        assert made["StartTime"] == slot
        assert made["OccurrenceStart"] == slot
        assert made["EndTime"] - made["StartTime"] == timedelta(hours=1)

    async def test_it_inherits_the_series_details(
        self, client, clean_events, clean_series
    ):
        create(client)
        ordered = await drop_all_but_the_first()

        made = await materialise(await series_id(), ordered[2]["OccurrenceStart"])

        assert made["Title"] == "Lazy Circle"
        assert made["LeaderSlackID"] == LEADER
        assert made["Tags"] == ["workshop"]
        assert "app_redirect" in made["EventLink"]

    async def test_it_gets_its_own_slug(self, client, clean_events, clean_series):
        create(client)
        ordered = await drop_all_but_the_first()

        made = await materialise(await series_id(), ordered[2]["OccurrenceStart"])
        first = await Event.select(Event.Calculation).where(
            Event.id == ordered[0]["id"]
        ).first()

        assert made["Calculation"]
        assert made["Calculation"] != first["Calculation"]

    async def test_it_starts_with_nobody_going(
        self, client, clean_events, clean_series
    ):
        create(client)
        ordered = await drop_all_but_the_first()

        made = await materialise(await series_id(), ordered[2]["OccurrenceStart"])

        assert made["InterestCount"] == 0
        assert not made["Cancelled"]

    async def test_asking_twice_does_not_make_two_rows(
        self, client, clean_events, clean_series
    ):
        create(client)
        ordered = await drop_all_but_the_first()
        slot = ordered[2]["OccurrenceStart"]

        first = await materialise(await series_id(), slot)
        again = await materialise(await series_id(), slot)

        assert str(first["id"]) == str(again["id"])
        assert await Event.count().where(Event.LeaderSlackID == LEADER) == 2

    async def test_it_refuses_a_date_the_rule_never_produces(
        self, client, clean_events, clean_series
    ):
        create(client)
        await drop_all_but_the_first()

        assert await materialise(await series_id(), START + timedelta(days=3)) is None
        assert await Event.count().where(Event.LeaderSlackID == LEADER) == 1

    async def test_it_refuses_a_series_that_does_not_exist(
        self, client, clean_events, clean_series
    ):
        assert await materialise("no-such-series", START) is None

    async def test_it_refuses_nonsense(self, client, clean_events, clean_series):
        assert await materialise("", START) is None
        assert await materialise("S1", None) is None
