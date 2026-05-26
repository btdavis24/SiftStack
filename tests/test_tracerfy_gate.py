"""Network-free tests for main.is_tracerfy_eligible — the two-gate predicate
that decides which NoticeData records get sent to paid Tracerfy.

Regression context: the 2026-05-26 KY-only Apify run produced 14 records (4
probate + 10 lis_pendens) but only the 4 probate records went through Tracerfy.
LP records were silently excluded because the original gate's secondary clause
required deceased/heir/DM. Fix B widened the gate to also accept lis_pendens
records that have an owner_name + address. These tests pin that widening.

Run:  python tests/test_tracerfy_gate.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from main import is_tracerfy_eligible  # noqa: E402
from notice_parser import NoticeData  # noqa: E402


MIN_FIT = 40  # mirrors config.SKIP_TRACE_MIN_FIT default


def _notice(**kw) -> NoticeData:
    n = NoticeData()
    for k, v in kw.items():
        setattr(n, k, v)
    return n


# ── Probate happy path (pre-existing — must still pass) ───────────────────
def test_probate_deceased_passes():
    """Deceased owner + fit score above threshold -> eligible (DP path)."""
    n = _notice(
        notice_type="probate",
        owner_deceased="yes",
        decision_maker_name="Jane Heir",
        address="123 Main St",
        wholesale_fit_score="65",
    )
    assert is_tracerfy_eligible(n, MIN_FIT) is True
    print("PASS: test_probate_deceased_passes")


def test_probate_with_heir_map_passes():
    """heir_map_json alone (without dm_name) satisfies the secondary gate."""
    n = _notice(
        notice_type="probate",
        heir_map_json='[{"name": "Heir A", "signing_authority": true}]',
        wholesale_fit_score="55",
    )
    assert is_tracerfy_eligible(n, MIN_FIT) is True
    print("PASS: test_probate_with_heir_map_passes")


def test_probate_with_dm_only_passes():
    """decision_maker_name alone satisfies the secondary gate."""
    n = _notice(
        notice_type="probate",
        decision_maker_name="John Executor",
        wholesale_fit_score="50",
    )
    assert is_tracerfy_eligible(n, MIN_FIT) is True
    print("PASS: test_probate_with_dm_only_passes")


# ── Lis pendens widening (Fix B) ──────────────────────────────────────────
def test_lis_pendens_with_owner_and_address_passes():
    """LP record with owner_name + address must pass — this is the bug fix.
    Pre-Fix-B, these were silently excluded because they have no DM/heir.
    """
    n = _notice(
        notice_type="lis_pendens",
        owner_name="CASEY CAYLA",
        address="802 W Ashland Ave",
        city="Louisville",
        state="KY",
        wholesale_fit_score="50",
    )
    assert is_tracerfy_eligible(n, MIN_FIT) is True
    print("PASS: test_lis_pendens_with_owner_and_address_passes")


def test_lis_pendens_without_owner_excluded():
    """LP record missing owner_name -> excluded (Tracerfy needs a name)."""
    n = _notice(
        notice_type="lis_pendens",
        owner_name="",
        address="123 Some St",
        wholesale_fit_score="60",
    )
    assert is_tracerfy_eligible(n, MIN_FIT) is False
    print("PASS: test_lis_pendens_without_owner_excluded")


def test_lis_pendens_without_address_excluded():
    """LP record with owner_name but no address -> excluded (Tracerfy needs
    a current-address hint; without it the match rate collapses)."""
    n = _notice(
        notice_type="lis_pendens",
        owner_name="DOE JOHN",
        address="",
        wholesale_fit_score="60",
    )
    assert is_tracerfy_eligible(n, MIN_FIT) is False
    print("PASS: test_lis_pendens_without_address_excluded")


def test_lis_pendens_low_fit_excluded():
    """Fit gate still applies to LP — low-score records don't burn credits."""
    n = _notice(
        notice_type="lis_pendens",
        owner_name="OWNER NAME",
        address="123 St",
        wholesale_fit_score="30",  # below MIN_FIT=40
    )
    assert is_tracerfy_eligible(n, MIN_FIT) is False
    print("PASS: test_lis_pendens_low_fit_excluded")


# ── Negative cases (must remain excluded) ─────────────────────────────────
def test_foreclosure_living_owner_excluded():
    """Non-LP record with living owner and no DM data — still excluded.
    Confirms Fix B didn't accidentally widen beyond lis_pendens."""
    n = _notice(
        notice_type="foreclosure",
        owner_name="LIVING OWNER",
        address="500 Some St",
        wholesale_fit_score="80",  # high fit, but no DP/LP eligibility
    )
    assert is_tracerfy_eligible(n, MIN_FIT) is False
    print("PASS: test_foreclosure_living_owner_excluded")


def test_blank_fit_score_excluded():
    """Blank wholesale_fit_score parses as 0 -> below threshold -> excluded
    (fails closed; matches the inline gate's original `or 0` behavior)."""
    n = _notice(
        notice_type="probate",
        owner_deceased="yes",
        decision_maker_name="Jane Heir",
        wholesale_fit_score="",  # unscored
    )
    assert is_tracerfy_eligible(n, MIN_FIT) is False
    print("PASS: test_blank_fit_score_excluded")


def test_garbage_fit_score_excluded():
    """Non-numeric wholesale_fit_score -> fails closed (no crash)."""
    n = _notice(
        notice_type="probate",
        owner_deceased="yes",
        decision_maker_name="Jane Heir",
        wholesale_fit_score="N/A",
    )
    assert is_tracerfy_eligible(n, MIN_FIT) is False
    print("PASS: test_garbage_fit_score_excluded")


def test_exact_threshold_passes():
    """Score == min_fit must pass (not strictly greater)."""
    n = _notice(
        notice_type="probate",
        decision_maker_name="DM",
        wholesale_fit_score=str(MIN_FIT),
    )
    assert is_tracerfy_eligible(n, MIN_FIT) is True
    print("PASS: test_exact_threshold_passes")


if __name__ == "__main__":
    test_probate_deceased_passes()
    test_probate_with_heir_map_passes()
    test_probate_with_dm_only_passes()
    test_lis_pendens_with_owner_and_address_passes()
    test_lis_pendens_without_owner_excluded()
    test_lis_pendens_without_address_excluded()
    test_lis_pendens_low_fit_excluded()
    test_foreclosure_living_owner_excluded()
    test_blank_fit_score_excluded()
    test_garbage_fit_score_excluded()
    test_exact_threshold_passes()
    print("\nALL PASS: tracerfy_gate")
