"""Network-free tests for the heir_recent uncertain-match guard in
kentucky_pva_lookup._is_uncertain_heir_recent_match.

Regression context — the 2026-05-27 HUPP/GOLDSMITH case:

  LP filed against HUPP CATHY at VALLEY DOWNS LOT 288 (= 10210 Falling Tree
  Way). JCD detected HUPP transferred to 'GOLDSMITH MARTY G GOLDSMITH MARTIN'
  on 2025-08-21 → current_property_holder set to GOLDSMITH joint string.
  PVA queried GOLDSMITH variants, returned 52 same-name candidates. Best
  holder-match was 'GOLDSMITH MARTY G' (lrsn=252427, 9930 PLAUDIT WAY) with
  score 0.75 (missing MARTIN token).

The picked parcel was the HEIR'S OTHER PROPERTY (his residence), NOT the LP
target. Two things saved the record from full data corruption:
  1. The detail page's MAILING ADDRESS field on the heir's parcel
     coincidentally pointed to 10210 Falling Tree Way (because GOLDSMITH
     uses that as his mailing).
  2. Smarty + Zillow re-fetched all the address-keyed fields by '10210
     Falling Tree Way', producing correct value / sqft / sale data.

The one field with no downstream override: parcel_id. The CSV shipped with
the WRONG parcel's PIDN.

The guard catches this scenario by all three signals:
  * relationship == 'heir_recent'
  * num_candidates >= 5 (common surname, hard to disambiguate)
  * holder_score < 0.90 (less than near-exact match)
… and clears parcel_id so the wrong reference doesn't ship.

Run:  python tests/test_uncertain_heir_recent.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from kentucky_pva_lookup import _is_uncertain_heir_recent_match  # noqa: E402


# ── Guard fires (HUPP/GOLDSMITH pattern) ──────────────────────────────────
def test_hupp_goldsmith_pattern_fires_guard():
    """The exact 2026-05-27 HUPP case parameters."""
    result = _is_uncertain_heir_recent_match(
        relationship="heir_recent",
        num_candidates=52,  # 'GOLDSMITH' surname returned 52 parcels
        holder_score=0.75,  # picked owner missing the MARTIN token
    )
    assert result is True
    print("PASS: test_hupp_goldsmith_pattern_fires_guard")


def test_guard_fires_at_min_candidates_threshold():
    """Exactly 5 candidates triggers the guard."""
    assert _is_uncertain_heir_recent_match("heir_recent", 5, 0.66) is True
    print("PASS: test_guard_fires_at_min_candidates_threshold")


def test_guard_fires_just_below_score_threshold():
    """Score 0.89 (one tick below 0.90) still fires the guard."""
    assert _is_uncertain_heir_recent_match("heir_recent", 10, 0.89) is True
    print("PASS: test_guard_fires_just_below_score_threshold")


# ── Guard does NOT fire (safety) ──────────────────────────────────────────
def test_guard_skipped_for_self_relationship():
    """Decedent IS the current owner (self) — heir_recent guard doesn't apply."""
    assert _is_uncertain_heir_recent_match("self", 52, 0.75) is False
    print("PASS: test_guard_skipped_for_self_relationship")


def test_guard_skipped_for_trust_relationship():
    """Property held by a trust — heir_recent guard doesn't apply."""
    assert _is_uncertain_heir_recent_match("trust", 52, 0.75) is False
    print("PASS: test_guard_skipped_for_trust_relationship")


def test_guard_skipped_for_empty_relationship():
    """No relationship classification — guard doesn't fire."""
    assert _is_uncertain_heir_recent_match("", 52, 0.75) is False
    print("PASS: test_guard_skipped_for_empty_relationship")


def test_guard_skipped_for_few_candidates():
    """Fewer than 5 candidates — disambiguation is more reliable."""
    assert _is_uncertain_heir_recent_match("heir_recent", 4, 0.75) is False
    assert _is_uncertain_heir_recent_match("heir_recent", 1, 0.75) is False
    print("PASS: test_guard_skipped_for_few_candidates")


def test_guard_skipped_for_near_exact_match():
    """holder_score >= 0.90: PVA picked a near-exact match → trust it."""
    assert _is_uncertain_heir_recent_match("heir_recent", 50, 0.90) is False
    assert _is_uncertain_heir_recent_match("heir_recent", 50, 1.00) is False
    print("PASS: test_guard_skipped_for_near_exact_match")


def test_guard_skipped_for_perfect_match_many_candidates():
    """Even with 100 candidates, a perfect-1.0 holder match is trusted —
    the heir's exact owner-string appears as a row. Real example: an heir
    'JONES JOHN' picks a 'JONES JOHN' PVA parcel cleanly."""
    assert _is_uncertain_heir_recent_match("heir_recent", 100, 1.00) is False
    print("PASS: test_guard_skipped_for_perfect_match_many_candidates")


# ── Boundary documentation ────────────────────────────────────────────────
def test_guard_documents_dual_threshold():
    """Document the guard requires ALL THREE signals (relationship + count
    + score). Any single signal alone won't fire it."""
    # Just relationship — skipped (no count/score limits)
    assert _is_uncertain_heir_recent_match("heir_recent", 1, 1.0) is False
    # Just count — skipped (wrong relationship)
    assert _is_uncertain_heir_recent_match("self", 50, 0.5) is False
    # Just score — skipped (wrong relationship)
    assert _is_uncertain_heir_recent_match("trust", 1, 0.5) is False
    print("PASS: test_guard_documents_dual_threshold")


if __name__ == "__main__":
    test_hupp_goldsmith_pattern_fires_guard()
    test_guard_fires_at_min_candidates_threshold()
    test_guard_fires_just_below_score_threshold()
    test_guard_skipped_for_self_relationship()
    test_guard_skipped_for_trust_relationship()
    test_guard_skipped_for_empty_relationship()
    test_guard_skipped_for_few_candidates()
    test_guard_skipped_for_near_exact_match()
    test_guard_skipped_for_perfect_match_many_candidates()
    test_guard_documents_dual_threshold()
    print("\nALL PASS: uncertain_heir_recent")
