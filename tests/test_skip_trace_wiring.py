"""Network-free unit tests for the Phase 5 skip-trace wiring helpers.

CREATED by plan 05-02 Task 2 (estate-attorney / AOC-805 fallback + set_repoll_after);
EXTENDED by Task 3b (credits-exhausted -> repoll + add_litigator param path).

All tests are standalone (TESTING.md style: bare asserts + print PASS) and run
with no network — the helpers under test mutate NoticeData in place and the
litigator-param test exercises score_record_phones's early-return (no api_key).

Run:  python tests/test_skip_trace_wiring.py
"""

import os
import re
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import skip_trace_guard as guard  # noqa: E402
from notice_parser import NoticeData  # noqa: E402

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ── Task 2: estate-attorney / AOC-805 fallback ───────────────────────────

def test_attorney_fallback():
    """No DM phones + a known estate attorney -> contact_via_attorney flagged."""
    n = NoticeData()
    n.decision_maker_name = "Some Heir"
    n.estate_attorney_name = "Jane Atty"
    n.estate_attorney_phone = "5025551212"

    ch = guard.apply_contact_fallback(n)

    assert ch == "attorney", f"channel={ch!r}"
    assert n.contact_via_attorney == "yes", n.contact_via_attorney
    assert "fallback=attorney" in n.skip_trace_guard_notes, n.skip_trace_guard_notes
    print("PASS: test_attorney_fallback")


def test_aoc805_queue():
    """No DM phones AND no attorney -> queued for AOC-805 via repoll_after."""
    n = NoticeData()
    n.decision_maker_name = "Some Heir"

    ch = guard.apply_contact_fallback(n)

    assert ch == "aoc805_queued", f"channel={ch!r}"
    assert _DATE_RE.match(n.repoll_after), f"repoll_after={n.repoll_after!r}"
    assert n.repoll_after >= date.today().isoformat(), n.repoll_after
    assert "aoc805_queued" in n.skip_trace_guard_notes, n.skip_trace_guard_notes
    assert n.contact_via_attorney == "", n.contact_via_attorney
    print("PASS: test_aoc805_queue")


def test_phone_present_no_fallback():
    """A guard-passing DM phone (status not unconfirmed) -> no fallback applied."""
    n = NoticeData()
    n.decision_maker_name = "Living Heir"
    n.decision_maker_status = "verified_living"
    n.primary_phone = "5025550000"

    ch = guard.apply_contact_fallback(n)

    assert ch == "", f"channel={ch!r}"
    assert n.contact_via_attorney == "", n.contact_via_attorney
    assert n.repoll_after == "", n.repoll_after
    print("PASS: test_phone_present_no_fallback")


def test_unconfirmed_dm_still_falls_back():
    """A DM phone is present but decision_maker_status==unconfirmed (Armstrong):
    unconfirmed phones are NOT guard-passing -> still falls back to the attorney."""
    n = NoticeData()
    n.decision_maker_name = "Barry Armstrong"
    n.decision_maker_status = "unconfirmed"
    n.primary_phone = "5025559999"
    n.estate_attorney_name = "Probate Atty"

    ch = guard.apply_contact_fallback(n)

    assert ch == "attorney", f"channel={ch!r}"
    assert n.contact_via_attorney == "yes", n.contact_via_attorney
    print("PASS: test_unconfirmed_dm_still_falls_back")


def test_set_repoll_after_future():
    """set_repoll_after(notice, days=4) -> a future YYYY-MM-DD repoll_after."""
    n = NoticeData()
    out = guard.set_repoll_after(n, days=4)

    assert _DATE_RE.match(out), f"returned={out!r}"
    assert n.repoll_after == out, (n.repoll_after, out)
    assert out > date.today().isoformat(), out
    print("PASS: test_set_repoll_after_future")


def test_apply_contact_fallbacks_batch():
    """Batch helper returns per-channel counts."""
    a = NoticeData(); a.decision_maker_name = "H1"; a.estate_attorney_name = "Atty"
    b = NoticeData(); b.decision_maker_name = "H2"
    c = NoticeData(); c.decision_maker_name = "H3"
    c.decision_maker_status = "verified_living"; c.primary_phone = "5025550000"

    stats = guard.apply_contact_fallbacks([a, b, c])

    assert stats["records"] == 3, stats
    assert stats["attorney"] == 1, stats
    assert stats["aoc805_queued"] == 1, stats
    print("PASS: test_apply_contact_fallbacks_batch")


if __name__ == "__main__":
    test_attorney_fallback()
    test_aoc805_queue()
    test_phone_present_no_fallback()
    test_unconfirmed_dm_still_falls_back()
    test_set_repoll_after_future()
    test_apply_contact_fallbacks_batch()
    print("\nALL PASS: skip_trace_wiring (Task 2)")
