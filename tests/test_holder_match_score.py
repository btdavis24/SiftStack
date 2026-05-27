"""Network-free tests for kentucky_pva_lookup._holder_match_score.

Regression context: in the 2026-05-27 Apify run, PVA disambiguation declined
many cases where the deed-chain holder was set. Examples:

  Holder 'BLEVINS, WILLIAM PATRICK' vs PVA candidates:
    'BLEVINS WILLIAM A' → 0.67   (old: tied 2/3, no margin)
    'BLEVINS WILLIAM E' → 0.67
    'BLEVINS WILLIAM P' → 0.67   (should be 1.0 — P = PATRICK initial)

  Holder 'BRUCE, JUDITH ANNE' vs 64 'BRUCE' parcels:
    most score 0.33 (BRUCE only)
    'BRUCE JUDITH'   → 0.67
    'BRUCE JUDITH A' → 0.67       (should be 1.0 — A = ANNE)

The fix adds an initial-to-name boost: when the row has >= holder tokens,
a single-letter row token can match the first letter of a holder token
of length > 1 (one initial may only be consumed once).

These tests pin the new behavior + the safety gate that prevents short
rows from spuriously matching long holders.

Run:  python tests/test_holder_match_score.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from kentucky_pva_lookup import _holder_match_score  # noqa: E402


# ── Boost fires correctly — the 2026-05-27 BLEVINS / BRUCE / FERNKAS bugs ─
def test_blevins_william_patrick_vs_william_p_scores_one():
    """Holder full name vs row with matching middle initial → 1.0."""
    s = _holder_match_score("BLEVINS, WILLIAM PATRICK", "BLEVINS WILLIAM P")
    assert s == 1.0, s
    print("PASS: test_blevins_william_patrick_vs_william_p_scores_one")


def test_blevins_william_patrick_vs_william_a_no_boost():
    """Different middle initial — no boost, score stays at 2/3."""
    s = _holder_match_score("BLEVINS, WILLIAM PATRICK", "BLEVINS WILLIAM A")
    assert s == 2 / 3, s
    print("PASS: test_blevins_william_patrick_vs_william_a_no_boost")


def test_blevins_no_middle_no_boost():
    """Row missing the middle initial — only exact tokens match."""
    s = _holder_match_score("BLEVINS, WILLIAM PATRICK", "BLEVINS WILLIAM")
    # Row has 2 tokens, holder has 3. Boost gate: 2 < 3 → no boost.
    assert s == 2 / 3, s
    print("PASS: test_blevins_no_middle_no_boost")


def test_bruce_judith_anne_vs_judith_a_scores_one():
    """BRUCE pattern — A matches ANNE via boost, score = 1.0."""
    s = _holder_match_score("BRUCE, JUDITH ANNE", "BRUCE JUDITH A")
    assert s == 1.0, s
    print("PASS: test_bruce_judith_anne_vs_judith_a_scores_one")


def test_fernkas_linda_adell_vs_linda_a_scores_one():
    """FERNKAS pattern: today this case scored 0.67 and passed via margin
    against weaker rivals. With the boost it scores 1.0 — same outcome,
    cleaner margin."""
    s = _holder_match_score("FERNKAS, LINDA ADELL", "FERNKAS LINDA A")
    assert s == 1.0, s
    print("PASS: test_fernkas_linda_adell_vs_linda_a_scores_one")


# ── Safety: boost MUST NOT fire when the row is too short ────────────────
def test_bruce_a_does_NOT_match_judith_anne():
    """The dangerous case: 'BRUCE A' has fewer tokens than 'BRUCE JUDITH
    ANNE'. The boost is gated to prevent A→ANNE in this direction —
    otherwise any 'BRUCE A' parcel would falsely fit any 'BRUCE *NE'
    holder. Boost SKIPPED → score stays at 1/3."""
    s = _holder_match_score("BRUCE, JUDITH ANNE", "BRUCE A")
    assert s == 1 / 3, s
    print("PASS: test_bruce_a_does_NOT_match_judith_anne")


def test_two_initials_consume_separate_names():
    """Multi-initial row → each initial can be consumed once."""
    s = _holder_match_score("SMITH JOHN PAUL", "SMITH J P")
    assert s == 1.0, s
    print("PASS: test_two_initials_consume_separate_names")


def test_initial_only_credits_first_match():
    """One row initial cannot consume itself for two holder names."""
    # Row 'SMITH J' vs holder 'SMITH JOHN JAMES' — only ONE name (whichever
    # consumed first) should be boosted. With 3-token holder and 2-token
    # row, the boost gate (row >= holder) fails → no boost at all → 1/3.
    s = _holder_match_score("SMITH JOHN JAMES", "SMITH J")
    assert s == 1 / 3, s
    print("PASS: test_initial_only_credits_first_match")


# ── Edge cases ────────────────────────────────────────────────────────────
def test_empty_holder_returns_zero():
    assert _holder_match_score("", "BLEVINS WILLIAM") == 0.0
    assert _holder_match_score("   ", "BLEVINS WILLIAM") == 0.0
    print("PASS: test_empty_holder_returns_zero")


def test_empty_row_returns_zero():
    assert _holder_match_score("BLEVINS WILLIAM", "") == 0.0
    assert _holder_match_score("BLEVINS WILLIAM", "   ") == 0.0
    print("PASS: test_empty_row_returns_zero")


def test_no_overlap_returns_zero():
    """No surname/first-name overlap → 0."""
    s = _holder_match_score("BLEVINS WILLIAM", "JONES MARK")
    assert s == 0.0, s
    print("PASS: test_no_overlap_returns_zero")


def test_exact_match_returns_one():
    s = _holder_match_score("BLEVINS WILLIAM PATRICK", "BLEVINS WILLIAM PATRICK")
    assert s == 1.0, s
    print("PASS: test_exact_match_returns_one")


def test_extra_row_tokens_dont_lower_score():
    """Row has MORE tokens than holder; full holder match → 1.0."""
    s = _holder_match_score("BLEVINS WILLIAM", "BLEVINS WILLIAM ESTATE OF")
    assert s == 1.0, s
    print("PASS: test_extra_row_tokens_dont_lower_score")


def test_punctuation_and_case_ignored():
    """Commas, dots, mixed case all normalized."""
    s = _holder_match_score("Smith, John P.", "SMITH JOHN P")
    assert s == 1.0, s
    print("PASS: test_punctuation_and_case_ignored")


def test_single_token_holder_matches_surname_only():
    """Holder of 1 token (rare — entity name like 'JONES') matches any row
    containing that token."""
    s = _holder_match_score("JONES", "JONES JOHN MARK")
    assert s == 1.0, s
    print("PASS: test_single_token_holder_matches_surname_only")


def test_joint_owner_holder_still_works():
    """A joint-owner holder string still matches a joint PVA parcel.
    Pattern in production: HOLDER 'HOLDER CORBIN JACK', PVA row 'HOLDER
    CORBIN JACK & BOOTH MERIDETH LOUISE' — every holder token present."""
    s = _holder_match_score(
        "HOLDER CORBIN JACK",
        "HOLDER CORBIN JACK & BOOTH MERIDETH LOUISE",
    )
    assert s == 1.0, s
    print("PASS: test_joint_owner_holder_still_works")


def test_marshall_othello_uncommon_first_name():
    """Uncommon first name pattern — 70 PVA parcels for MARSHALL surname,
    only one likely contains 'OTHELLO'. The exact token match should
    deliver a clear winner."""
    # Top candidate (the right one):
    s_correct = _holder_match_score("MARSHALL OTHELLO", "MARSHALL OTHELLO")
    # Wrong candidates (same surname, different first):
    s_wrong = _holder_match_score("MARSHALL OTHELLO", "MARSHALL MICHAEL")
    assert s_correct == 1.0, s_correct
    assert s_wrong == 0.5, s_wrong
    assert s_correct - s_wrong == 0.5, "expected clean 0.5 margin"
    print("PASS: test_marshall_othello_uncommon_first_name")


# ── Disambiguation contract: the existing margin still gates marginal picks ─
def test_disambig_contract_blevins_passes_with_boost():
    """End-to-end: with the boost, BLEVINS-pattern disambiguation now has
    a clean margin. The 3 candidates for 'BLEVINS WILLIAM' score:
      P → 1.0,  A → 0.67,  E → 0.67
    Margin top - second = 0.33, comfortably above the 0.20 floor.

    Without the boost, all three would have tied at 0.67 → declined."""
    top = _holder_match_score("BLEVINS, WILLIAM PATRICK", "BLEVINS WILLIAM P")
    second = _holder_match_score("BLEVINS, WILLIAM PATRICK", "BLEVINS WILLIAM A")
    third = _holder_match_score("BLEVINS, WILLIAM PATRICK", "BLEVINS WILLIAM E")
    assert top == 1.0
    assert second < 1.0 and third < 1.0
    margin = top - max(second, third)
    assert margin >= 0.20, f"margin={margin} below 0.20 floor"
    print("PASS: test_disambig_contract_blevins_passes_with_boost")


if __name__ == "__main__":
    test_blevins_william_patrick_vs_william_p_scores_one()
    test_blevins_william_patrick_vs_william_a_no_boost()
    test_blevins_no_middle_no_boost()
    test_bruce_judith_anne_vs_judith_a_scores_one()
    test_fernkas_linda_adell_vs_linda_a_scores_one()
    test_bruce_a_does_NOT_match_judith_anne()
    test_two_initials_consume_separate_names()
    test_initial_only_credits_first_match()
    test_empty_holder_returns_zero()
    test_empty_row_returns_zero()
    test_no_overlap_returns_zero()
    test_exact_match_returns_one()
    test_extra_row_tokens_dont_lower_score()
    test_punctuation_and_case_ignored()
    test_single_token_holder_matches_surname_only()
    test_joint_owner_holder_still_works()
    test_marshall_othello_uncommon_first_name()
    test_disambig_contract_blevins_passes_with_boost()
    print("\nALL PASS: holder_match_score")
