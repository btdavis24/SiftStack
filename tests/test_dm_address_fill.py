"""Network-free tests for the consolidated DM-address backfill in
tracerfy_skip_tracer (_maybe_fill_dm_address + _match_results).

Regression context — the 2026-05-28 Apify run:

  The old DM-address path was a second Tracerfy batch call in obituary_enricher
  (Phase C) that sent a malformed request (missing `mailing_zip_column`) and
  always 400'd, ran pre-fit-gate, and used the same naive name split + a
  hardcoded "TN" state. DM addresses never came from Tracerfy — every record
  fell back to the property address (property_fallback 26/28).

  PR #14 deletes Phase C and instead lets the working post-fit-gate skip-trace
  pass fill the DM mailing address from the Tracerfy `mail_address` field it
  already receives. The address is only filled when the DM has no address or is
  using the property-address fallback — a verified address is never clobbered.

Run:  python tests/test_dm_address_fill.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from notice_parser import NoticeData  # noqa: E402
from tracerfy_skip_tracer import (  # noqa: E402
    _maybe_fill_dm_address,
    _match_results,
)


def _notice(**kw) -> NoticeData:
    n = NoticeData()
    for k, v in kw.items():
        setattr(n, k, v)
    return n


_REC = {
    "first_name": "Sherri",
    "last_name": "Pack",
    "mail_address": "742 Evergreen Ter",
    "mail_city": "Louisville",
    "mail_state": "KY",
    "mail_zip": "40220",
}


# ── _maybe_fill_dm_address ────────────────────────────────────────────────
def test_fills_when_dm_address_empty():
    n = _notice(decision_maker_name="Sherri Pack", address="11412 Garden Trace Dr")
    stats = {"addresses_found": 0}
    _maybe_fill_dm_address(n, _REC, stats)
    assert n.decision_maker_street == "742 Evergreen Ter"
    assert n.decision_maker_city == "Louisville"
    assert n.decision_maker_state == "KY"
    assert n.decision_maker_zip == "40220"
    assert stats["addresses_found"] == 1
    print("PASS: test_fills_when_dm_address_empty")


def test_overrides_property_fallback():
    """DM street == property address (the fallback) → upgrade to skip-traced."""
    n = _notice(
        decision_maker_name="Sherri Pack",
        address="11412 Garden Trace Dr",
        decision_maker_street="11412 Garden Trace Dr",
        decision_maker_city="Louisville",
        decision_maker_state="KY",
        decision_maker_zip="40229",
    )
    stats = {"addresses_found": 0}
    _maybe_fill_dm_address(n, _REC, stats)
    assert n.decision_maker_street == "742 Evergreen Ter"
    assert stats["addresses_found"] == 1
    print("PASS: test_overrides_property_fallback")


def test_property_fallback_match_is_case_insensitive():
    n = _notice(
        decision_maker_name="Sherri Pack",
        address="11412 Garden Trace Dr",
        decision_maker_street="11412 GARDEN TRACE DR",
    )
    stats = {"addresses_found": 0}
    _maybe_fill_dm_address(n, _REC, stats)
    assert n.decision_maker_street == "742 Evergreen Ter"
    print("PASS: test_property_fallback_match_is_case_insensitive")


def test_preserves_verified_address():
    """A real DM address (different from the property) is never clobbered."""
    n = _notice(
        decision_maker_name="Sherri Pack",
        address="11412 Garden Trace Dr",
        decision_maker_street="8510 Atrium Dr",
        decision_maker_city="Louisville",
        decision_maker_state="KY",
        decision_maker_zip="40220",
    )
    stats = {"addresses_found": 0}
    _maybe_fill_dm_address(n, _REC, stats)
    assert n.decision_maker_street == "8510 Atrium Dr"
    assert stats["addresses_found"] == 0
    print("PASS: test_preserves_verified_address")


def test_noop_when_rec_has_no_mail_address():
    n = _notice(decision_maker_name="Sherri Pack", address="11412 Garden Trace Dr")
    stats = {"addresses_found": 0}
    _maybe_fill_dm_address(n, {"first_name": "Sherri", "last_name": "Pack"}, stats)
    assert n.decision_maker_street == ""
    assert stats["addresses_found"] == 0
    print("PASS: test_noop_when_rec_has_no_mail_address")


def test_missing_rec_city_keeps_existing():
    """When the rec omits mail_city, keep the existing DM city rather than blank."""
    n = _notice(
        decision_maker_name="Sherri Pack",
        address="11412 Garden Trace Dr",
        decision_maker_street="11412 Garden Trace Dr",
        decision_maker_city="Louisville",
        decision_maker_state="KY",
    )
    rec = {"first_name": "Sherri", "last_name": "Pack",
           "mail_address": "742 Evergreen Ter"}
    stats = {"addresses_found": 0}
    _maybe_fill_dm_address(n, rec, stats)
    assert n.decision_maker_street == "742 Evergreen Ter"
    assert n.decision_maker_city == "Louisville"  # preserved
    assert n.decision_maker_state == "KY"          # preserved
    print("PASS: test_missing_rec_city_keeps_existing")


# ── _match_results integration ────────────────────────────────────────────
def test_match_results_fills_address_without_phones():
    """A primary DM record with a mail_address but NO phones still gets the
    address upgraded — the 0/4-phones case from 2026-05-28."""
    n = _notice(
        notice_type="probate",
        owner_deceased="yes",
        decision_maker_name="Sherri Pack",
        address="11412 Garden Trace Dr",
        decision_maker_street="11412 Garden Trace Dr",
    )
    lookup_map = [(n, "Sherri", "Pack", "11412 Garden Trace Dr",
                   "Louisville", "40229", "Sherri Pack")]
    stats = {"matched": 0, "phones_found": 0, "emails_found": 0,
             "addresses_found": 0}
    _match_results([dict(_REC)], lookup_map, stats)
    assert n.decision_maker_street == "742 Evergreen Ter"
    assert stats["addresses_found"] == 1
    assert stats["matched"] == 0  # no phones/emails → not counted as a match
    assert not n.primary_phone
    print("PASS: test_match_results_fills_address_without_phones")


def test_match_results_fills_address_and_phones():
    n = _notice(
        notice_type="probate",
        owner_deceased="yes",
        decision_maker_name="Sherri Pack",
        address="11412 Garden Trace Dr",
        decision_maker_street="11412 Garden Trace Dr",
    )
    lookup_map = [(n, "Sherri", "Pack", "11412 Garden Trace Dr",
                   "Louisville", "40229", "Sherri Pack")]
    rec = dict(_REC)
    rec["primary_phone"] = "5025551234"
    rec["email_1"] = "sherri@example.com"
    stats = {"matched": 0, "phones_found": 0, "emails_found": 0,
             "addresses_found": 0}
    _match_results([rec], lookup_map, stats)
    assert n.decision_maker_street == "742 Evergreen Ter"
    assert n.primary_phone == "5025551234"
    assert n.email_1 == "sherri@example.com"
    assert stats["addresses_found"] == 1
    assert stats["matched"] == 1
    print("PASS: test_match_results_fills_address_and_phones")


if __name__ == "__main__":
    test_fills_when_dm_address_empty()
    test_overrides_property_fallback()
    test_property_fallback_match_is_case_insensitive()
    test_preserves_verified_address()
    test_noop_when_rec_has_no_mail_address()
    test_missing_rec_city_keeps_existing()
    test_match_results_fills_address_without_phones()
    test_match_results_fills_address_and_phones()
    print("\nALL PASS: dm_address_fill")
