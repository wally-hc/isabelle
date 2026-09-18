from isabelle.attendance import ALL
from isabelle.attendance import THIS
from isabelle.attendance import attendees_of
from isabelle.attendance import followers_of
from isabelle.attendance import public_count
from isabelle.attendance import read_rsvp_scope
from isabelle.attendance import recipients_for
from isabelle.attendance import toggle_follower


def event(*slack_ids, legacy=()):
    return {
        "RSVPData": {f"sub-{i}": {"slackId": s} for i, s in enumerate(slack_ids)},
        "InterestedUsers": list(legacy),
    }


def series(*slack_ids):
    return {"SeriesID": "S1", "Followers": list(slack_ids)}


class TestReadRsvpScope:
    def test_takes_the_two_it_knows(self):
        assert read_rsvp_scope("this") == THIS
        assert read_rsvp_scope("ALL") == ALL

    def test_defaults_to_the_one_date(self):
        assert read_rsvp_scope(None) == THIS
        assert read_rsvp_scope("everything") == THIS


class TestAttendeesOf:
    def test_reads_the_rsvp_data(self):
        assert attendees_of(event("U1", "U2")) == ["U1", "U2"]

    def test_still_reads_the_legacy_column(self):
        assert attendees_of(event("U1", legacy=["U9"])) == ["U1", "U9"]

    def test_never_lists_anyone_twice(self):
        assert attendees_of(event("U1", "U1", legacy=["U1"])) == ["U1"]

    def test_reads_it_even_when_it_arrives_as_json_text(self):
        import json

        raw = {"RSVPData": json.dumps({"s1": {"slackId": "U1"}})}
        assert attendees_of(raw) == ["U1"]

    def test_copes_with_junk(self):
        assert attendees_of({}) == []
        assert attendees_of({"RSVPData": None, "InterestedUsers": None}) == []
        assert attendees_of({"RSVPData": "not a dict"}) == []
        assert attendees_of({"RSVPData": "[1, 2]"}) == []
        assert attendees_of({"RSVPData": {"a": None}}) == []


class TestFollowersOf:
    def test_reads_the_series(self):
        assert followers_of(series("U1", "U2")) == ["U1", "U2"]

    def test_copes_with_nothing(self):
        assert followers_of(None) == []
        assert followers_of({}) == []


class TestRecipientsFor:
    def test_joins_the_date_and_the_series(self):
        assert recipients_for(event("U1"), series("U2")) == ["U1", "U2"]

    def test_someone_on_both_lists_is_reminded_once(self):
        assert recipients_for(event("U1", "U2"), series("U2", "U3")) == [
            "U1",
            "U2",
            "U3",
        ]

    def test_works_without_a_series(self):
        assert recipients_for(event("U1")) == ["U1"]

    def test_a_follower_alone_is_still_reminded(self):
        assert recipients_for(event(), series("U7")) == ["U7"]


class TestToggleFollower:
    def test_following_adds_them(self):
        after, following = toggle_follower(series("U1"), "U2")
        assert after == ["U1", "U2"]
        assert following is True

    def test_following_again_removes_them(self):
        after, following = toggle_follower(series("U1", "U2"), "U2")
        assert after == ["U1"]
        assert following is False

    def test_a_missing_person_changes_nothing(self):
        after, following = toggle_follower(series("U1"), None)
        assert after == ["U1"]
        assert following is False

    def test_works_on_a_series_nobody_follows_yet(self):
        after, following = toggle_follower({}, "U1")
        assert after == ["U1"]
        assert following is True


class TestPublicCount:
    def test_counts_only_the_people_on_this_date(self):
        assert public_count(event("U1", "U2")) == 2

    def test_followers_never_reach_the_public_number(self):
        one_date = event("U1")
        assert public_count(one_date) == 1
        assert len(recipients_for(one_date, series("U2", "U3"))) == 3
