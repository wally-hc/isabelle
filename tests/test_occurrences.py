from datetime import datetime
from datetime import timedelta

from isabelle.occurrences import expand
from isabelle.occurrences import merge


def at(text):
    return datetime.fromisoformat(text)


def series(rule="FREQ=WEEKLY;COUNT=4", tz="UTC"):
    return {"SeriesID": "S1", "Rule": rule, "Timezone": tz}


def row(start, *, slot=None, series_id="S1", hours=1, **extra):
    base = {
        "SeriesID": series_id,
        "OccurrenceStart": slot if slot is not None else start,
        "StartTime": start,
        "EndTime": start + timedelta(hours=hours),
        "Cancelled": False,
    }
    base.update(extra)
    return base


class TestExpand:
    def test_gives_the_dates_inside_the_window(self):
        dates = expand(
            series(),
            at("2026-10-01T18:00"),
            at("2026-10-01T00:00"),
            at("2026-10-31T00:00"),
        )
        assert [d.date().isoformat() for d in dates] == [
            "2026-10-01",
            "2026-10-08",
            "2026-10-15",
            "2026-10-22",
        ]

    def test_clips_to_the_window(self):
        dates = expand(
            series(),
            at("2026-10-01T18:00"),
            at("2026-10-07T00:00"),
            at("2026-10-16T00:00"),
        )
        assert [d.date().isoformat() for d in dates] == ["2026-10-08", "2026-10-15"]

    def test_an_endless_rule_still_stops_at_the_window(self):
        dates = expand(
            series(rule="FREQ=WEEKLY"),
            at("2026-10-01T18:00"),
            at("2026-10-01T00:00"),
            at("2026-12-01T00:00"),
        )
        assert len(dates) == 9
        assert dates[-1] < at("2026-12-01T00:00")

    def test_an_endless_rule_cannot_run_away(self):
        dates = expand(
            series(rule="FREQ=DAILY"),
            at("2026-01-01T18:00"),
            at("2026-01-01T00:00"),
            at("2036-01-01T00:00"),
            limit=10,
        )
        assert len(dates) == 10

    def test_expands_in_the_series_timezone(self):
        dates = expand(
            series(rule="FREQ=WEEKLY;COUNT=2", tz="Europe/London"),
            at("2026-10-24T17:00"),
            at("2026-10-01T00:00"),
            at("2026-11-30T00:00"),
        )
        assert [d.isoformat() for d in dates] == [
            "2026-10-24T17:00:00",
            "2026-10-31T18:00:00",
        ]

    def test_nothing_without_a_rule_or_an_anchor(self):
        assert expand({}, at("2026-10-01T18:00"), at("2026-10-01"), at("2026-11-01")) == []
        assert expand(series(), None, at("2026-10-01"), at("2026-11-01")) == []

    def test_nothing_for_a_backwards_window(self):
        assert (
            expand(
                series(),
                at("2026-10-01T18:00"),
                at("2026-11-01T00:00"),
                at("2026-10-01T00:00"),
            )
            == []
        )


class TestMerge:
    def test_a_slot_with_a_row_uses_the_row(self):
        stored = row(at("2026-10-08T18:00"), Title="Week two")
        out = merge([("S1", at("2026-10-08T18:00"))], [stored])
        assert out == [stored]

    def test_a_slot_without_a_row_is_filled_in(self):
        out = merge([("S1", at("2026-10-08T18:00"))], [])
        assert len(out) == 1
        assert out[0]["StartTime"] == at("2026-10-08T18:00")
        assert out[0]["SeriesID"] == "S1"

    def test_a_moved_occurrence_shows_where_it_moved_to(self):
        moved = row(at("2026-10-09T18:00"), slot=at("2026-10-08T18:00"))
        out = merge([("S1", at("2026-10-08T18:00"))], [moved])
        assert out[0]["StartTime"] == at("2026-10-09T18:00")

    def test_a_cancelled_occurrence_drops_out(self):
        gone = row(at("2026-10-08T18:00"), Cancelled=True)
        assert merge([("S1", at("2026-10-08T18:00"))], [gone]) == []

    def test_a_cancelled_occurrence_can_be_asked_for(self):
        gone = row(at("2026-10-08T18:00"), Cancelled=True)
        out = merge(
            [("S1", at("2026-10-08T18:00"))], [gone], include_cancelled=True
        )
        assert out == [gone]

    def test_a_one_off_passes_straight_through(self):
        one_off = {
            "SeriesID": "",
            "OccurrenceStart": None,
            "StartTime": at("2026-10-05T10:00"),
            "Cancelled": False,
        }
        assert merge([], [one_off]) == [one_off]

    def test_an_extra_date_outside_the_rule_is_kept(self):
        extra = row(at("2026-10-10T18:00"))
        out = merge([("S1", at("2026-10-08T18:00"))], [extra])
        assert len(out) == 2

    def test_everything_comes_back_in_date_order(self):
        out = merge(
            [
                ("S1", at("2026-10-15T18:00")),
                ("S1", at("2026-10-01T18:00")),
                ("S1", at("2026-10-08T18:00")),
            ],
            [row(at("2026-10-08T18:00"))],
        )
        starts = [o["StartTime"] for o in out]
        assert starts == sorted(starts)

    def test_two_series_do_not_borrow_each_others_rows(self):
        mine = row(at("2026-10-08T18:00"), series_id="S1", Title="Mine")
        theirs = row(at("2026-10-08T18:00"), series_id="S2", Title="Theirs")
        out = merge(
            [("S1", at("2026-10-08T18:00")), ("S2", at("2026-10-08T18:00"))],
            [mine, theirs],
        )
        assert {o["Title"] for o in out} == {"Mine", "Theirs"}

    def test_copes_with_nothing(self):
        assert merge([], []) == []


class TestSynthesisedOccurrences:
    def rows(self):
        return [
            row(
                at("2026-10-01T18:00"),
                Title="Website Circle",
                Description="Weekly build session.",
                Leader="Ada",
                LeaderSlackID="U1",
                EventLink="https://hackclub.slack.com/app_redirect?channel=hq",
                Tags=["workshop"],
                Approved=True,
                InterestCount=7,
                Calculation="website-circle-oct-1-2026",
            )
        ]

    def merged(self):
        return merge(
            [("S1", at("2026-10-01T18:00")), ("S1", at("2026-10-08T18:00"))],
            self.rows(),
        )

    def test_a_date_with_no_row_still_has_a_title(self):
        synthetic = self.merged()[1]
        assert synthetic["Title"] == "Website Circle"
        assert synthetic["Description"] == "Weekly build session."

    def test_it_inherits_who_is_running_it(self):
        synthetic = self.merged()[1]
        assert synthetic["Leader"] == "Ada"
        assert synthetic["LeaderSlackID"] == "U1"

    def test_it_inherits_where_it_happens_and_its_tags(self):
        synthetic = self.merged()[1]
        assert "app_redirect" in synthetic["EventLink"]
        assert synthetic["Tags"] == ["workshop"]

    def test_it_inherits_whether_the_series_was_approved(self):
        assert self.merged()[1]["Approved"] is True

    def test_it_keeps_the_length_of_the_real_date(self):
        synthetic = self.merged()[1]
        assert synthetic["EndTime"] - synthetic["StartTime"] == timedelta(hours=1)

    def test_it_never_inherits_another_date_s_attendance(self):
        synthetic = self.merged()[1]
        assert synthetic["InterestCount"] == 0
        assert synthetic.get("RSVPData") is None

    def test_it_never_inherits_another_date_s_identity(self):
        synthetic = self.merged()[1]
        assert synthetic["id"] is None
        assert synthetic.get("Calculation") is None

    def test_it_is_marked_as_not_yet_stored(self):
        real, synthetic = self.merged()
        assert synthetic["Synthetic"] is True
        assert "Synthetic" not in real

    def test_a_two_hour_series_stays_two_hours(self):
        rows = [row(at("2026-10-01T18:00"), hours=2, Title="Long one")]
        out = merge(
            [("S1", at("2026-10-01T18:00")), ("S1", at("2026-10-08T18:00"))], rows
        )
        assert out[1]["EndTime"] - out[1]["StartTime"] == timedelta(hours=2)

    def test_an_unknown_length_falls_back_to_an_hour_not_to_nothing(self):
        out = merge([("S1", at("2026-10-08T18:00"))], [])
        assert out[0]["EndTime"] - out[0]["StartTime"] == timedelta(hours=1)

    def test_a_series_with_no_rows_at_all_still_yields_something(self):
        out = merge([("S1", at("2026-10-01T18:00"))], [])
        assert len(out) == 1
        assert out[0]["StartTime"] == at("2026-10-01T18:00")
