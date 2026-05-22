"""Unit tests for kentucky_title_classifier.classify_title_path (Phase 2f).

Standalone script (NOT pytest) per .planning/codebase/TESTING.md:
  * bare ``assert`` + ``print("PASS: ...")``
  * ``sys.path.insert`` to reach ``src/``
  * build ``NoticeData`` inline; one fixture per cited case
Run directly:  python tests/test_title_classifier.py
An AssertionError propagates to a non-zero exit; clean run exits 0.

Cited cases (from docs/phase_2f_title_path_spec.md + MEMORY notes):
  * Sauer    — Christian/Patricia Sauer Revocable Living Trust   → successor_trustee
  * Karem    — surviving wife Ann Lenore, joint deed 9806/0835   → surviving_owner
  * Caffee   — property deeded to son Jeffrey 2022 pre-death     → out_of_estate
  * Bell     — estate sold post-will to D&M Properties           → out_of_estate
  * Humphrey — renter, NO Jefferson real estate                  → no_property
  * standard — clean sole-executor, decedent on title            → standard_probate
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from notice_parser import NoticeData
from kentucky_title_classifier import classify_title_path, TRUST_OWNER_RE


# ── successor_trustee ──────────────────────────────────────────────────
def test_sauer_successor_trustee():
    n = NoticeData(
        notice_type="probate",
        county="Jefferson",
        state="KY",
        address="9609 Dolphin Ct",
        decedent_name="SAUER, CHRISTIAN A",
        pva_owner_string="CHRISTIAN A & PATRICIA SAUER REVOCABLE LIVING TRUST",
    )
    classify_title_path(n)
    assert n.title_path == "successor_trustee", f"Got: {n.title_path}"
    assert n.dm_can_sell_without_probate == "yes", f"Got: {n.dm_can_sell_without_probate}"
    assert n.needs_trustee_research == "yes", f"Got: {n.needs_trustee_research}"
    print("PASS: test_sauer_successor_trustee")


def test_trust_unconfirmed_falls_back():
    # Trust string present but no recoverable successor-trustee grantee
    # (no deed-chain trust holder, no "<NAME> TRUSTEE" token) → flag set +
    # fall back to executor (locked decision 3, Smith-Charles).
    n = NoticeData(
        notice_type="probate",
        county="Jefferson",
        state="KY",
        address="Wolf Pen Branch Rd",
        decedent_name="SMITH, CHARLES",
        pva_owner_string="SMITH CHARLES FAMILY TRUST",
    )
    classify_title_path(n)
    assert n.title_path == "successor_trustee", f"Got: {n.title_path}"
    assert n.needs_trustee_research == "yes", f"Got: {n.needs_trustee_research}"
    assert n.trustee_unconfirmed == "yes", f"Got: {n.trustee_unconfirmed}"
    print("PASS: test_trust_unconfirmed_falls_back")


# ── surviving_owner ────────────────────────────────────────────────────
def test_karem_surviving_owner():
    n = NoticeData(
        notice_type="probate",
        county="Jefferson",
        state="KY",
        address="17201 Anselmo Ln",
        decedent_name="KAREM, DONALD N",
        date_of_death="2026-02-16",
        current_property_holder="DONALD N KAREM & ANN LENORE KAREM",
        current_holder_relationship="self",
        pva_owner_string="KAREM DONALD N & ANN LENORE",
    )
    classify_title_path(n)
    assert n.title_path == "surviving_owner", f"Got: {n.title_path}"
    assert n.dm_can_sell_without_probate == "yes", f"Got: {n.dm_can_sell_without_probate}"
    print("PASS: test_karem_surviving_owner")


# ── out_of_estate ──────────────────────────────────────────────────────
def test_caffee_out_of_estate_predeath():
    # Property deeded to son Jeffrey in 2022, 4 years before death (2026) —
    # decedent no longer holds title (relationship heir_recent).
    n = NoticeData(
        notice_type="probate",
        county="Jefferson",
        state="KY",
        address="4003 Laurelwood Ave",
        decedent_name="CAFFEE, TERESA M",
        date_of_death="2026-01-09",
        heir_transferred_to="JEFFREY S CAFFEE",
        heir_transfer_date="2022-03-25",
        current_property_holder="JEFFREY S CAFFEE",
        current_holder_relationship="heir_recent",
    )
    classify_title_path(n)
    assert n.title_path == "out_of_estate", f"Got: {n.title_path}"
    print("PASS: test_caffee_out_of_estate_predeath")


def test_bell_out_of_estate_postdeath():
    # Estate sold the property AFTER death — transfer date strictly after a
    # VALID DOD ("2026-03-01" < "2026-05-01"), so the post-death branch fires.
    n = NoticeData(
        notice_type="probate",
        county="Jefferson",
        state="KY",
        address="Floyd",
        decedent_name="BELL",
        date_of_death="2026-03-01",
        heir_transfer_date="2026-05-01",
        current_property_holder="D&M PROPERTIES KY LLC",
    )
    classify_title_path(n)
    assert n.title_path == "out_of_estate", f"Got: {n.title_path}"
    print("PASS: test_bell_out_of_estate_postdeath")


# ── no_property ────────────────────────────────────────────────────────
def test_humphrey_no_property():
    n = NoticeData(
        notice_type="probate",
        county="Jefferson",
        state="KY",
        address="",
        current_property_holder="",
        current_holder_relationship="",
        decedent_name="HUMPHREY, CHARLES THOMAS",
    )
    classify_title_path(n)
    assert n.title_path == "no_property", f"Got: {n.title_path}"
    assert n.dm_can_sell_without_probate == "", f"Got: {n.dm_can_sell_without_probate}"
    print("PASS: test_humphrey_no_property")


# ── standard_probate (default) ─────────────────────────────────────────
def test_standard_probate():
    n = NoticeData(
        notice_type="probate",
        county="Jefferson",
        state="KY",
        address="123 Clean St",
        decedent_name="SMITH, JOHN A",
        pva_owner_string="SMITH JOHN A",
        current_property_holder="SMITH JOHN A",
        current_holder_relationship="self",
        owner_name="JANE SMITH",  # CourtNet executor
    )
    classify_title_path(n)
    assert n.title_path == "standard_probate", f"Got: {n.title_path}"
    assert n.dm_can_sell_without_probate == "no", f"Got: {n.dm_can_sell_without_probate}"
    print("PASS: test_standard_probate")


# ── safety: malformed dates never crash ────────────────────────────────
def test_malformed_date_does_not_crash():
    # Dedicated malformed-date safety case (SEPARATE from Bell). _safe_date
    # returns None for each garbage/partial value, so the date-comparison
    # branch is skipped and the notice falls through to a later rule.
    for tdate, dod in [
        ("not-a-date", "garbage"),
        ("2026-03-xx", "2026-13-40"),
        ("", ""),
    ]:
        n = NoticeData(
            notice_type="probate",
            county="Jefferson",
            state="KY",
            address="55 Resilient Rd",
            decedent_name="DOE, JANE",
            date_of_death=dod,
            heir_transfer_date=tdate,
            current_property_holder="DOE JANE",
            current_holder_relationship="self",
        )
        classify_title_path(n)  # must NOT raise
        assert n.title_path, f"Empty title_path for ({tdate!r}, {dod!r})"
        assert n.title_path == "standard_probate", f"Got: {n.title_path}"
    print("PASS: test_malformed_date_does_not_crash")


# ── ordering: first match wins ─────────────────────────────────────────
def test_first_match_order():
    # Satisfies BOTH a trust string AND no-property (no address / no holder).
    # Rule 1 (no_property) precedes Rule 3 (successor_trustee) → no_property.
    n = NoticeData(
        notice_type="probate",
        county="Jefferson",
        state="KY",
        address="",
        current_property_holder="",
        current_holder_relationship="",
        decedent_name="GHOST, NO ADDR",
        pva_owner_string="GHOST FAMILY REVOCABLE TRUST",
    )
    classify_title_path(n)
    assert n.title_path == "no_property", f"Got: {n.title_path}"
    print("PASS: test_first_match_order")


def test_trust_owner_re_tokens():
    # Sanity: the bounded pattern matches each canonical trust token.
    for s in (
        "JONES REVOCABLE LIVING TRUST",
        "DOE FAMILY TRUST",
        "SMITH JOHN TRUSTEE",
        "ATLAS QPRT",
        "BROWN DECLARATION OF TRUST",
        "GREEN DECL OF TRUST",
    ):
        assert TRUST_OWNER_RE.search(s), f"No match: {s}"
    assert not TRUST_OWNER_RE.search("SMITH JOHN A"), "False positive on plain name"
    print("PASS: test_trust_owner_re_tokens")


if __name__ == "__main__":
    test_sauer_successor_trustee()
    test_trust_unconfirmed_falls_back()
    test_karem_surviving_owner()
    test_caffee_out_of_estate_predeath()
    test_bell_out_of_estate_postdeath()
    test_humphrey_no_property()
    test_standard_probate()
    test_malformed_date_does_not_crash()
    test_first_match_order()
    test_trust_owner_re_tokens()
    print("\nAll title-path classifier tests passed.")
