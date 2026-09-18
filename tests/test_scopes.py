from datetime import datetime
from datetime import timedelta

from isabelle.scopes import ALL
from isabelle.scopes import FOLLOWING
from isabelle.scopes import THIS
from isabelle.scopes import changed_fields
from isabelle.scopes import merge_overrides
from isabelle.scopes import read_scope
from isabelle.scopes import siblings_in_scope
from isabelle.scopes import time_shift
from isabelle.scopes import updates_for_sibling


def at(text):
    return datetime.fromisoformat(text)


def row(id_, slot, *, overridden=None, cancelled=False, hours=1):
    return {
        "id": id_,
        "SeriesID": "S1",
        "OccurrenceStart": slot,
        "StartTime": slot,
        "EndTime": slot + timedelta(hours=hours),
        "OverriddenFields": overridden or [],
        "Cancelled": cancelled,
        "Title": "Website Circle",
    }


class TestReadScope:
    def test_takes_the_ones_it_knows(self):
        assert read_scope("this") == THIS
        assert read_scope("FOLLOWING") == FOLLOWING
        assert read_scope(" all ") == ALL

    def test_falls_back_to_this_occurrence_only(self):
        assert read_scope(None) == THIS
        assert read_scope("") == THIS
        assert read_scope("everything") == THIS


class TestChangedFields:
    def test_notices_what_actually_changed(self):
        before = {"Title": "Old", "EventLink": "https://a"}
        assert changed_fields(
            before, {"Title": "New", "EventLink": "https://a"}
        ) == ["Title"]

    def test_ignores_fields_that_were_not_sent(self):
        assert changed_fields({"Title": "Old"}, {}) == []

    def test_counts_a_time_change(self):
        before = {"StartTime": at("2026-10-08T18:00")}
        assert changed_fields(
            before, {"StartTime": at("2026-10-09T18:00")}
        ) == ["StartTime"]


class TestMergeOverrides:
    def test_adds_without_repeating(self):
        assert merge_overrides(["Title"], ["Title", "StartTime"]) == [
            "StartTime",
            "Title",
        ]

    def test_copes_with_nothing(self):
        assert merge_overrides(None, []) == []


class TestTimeShift:
    def test_measures_the_move(self):
        shift = time_shift(
            {"StartTime": at("2026-10-08T18:00")},
            {"StartTime": at("2026-10-09T18:00")},
        )
        assert shift == timedelta(days=1)

    def test_is_nothing_when_the_time_did_not_move(self):
        assert (
            time_shift(
                {"StartTime": at("2026-10-08T18:00")},
                {"StartTime": at("2026-10-08T18:00")},
            )
            is None
        )

    def test_is_nothing_without_both_times(self):
        assert time_shift({}, {"StartTime": at("2026-10-08T18:00")}) is None


class TestUpdatesForSibling:
    def test_passes_the_shared_fields_along(self):
        out = updates_for_sibling(row("b", at("2026-10-15T18:00")), {"Title": "New"}, None)
        assert out == {"Title": "New"}

    def test_leaves_an_overridden_field_alone(self):
        sibling = row("b", at("2026-10-15T18:00"), overridden=["Title"])
        assert updates_for_sibling(sibling, {"Title": "New"}, None) == {}

    def test_shifts_the_sibling_by_the_same_amount(self):
        sibling = row("b", at("2026-10-15T18:00"))
        out = updates_for_sibling(sibling, {}, timedelta(days=1))
        assert out["StartTime"] == at("2026-10-16T18:00")
        assert out["EndTime"] == at("2026-10-16T19:00")

    def test_never_shifts_an_occurrence_that_was_moved_by_hand(self):
        sibling = row("b", at("2026-10-15T18:00"), overridden=["StartTime"])
        assert "StartTime" not in updates_for_sibling(sibling, {}, timedelta(days=1))

    def test_never_copies_the_anchor_time_verbatim(self):
        sibling = row("b", at("2026-10-15T18:00"))
        out = updates_for_sibling(
            sibling, {"StartTime": at("2026-10-09T18:00")}, timedelta(days=1)
        )
        assert out["StartTime"] == at("2026-10-16T18:00")


class TestSiblingsInScope:
    def setup_method(self):
        self.rows = [
            row("a", at("2026-10-01T18:00")),
            row("b", at("2026-10-08T18:00")),
            row("c", at("2026-10-15T18:00")),
            row("d", at("2026-10-22T18:00")),
        ]
        self.anchor = self.rows[1]

    def test_this_touches_nothing_else(self):
        assert siblings_in_scope(THIS, self.anchor, self.rows) == []

    def test_following_takes_only_the_later_ones(self):
        out = siblings_in_scope(FOLLOWING, self.anchor, self.rows)
        assert [r["id"] for r in out] == ["c", "d"]

    def test_all_takes_every_other_one(self):
        out = siblings_in_scope(ALL, self.anchor, self.rows)
        assert [r["id"] for r in out] == ["a", "c", "d"]

    def test_never_includes_the_anchor(self):
        for scope in (FOLLOWING, ALL):
            out = siblings_in_scope(scope, self.anchor, self.rows)
            assert self.anchor["id"] not in [r["id"] for r in out]

    def test_skips_cancelled_occurrences(self):
        rows = self.rows + [row("e", at("2026-10-29T18:00"), cancelled=True)]
        out = siblings_in_scope(ALL, self.anchor, rows)
        assert "e" not in [r["id"] for r in out]

    def test_following_uses_the_intended_date_not_the_moved_one(self):
        moved = row("b", at("2026-10-08T18:00"))
        moved["StartTime"] = at("2026-10-30T18:00")
        out = siblings_in_scope(FOLLOWING, moved, self.rows)
        assert [r["id"] for r in out] == ["c", "d"]
