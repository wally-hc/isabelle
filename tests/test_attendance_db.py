import json
import os
from datetime import datetime
from datetime import timedelta

import pytest
import pytest_asyncio
from starlette.testclient import TestClient

from app import api
from isabelle.attendance import public_count
from isabelle.tables import Event
from isabelle.tables import Series
from isabelle.utils import rsvp_checker

pytestmark = pytest.mark.db

SECRET = os.environ["EVENTS_RSVP_SECRET"]
LEADER = "U0ATTENDLEAD"
GOER = "U0REGULAR"
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
                "title": "Attendance Circle",
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


async def rows():
    found = await Event.select().where(Event.LeaderSlackID == LEADER)
    return sorted(found, key=lambda r: r["StartTime"])


def rsvp(client, event_id, *, scope=None, attending=True, who=GOER):
    body = {
        "slack_id": who,
        "attending": attending,
        "user_info": {"sub": f"sub-{who}"},
    }
    if scope:
        body["scope"] = scope

    return client.put(
        f"/internal/events/{event_id}/rsvp", content=json.dumps(body), headers=AUTH
    )


class TestFollowingASeries:
    async def test_following_does_not_write_to_every_row(
        self, client, clean_events, clean_series
    ):
        create(client)
        first = (await rows())[0]

        response = rsvp(client, first["id"], scope="all")
        assert response.status_code == 200
        assert response.json()["following"] is True

        after = await rows()
        with_rsvps = [r for r in after if public_count(r) > 0]
        assert len(with_rsvps) == 1

    async def test_the_follower_is_stored_once_on_the_series(
        self, client, clean_events, clean_series
    ):
        create(client)
        first = (await rows())[0]
        rsvp(client, first["id"], scope="all")

        series = await Series.select().first()
        assert series["Followers"] == [GOER]

    async def test_following_twice_stops_following(
        self, client, clean_events, clean_series
    ):
        create(client)
        first = (await rows())[0]

        rsvp(client, first["id"], scope="all")
        second = rsvp(client, first["id"], scope="all", attending=False)

        assert second.json()["following"] is False
        series = await Series.select().first()
        assert series["Followers"] == []

    async def test_rsvping_to_one_date_never_touches_the_series(
        self, client, clean_events, clean_series
    ):
        create(client)
        first = (await rows())[0]

        rsvp(client, first["id"])

        series = await Series.select().first()
        assert series["Followers"] == []


class TestRemindersAreNotSentTwice:
    async def test_a_follower_is_reminded_once_per_date_not_once_per_row(
        self, client, clean_events, clean_series
    ):
        create(client)
        all_rows = await rows()
        rsvp(client, all_rows[0]["id"], scope="all")

        for row in await rows():
            recipients = await rsvp_checker._slack_ids_for_event(row)
            assert recipients.count(GOER) == 1

    async def test_someone_on_both_lists_is_still_reminded_once(
        self, client, clean_events, clean_series
    ):
        create(client)
        first = (await rows())[0]

        rsvp(client, first["id"], scope="all")
        rsvp(client, first["id"])

        recipients = await rsvp_checker._slack_ids_for_event((await rows())[0])
        assert recipients.count(GOER) == 1

    async def test_a_follower_is_reminded_about_a_date_they_never_rsvped_to(
        self, client, clean_events, clean_series
    ):
        create(client)
        all_rows = await rows()
        rsvp(client, all_rows[0]["id"], scope="all")

        last = (await rows())[-1]
        assert public_count(last) == 0
        assert GOER in await rsvp_checker._slack_ids_for_event(last)

    async def test_a_one_off_still_reminds_the_people_who_rsvped(
        self, client, clean_events, clean_series
    ):
        client.post(
            "/internal/events",
            content=json.dumps(
                {
                    "title": "Attendance Circle",
                    "description": "Just the once.",
                    "start_time": START.isoformat(),
                    "end_time": (START + timedelta(hours=1)).isoformat(),
                    "leader_slack_id": LEADER,
                    "submitted_by": {"email": "organiser@hackclub.com"},
                }
            ),
            headers=AUTH,
        )
        only = (await rows())[0]
        rsvp(client, only["id"])

        assert await rsvp_checker._slack_ids_for_event((await rows())[0]) == [GOER]


class TestThePublicNumber:
    async def test_followers_never_reach_the_public_count(
        self, client, clean_events, clean_series
    ):
        create(client)
        first = (await rows())[0]
        rsvp(client, first["id"], scope="all", who="U0FOLLOWER")

        for row in await rows():
            assert row["InterestCount"] in (0, 1)

        last = (await rows())[-1]
        assert public_count(last) == 0
