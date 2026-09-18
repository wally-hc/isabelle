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
from isabelle.utils.env import env

pytestmark = pytest.mark.db

SECRET = os.environ["EVENTS_RSVP_SECRET"]
REVIEWER = env.authorised_users[0]
LEADER = "U0SCOPELEAD"
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
                "title": "Scope Circle",
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


async def dates():
    rows = await Event.select(
        Event.id,
        Event.StartTime,
        Event.OccurrenceStart,
        Event.Title,
        Event.OverriddenFields,
    ).where(Event.LeaderSlackID == LEADER)
    return sorted(rows, key=lambda r: r["OccurrenceStart"] or r["StartTime"])


def patch(client, event_id, **body):
    payload = {
        "actor_slack_id": REVIEWER,
        "title": "Scope Circle",
        "description": "Weekly build session.",
        "start_time": START.isoformat(),
        "end_time": (START + timedelta(hours=1)).isoformat(),
        "leader_slack_id": LEADER,
    }
    payload.update(body)
    return client.patch(
        f"/internal/events/{event_id}", content=json.dumps(payload), headers=AUTH
    )


class TestMovingOneOccurrence:
    async def test_moving_one_leaves_the_rest_where_they_were(
        self, client, clean_events, clean_series
    ):
        create(client)
        rows = await dates()
        second = rows[1]
        moved_to = second["StartTime"] + timedelta(days=1)

        response = patch(
            client,
            second["id"],
            start_time=moved_to.isoformat(),
            end_time=(moved_to + timedelta(hours=1)).isoformat(),
        )
        assert response.status_code == 200

        after = await dates()
        assert after[1]["StartTime"] == moved_to
        assert after[0]["StartTime"] == rows[0]["StartTime"]
        assert after[2]["StartTime"] == rows[2]["StartTime"]
        assert after[3]["StartTime"] == rows[3]["StartTime"]

    async def test_the_moved_date_remembers_where_it_should_have_been(
        self, client, clean_events, clean_series
    ):
        create(client)
        rows = await dates()
        second = rows[1]
        intended = second["OccurrenceStart"]
        moved_to = second["StartTime"] + timedelta(days=1)

        patch(
            client,
            second["id"],
            start_time=moved_to.isoformat(),
            end_time=(moved_to + timedelta(hours=1)).isoformat(),
        )

        after = await dates()
        assert after[1]["OccurrenceStart"] == intended
        assert "StartTime" in after[1]["OverriddenFields"]

    async def test_a_later_series_edit_does_not_drag_it_back(
        self, client, clean_events, clean_series
    ):
        create(client)
        rows = await dates()
        second = rows[1]
        moved_to = second["StartTime"] + timedelta(days=1)

        patch(
            client,
            second["id"],
            start_time=moved_to.isoformat(),
            end_time=(moved_to + timedelta(hours=1)).isoformat(),
        )

        first = (await dates())[0]
        patch(client, first["id"], title="Renamed Circle", scope="all")

        after = await dates()
        assert after[1]["StartTime"] == moved_to
        assert [r["Title"] for r in after] == ["Renamed Circle"] * 4


class TestScopes:
    async def test_this_touches_only_the_one(
        self, client, clean_events, clean_series
    ):
        create(client)
        rows = await dates()

        patch(client, rows[1]["id"], title="Just This One")

        titles = [r["Title"] for r in await dates()]
        assert titles == [
            "Scope Circle",
            "Just This One",
            "Scope Circle",
            "Scope Circle",
        ]

    async def test_following_takes_this_one_and_the_later_ones(
        self, client, clean_events, clean_series
    ):
        create(client)
        rows = await dates()

        response = patch(
            client, rows[1]["id"], title="From Here On", scope="following"
        )
        assert response.json()["alsoChanged"] == 2

        titles = [r["Title"] for r in await dates()]
        assert titles == [
            "Scope Circle",
            "From Here On",
            "From Here On",
            "From Here On",
        ]

    async def test_all_takes_every_date(self, client, clean_events, clean_series):
        create(client)
        rows = await dates()

        response = patch(client, rows[2]["id"], title="Everywhere", scope="all")
        assert response.json()["alsoChanged"] == 3

        assert [r["Title"] for r in await dates()] == ["Everywhere"] * 4

    async def test_a_series_time_change_shifts_the_others_by_the_same_amount(
        self, client, clean_events, clean_series
    ):
        create(client)
        rows = await dates()
        gaps_before = [
            (rows[i + 1]["StartTime"] - rows[i]["StartTime"]).days for i in range(3)
        ]

        moved_to = rows[0]["StartTime"] + timedelta(hours=2)
        patch(
            client,
            rows[0]["id"],
            start_time=moved_to.isoformat(),
            end_time=(moved_to + timedelta(hours=1)).isoformat(),
            scope="all",
        )

        after = await dates()
        gaps_after = [
            (after[i + 1]["StartTime"] - after[i]["StartTime"]).days for i in range(3)
        ]
        assert gaps_before == gaps_after
        assert after[3]["StartTime"] == rows[3]["StartTime"] + timedelta(hours=2)

    async def test_a_one_off_ignores_the_scope_entirely(
        self, client, clean_events, clean_series
    ):
        client.post(
            "/internal/events",
            content=json.dumps(
                {
                    "title": "Lonely Event",
                    "description": "Just the once.",
                    "start_time": START.isoformat(),
                    "end_time": (START + timedelta(hours=1)).isoformat(),
                    "leader_slack_id": LEADER,
                    "submitted_by": {"email": "organiser@hackclub.com"},
                }
            ),
            headers=AUTH,
        )
        rows = await dates()

        response = patch(client, rows[0]["id"], title="Still Lonely", scope="all")
        assert response.status_code == 200
        assert response.json()["alsoChanged"] == 0


class TestSkippingOneDate:
    async def _series(self, client):
        create(client)
        rows = await dates()
        for row in rows:
            await Event.update({Event.Approved: True}).where(Event.id == row["id"])
        return await dates()

    def cancel(self, client, event_id, **body):
        payload = {"actor_slack_id": REVIEWER, "reason": "Clashes with something."}
        payload.update(body)
        return client.post(
            f"/internal/events/{event_id}/cancel",
            content=json.dumps(payload),
            headers=AUTH,
        )

    async def test_skipping_one_leaves_the_rest_running(
        self, client, clean_events, clean_series
    ):
        rows = await self._series(client)

        response = self.cancel(client, rows[1]["id"])
        assert response.status_code == 200

        live = await Event.select(Event.Cancelled).where(
            Event.LeaderSlackID == LEADER
        )
        assert sum(1 for r in live if r["Cancelled"]) == 1

    async def test_this_is_the_default_without_a_scope(
        self, client, clean_events, clean_series
    ):
        rows = await self._series(client)

        assert self.cancel(client, rows[0]["id"]).json()["seriesCancelled"] == 1

    async def test_following_stops_the_rest_of_the_run(
        self, client, clean_events, clean_series
    ):
        rows = await self._series(client)

        response = self.cancel(client, rows[1]["id"], scope="following")
        assert response.json()["seriesCancelled"] == 3

        live = await Event.select(Event.Cancelled).where(
            Event.LeaderSlackID == LEADER
        )
        assert sum(1 for r in live if not r["Cancelled"]) == 1

    async def test_the_old_series_word_still_means_everything(
        self, client, clean_events, clean_series
    ):
        rows = await self._series(client)

        response = self.cancel(client, rows[0]["id"], scope="series")
        assert response.json()["seriesCancelled"] == 4

    async def test_a_skipped_date_does_not_come_back_when_the_series_is_edited(
        self, client, clean_events, clean_series
    ):
        rows = await self._series(client)
        self.cancel(client, rows[1]["id"])

        patch(client, rows[0]["id"], title="Renamed", scope="all")

        cancelled = await Event.select(Event.Cancelled, Event.Title).where(
            Event.LeaderSlackID == LEADER
        )
        assert sum(1 for r in cancelled if r["Cancelled"]) == 1
