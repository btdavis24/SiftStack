"""Network-free unit tests for the death/identity guard (spec task 2g-3).

Covers the four guard behaviors:
  * Davis — DM resolved to a dead spouse -> all DM flat phones dropped.
  * deceased-heir — an heir flagged status==deceased with phones -> phones cleared
    and the suppression recorded in skip_trace_guard_notes (audit-trail must_have).
  * Armstrong — a same-name wrong-age contact (disambiguate -> None) -> flagged
    `unconfirmed`, phones HELD (not cleared), NEVER promoted.
  * living DM — a clean confirmed DM -> no suppression, phones intact.

No network: `disambiguate` is injected via the module attribute per test.
Standalone-script style per TESTING.md (bare asserts + print PASS).

Run:  python tests/test_skip_trace_guard.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import skip_trace_guard as guard  # noqa: E402
from notice_parser import NoticeData  # noqa: E402


def test_davis_dead_spouse_dropped():
    """DM is the husband dead since 2012 (preceded_in_death/deceased heir) ->
    every DM flat phone is death-suppressed."""
    n = NoticeData()
    n.decision_maker_name = "Robert Davis"
    n.date_of_death = "2024-02-01"
    n.primary_phone = "5025550000"
    n.mobile_1 = "5025550001"
    # The DM name appears as a deceased / preceded_in_death heir.
    n.heir_map_json = json.dumps([
        {"name": "Robert Davis", "status": "deceased",
         "preceded_in_death": True, "phones": [], "emails": []},
    ])

    r = guard.guard_traced_contacts(n)

    assert n.primary_phone == "", f"primary_phone not cleared: {n.primary_phone!r}"
    assert n.mobile_1 == "", f"mobile_1 not cleared: {n.mobile_1!r}"
    assert r["suppressed_phones"] == 2, r
    assert "death-suppressed" in n.skip_trace_guard_notes, n.skip_trace_guard_notes
    print("PASS: test_davis_dead_spouse_dropped")


def test_deceased_heir_phones_suppressed():
    """A LIVING confirmed DM, plus a heir flagged status==deceased with phones ->
    the deceased heir's phones/emails are cleared and audited (deceased-HEIR path)."""
    n = NoticeData()
    n.decision_maker_name = "Jane Smith"
    n.decision_maker_status = "verified_living"
    n.heir_map_json = json.dumps([
        {"name": "Jane Smith", "status": "verified_living",
         "phones": ["5025551111"], "emails": []},
        {"name": "Dead Heir", "status": "deceased",
         "phones": ["5025550000"], "emails": ["dead@example.com"]},
    ])

    r = guard.guard_traced_contacts(n)

    heirs = json.loads(n.heir_map_json)
    dead = next(h for h in heirs if h["name"] == "Dead Heir")
    assert dead["phones"] == [], f"deceased heir phones not cleared: {dead['phones']}"
    assert dead["emails"] == [], f"deceased heir emails not cleared: {dead['emails']}"
    # Living DM heir untouched.
    living = next(h for h in heirs if h["name"] == "Jane Smith")
    assert living["phones"] == ["5025551111"], living["phones"]
    assert r["suppressed_phones"] >= 1, r
    notes = n.skip_trace_guard_notes
    assert "death-suppressed heir" in notes or (
        "Dead Heir" in notes and "status=deceased" in notes
    ), notes
    print("PASS: test_deceased_heir_phones_suppressed")


def test_armstrong_wrong_age_unconfirmed():
    """A same-name wrong-age contact: inject disambiguate -> None (below
    threshold). Phone is HELD, DM flagged unconfirmed, audited."""
    saved = guard.disambiguate
    guard.disambiguate = lambda *a, **k: None
    try:
        n = NoticeData()
        n.decision_maker_name = "Barry Armstrong"
        n.date_of_death = "2024-02-01"
        n.address = "123 Real St"
        n.primary_phone = "5025559999"
        # Tracerfy attached an age that conflicts + a non-matching address.
        n.heir_map_json = json.dumps([
            {"name": "Barry Armstrong", "status": "verified_living",
             "age": 80, "addresses": ["999 Wrong Ave"],
             "phones": [], "emails": []},
        ])

        r = guard.guard_traced_contacts(n)

        assert n.primary_phone == "5025559999", \
            f"phone wrongly cleared: {n.primary_phone!r}"
        assert n.decision_maker_status == "unconfirmed", n.decision_maker_status
        assert "unconfirmed" in n.skip_trace_guard_notes, n.skip_trace_guard_notes
        assert r["unconfirmed"] is True, r
    finally:
        guard.disambiguate = saved
    print("PASS: test_armstrong_wrong_age_unconfirmed")


def test_living_dm_confirmed_passes():
    """A clean living DM with matching age/address: disambiguate returns a result
    -> no suppression, status not flagged unconfirmed, phones intact."""
    saved = guard.disambiguate

    class _Res:
        pass

    guard.disambiguate = lambda *a, **k: _Res()
    try:
        n = NoticeData()
        n.decision_maker_name = "Living Person"
        n.date_of_death = "2024-02-01"
        n.address = "123 Real St"
        n.decision_maker_status = "verified_living"
        n.primary_phone = "5025558888"
        n.heir_map_json = json.dumps([
            {"name": "Living Person", "status": "verified_living",
             "age": 55, "addresses": ["123 Real St"],
             "phones": [], "emails": []},
        ])

        r = guard.guard_traced_contacts(n)

        assert n.primary_phone == "5025558888", n.primary_phone
        assert n.decision_maker_status == "verified_living", n.decision_maker_status
        assert r["unconfirmed"] is False, r
        assert r["suppressed_phones"] == 0, r
    finally:
        guard.disambiguate = saved
    print("PASS: test_living_dm_confirmed_passes")


def test_guard_all_aggregates():
    """guard_all rolls up suppressed/unconfirmed counts across a list."""
    n1 = NoticeData()
    n1.decision_maker_name = "Robert Davis"
    n1.decedent_name = "Robert Davis"
    n1.primary_phone = "5025550000"
    n2 = NoticeData()
    n2.decision_maker_name = "Jane Smith"
    n2.decision_maker_status = "verified_living"

    agg = guard.guard_all([n1, n2])
    assert agg["records"] == 2, agg
    assert agg["suppressed_phones"] >= 1, agg
    print("PASS: test_guard_all_aggregates")


if __name__ == "__main__":
    test_davis_dead_spouse_dropped()
    test_deceased_heir_phones_suppressed()
    test_armstrong_wrong_age_unconfirmed()
    test_living_dm_confirmed_passes()
    test_guard_all_aggregates()
    print("\nALL PASS: skip_trace_guard")
