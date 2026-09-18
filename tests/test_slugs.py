from datetime import datetime

from isabelle.slugs import base_slug
from isabelle.slugs import date_suffix
from isabelle.slugs import slug_for


def at(text):
    return datetime.fromisoformat(text)


class TestBaseSlug:
    def test_matches_the_shape_the_site_routes_on(self):
        assert base_slug("Website Circle") == "website-circle"
        assert base_slug("AMA: Zach Latta") == "ama-zach-latta"

    def test_copes_with_nothing(self):
        assert base_slug(None) == ""
        assert base_slug("") == ""


class TestDateSuffix:
    def test_reads_as_a_date(self):
        assert date_suffix(at("2026-10-01T19:00")) == "oct-1-2026"
        assert date_suffix(at("2026-09-24T19:00")) == "sep-24-2026"

    def test_is_empty_when_there_is_no_date(self):
        assert date_suffix(None) == ""
        assert date_suffix("not a date") == ""


class TestSlugFor:
    def test_a_one_off_keeps_its_plain_slug(self):
        assert slug_for("Code in the Dark", at("2026-10-01T19:00")) == (
            "code-in-the-dark"
        )

    def test_a_series_occurrence_carries_its_date(self):
        assert slug_for("Website Circle", at("2026-10-01T19:00"), "S1") == (
            "website-circle-oct-1-2026"
        )

    def test_every_date_of_a_series_gets_a_different_slug(self):
        slugs = {
            slug_for("Website Circle", at(start), "S1")
            for start in (
                "2026-09-24T19:00",
                "2026-10-01T19:00",
                "2026-10-08T19:00",
                "2026-10-15T19:00",
            )
        }
        assert len(slugs) == 4

    def test_two_series_on_the_same_day_still_differ_by_title(self):
        assert slug_for("Website Circle", at("2026-10-01T19:00"), "S1") != slug_for(
            "Code in the Dark", at("2026-10-01T19:00"), "S2"
        )

    def test_the_same_occurrence_always_slugs_the_same(self):
        first = slug_for("Website Circle", at("2026-10-01T19:00"), "S1")
        again = slug_for("Website Circle", at("2026-10-01T19:00"), "S1")
        assert first == again

    def test_falls_back_to_the_base_when_there_is_no_date(self):
        assert slug_for("Website Circle", None, "S1") == "website-circle"
