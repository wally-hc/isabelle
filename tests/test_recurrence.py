from datetime import datetime

import pytest

from isabelle.recurrence import MAX_COUNT
from isabelle.recurrence import MAX_INTERVAL
from isabelle.recurrence import describe
from isabelle.recurrence import is_endless
from isabelle.recurrence import occurrences
from isabelle.recurrence import to_rrule
from isabelle.recurrence import validate_recurrence


def at(text):
    return datetime.fromisoformat(text)


START = at("2026-10-06T18:00")
END = at("2026-10-06T19:00")


def rule_for(payload, start=START):
    errors, rule = validate_recurrence(payload, start)
    assert errors == {}, errors
    return rule


def days(payload, limit=8, start=START):
    return [
        d[0].strftime("%a %d %b")
        for d in occurrences(start, END, rule_for(payload, start), limit=limit)
    ]


class TestTheOldShapeStillWorks:
    def test_a_plain_count_series(self):
        rule = rule_for({"frequency": "weekly", "count": 3})
        assert rule["ends"] == {"type": "count", "count": 3}
        assert to_rrule(rule) == "FREQ=WEEKLY;COUNT=3"

    def test_fortnightly_becomes_an_interval(self):
        rule = rule_for({"frequency": "fortnightly", "count": 3})
        assert rule["frequency"] == "weekly"
        assert rule["interval"] == 2
        assert to_rrule(rule) == "FREQ=WEEKLY;INTERVAL=2;COUNT=3"

    def test_monthly_still_skips_months_without_that_day(self):
        dates = occurrences(
            at("2026-01-31T18:00"),
            at("2026-01-31T19:00"),
            rule_for({"frequency": "monthly", "count": 3}, at("2026-01-31T18:00")),
        )
        assert [d[0].date().isoformat() for d in dates] == [
            "2026-01-31",
            "2026-03-31",
            "2026-05-31",
        ]


class TestTwiceAWeek:
    def test_picks_both_days(self):
        assert days({"frequency": "weekly", "byDay": ["TU", "TH"], "count": 6}) == [
            "Tue 06 Oct",
            "Thu 08 Oct",
            "Tue 13 Oct",
            "Thu 15 Oct",
            "Tue 20 Oct",
            "Thu 22 Oct",
        ]

    def test_weekdays_only(self):
        assert days(
            {
                "frequency": "weekly",
                "byDay": ["MO", "TU", "WE", "TH", "FR"],
                "count": 5,
            }
        ) == ["Tue 06 Oct", "Wed 07 Oct", "Thu 08 Oct", "Fri 09 Oct", "Mon 12 Oct"]

    def test_the_days_come_out_in_week_order_however_they_went_in(self):
        rule = rule_for({"frequency": "weekly", "byDay": ["TH", "MO", "TH"], "count": 4})
        assert rule["byDay"] == ["MO", "TH"]

    def test_only_a_weekly_series_can_pick_days(self):
        errors, _ = validate_recurrence(
            {"frequency": "monthly", "byDay": ["TU"], "count": 3}, START
        )
        assert "weekly" in errors["recurrence"]

    def test_rejects_a_day_that_is_not_a_day(self):
        errors, _ = validate_recurrence(
            {"frequency": "weekly", "byDay": ["XX"], "count": 3}, START
        )
        assert "byDay" in errors["recurrence"]


class TestInterval:
    def test_every_third_week(self):
        rule = rule_for({"frequency": "weekly", "interval": 3, "count": 3})
        assert to_rrule(rule) == "FREQ=WEEKLY;INTERVAL=3;COUNT=3"
        assert days({"frequency": "weekly", "interval": 3, "count": 3}) == [
            "Tue 06 Oct",
            "Tue 27 Oct",
            "Tue 17 Nov",
        ]

    def test_an_interval_of_one_is_left_out_of_the_rule(self):
        assert "INTERVAL" not in to_rrule(
            rule_for({"frequency": "weekly", "interval": 1, "count": 2})
        )

    def test_rejects_a_silly_interval(self):
        for interval in (0, -1, MAX_INTERVAL + 1, "2", 1.5):
            errors, _ = validate_recurrence(
                {"frequency": "weekly", "interval": interval, "count": 3}, START
            )
            assert "interval" in errors["recurrence"]


class TestEndingOnADate:
    def test_stops_at_the_date(self):
        assert days(
            {"frequency": "weekly", "ends": {"type": "until", "until": "2026-11-05"}}
        ) == ["Tue 06 Oct", "Tue 13 Oct", "Tue 20 Oct", "Tue 27 Oct", "Tue 03 Nov"]

    def test_stores_the_date_in_utc(self):
        rule = rule_for(
            {"frequency": "weekly", "ends": {"type": "until", "until": "2026-11-05"}}
        )
        assert to_rrule(rule).endswith("UNTIL=20261105T000000Z")

    def test_the_end_must_come_after_the_start(self):
        errors, _ = validate_recurrence(
            {"frequency": "weekly", "ends": {"type": "until", "until": "2026-09-01"}},
            START,
        )
        assert "after" in errors["recurrence"]

    def test_the_end_cannot_be_absurdly_far_away(self):
        errors, _ = validate_recurrence(
            {"frequency": "weekly", "ends": {"type": "until", "until": "2099-01-01"}},
            START,
        )
        assert "years" in errors["recurrence"]

    def test_rejects_something_that_is_not_a_date(self):
        errors, _ = validate_recurrence(
            {"frequency": "weekly", "ends": {"type": "until", "until": "soon"}}, START
        )
        assert "date" in errors["recurrence"]


class TestNeverEnding:
    def test_the_rule_carries_no_ending(self):
        rule = rule_for({"frequency": "weekly", "ends": {"type": "never"}})
        assert to_rrule(rule) == "FREQ=WEEKLY"
        assert is_endless(rule) is True

    def test_it_keeps_producing_dates(self):
        assert len(days({"frequency": "weekly", "ends": {"type": "never"}}, limit=40)) == 40

    def test_it_still_stops_where_it_is_told_to(self):
        dates = occurrences(
            START, END, rule_for({"frequency": "weekly", "ends": {"type": "never"}}), limit=5
        )
        assert len(dates) == 5

    def test_a_finite_series_is_not_endless(self):
        assert is_endless(rule_for({"frequency": "weekly", "count": 3})) is False
        assert is_endless(None) is False


class TestValidation:
    def test_absent_recurrence_is_fine(self):
        for value in (None, {}, ""):
            errors, rule = validate_recurrence(value, START)
            assert errors == {}
            assert rule is None

    def test_rejects_an_unknown_frequency(self):
        errors, _ = validate_recurrence({"frequency": "hourly", "count": 3}, START)
        assert "frequency" in errors["recurrence"]

    def test_rejects_an_unknown_ending(self):
        errors, _ = validate_recurrence(
            {"frequency": "weekly", "ends": {"type": "whenever"}}, START
        )
        assert "ends.type" in errors["recurrence"]

    @pytest.mark.parametrize("count", ["4", 4.5, None, True])
    def test_rejects_a_count_that_is_not_a_whole_number(self, count):
        errors, _ = validate_recurrence({"frequency": "weekly", "count": count}, START)
        assert "count" in errors["recurrence"]

    def test_rejects_a_runaway_count(self):
        errors, _ = validate_recurrence(
            {"frequency": "weekly", "count": MAX_COUNT + 1}, START
        )
        assert str(MAX_COUNT) in errors["recurrence"]

    def test_rejects_a_zone_that_is_not_a_zone(self):
        errors, _ = validate_recurrence(
            {"frequency": "weekly", "count": 3, "timezone": "Middle Earth"}, START
        )
        assert "IANA" in errors["recurrence"]


class TestTimezone:
    def test_a_weekly_series_keeps_its_local_hour_across_a_clock_change(self):
        rule = rule_for(
            {
                "frequency": "weekly",
                "count": 3,
                "timezone": "Europe/London",
            },
            at("2026-10-24T17:00"),
        )
        dates = occurrences(at("2026-10-24T17:00"), at("2026-10-24T18:00"), rule)
        assert [d[0].isoformat() for d in dates] == [
            "2026-10-24T17:00:00",
            "2026-10-31T18:00:00",
            "2026-11-07T18:00:00",
        ]

    def test_an_until_date_survives_the_same_journey(self):
        rule = rule_for(
            {
                "frequency": "weekly",
                "timezone": "Europe/London",
                "ends": {"type": "until", "until": "2026-11-08T00:00:00Z"},
            },
            at("2026-10-24T17:00"),
        )
        dates = occurrences(at("2026-10-24T17:00"), at("2026-10-24T18:00"), rule)
        assert len(dates) == 3


class TestDescribe:
    def test_says_what_the_series_does(self):
        assert (
            describe(rule_for({"frequency": "weekly", "count": 4}))
            == "Weekly · 4 dates"
        )
        assert (
            describe(rule_for({"frequency": "weekly", "byDay": ["TU", "TH"], "count": 6}))
            == "Weekly on Tuesday and Thursday · 6 dates"
        )
        assert (
            describe(rule_for({"frequency": "weekly", "interval": 2, "count": 3}))
            == "Every 2 weeks · 3 dates"
        )
        assert (
            describe(rule_for({"frequency": "weekly", "ends": {"type": "never"}}))
            == "Weekly · ongoing"
        )

    def test_says_nothing_without_a_rule(self):
        assert describe(None) is None
