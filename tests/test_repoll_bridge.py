"""Standalone, network-free tests for the Phase 5->Phase 6 BRIDGE (Phase 6 / COVER-01, plan 06-03b).

Run: .venv/Scripts/python.exe tests/test_repoll_bridge.py

BLOCKER-2 acceptance: Phase 5's 2g-6 (handle_credits_exhausted) + AOC-805 fallback set
``notice.repoll_after`` on a FIELD, but nothing copied those notices INTO the
``kcoj_repoll_queue`` DICT that the drain (Task 1) reads. The main.py bridge closes that
gap: after the skip-trace block, every traced notice with a non-empty ``repoll_after`` is
enqueued into kcoj_repoll_queue, so the NEXT run's drain re-searches it.

This test replicates the EXACT inline enqueue-loop that main.py runs (kept inline per the
plan's SCOPE note — no helper in kcoj_repoll_queue.py) against the real queue store, so it
exercises the production behavior network-free. It needs no main.py import.

Covers:
  * a notice with repoll_after set (as Phase 5 leaves it) + a case_number -> appears in the
    queue -> round-trips through save/load -> is returned by due_entries (DRAINABLE).
  * a notice with repoll_after="" is NOT enqueued (no false enqueues).
  * a notice already in the queue at attempts=2 is NOT reset by the bridge (idempotent).

config.KCOJ_REPOLL_FILE is redirected to a tempfile (never touches real state).
"""

import os
import sys
import tempfile
from pathlib import Path

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
sys.path.insert(0, _SRC)

import config  # noqa: E402

config.KCOJ_REPOLL_FILE = Path(tempfile.mkdtemp(prefix="repoll_bridge_test_")) / "q.json"

import kcoj_repoll_queue as q  # noqa: E402
from notice_parser import NoticeData  # noqa: E402


def _fresh_file():
    config.KCOJ_REPOLL_FILE = Path(tempfile.mkdtemp(prefix="repoll_bridge_test_")) / "q.json"


def _run_bridge(notices, queue):
    """Replicate main.py's INLINE Phase 5->6 bridge loop (both Apify + CLI blocks run this).

    Kept byte-identical to main.py so this test exercises the real bridge behavior.
    """
    from kcoj_repoll_queue import enqueue_repoll, make_key
    bridged = 0
    for n in notices:
        if getattr(n, "repoll_after", "").strip():
            k = make_key(n)
            if k:
                enqueue_repoll(queue, k, reason="credits_exhausted")
                bridged += 1
    return bridged


def test_repoll_after_notice_bridged_into_queue():
    """A Phase-5-marked notice (repoll_after set) becomes a DRAINABLE queue entry."""
    _fresh_file()
    notice = NoticeData(
        notice_type="probate", county="Jefferson", state="KY",
        case_number="26-P-008001", decedent_name="BRIDGED DECEDENT",
    )
    # Phase 5's set_repoll_after leaves a future YYYY-MM-DD on the FIELD.
    notice.repoll_after = "2026-01-01"

    queue: dict = {}
    bridged = _run_bridge([notice], queue)
    assert bridged == 1, f"expected 1 bridged notice, got {bridged}"

    key = q.make_key(notice)
    assert key == "26-P-008001", f"unexpected key: {key!r}"
    assert key in queue, f"a repoll_after notice must be enqueued; queue={queue}"
    assert queue[key]["attempts"] == 0
    assert queue[key]["reason"] == "credits_exhausted", f"unexpected reason: {queue[key]}"

    # Round-trips through persistence (the bridge persists; next run reloads).
    q.save_repoll_queue(queue)
    reloaded = q.load_repoll_queue()
    assert reloaded == queue, f"round-trip mismatch: {reloaded} != {queue}"

    # ...and is DUE (drainable) once its repoll_after date arrives. The bridge
    # enqueues with a future business-day offset (REPOLL_DELAY_BUSINESS_DAYS from
    # today), so it is NOT yet due, but IS due on/after its scheduled date.
    scheduled = reloaded[key]["repoll_after"]
    assert key not in q.due_entries(reloaded, today="2000-01-01"), (
        "a freshly bridged notice must not be due before its repoll_after"
    )
    due = q.due_entries(reloaded, today=scheduled)
    assert key in due, f"a bridged notice must become drainable on/after {scheduled}; due={due}"
    print("PASS: test_repoll_after_notice_bridged_into_queue")


def test_no_repoll_after_not_bridged():
    """A notice without repoll_after is NOT enqueued (no false enqueues)."""
    _fresh_file()
    notice = NoticeData(
        notice_type="probate", county="Jefferson", state="KY",
        case_number="26-P-008002", decedent_name="NOTRACE DECEDENT",
    )
    assert getattr(notice, "repoll_after", "") == "", "default repoll_after should be empty"
    queue: dict = {}
    bridged = _run_bridge([notice], queue)
    assert bridged == 0, f"a notice without repoll_after must not bridge, got {bridged}"
    assert queue == {}, f"queue must stay empty; queue={queue}"
    print("PASS: test_no_repoll_after_not_bridged")


def test_bridge_idempotent():
    """A notice whose key is already queued at attempts=2 is NOT reset by the bridge."""
    _fresh_file()
    notice = NoticeData(
        notice_type="probate", county="Jefferson", state="KY",
        case_number="26-P-008003", decedent_name="EXISTING DECEDENT",
    )
    notice.repoll_after = "2026-01-01"
    key = q.make_key(notice)
    # Pre-seed as if a prior bump raised attempts to 2.
    queue = {key: {"repoll_after": "2026-12-31", "attempts": 2, "reason": "prior"}}
    bridged = _run_bridge([notice], queue)
    # The bridge still "saw" it (count includes the attempt), but enqueue_repoll is
    # idempotent on an existing key — attempts/date must be untouched.
    assert bridged == 1, f"bridge loop counts the candidate, got {bridged}"
    assert queue[key]["attempts"] == 2, f"bridge must NOT reset attempts; got {queue[key]}"
    assert queue[key]["repoll_after"] == "2026-12-31", "bridge must NOT change the date"
    print("PASS: test_bridge_idempotent")


if __name__ == "__main__":
    test_repoll_after_notice_bridged_into_queue()
    test_no_repoll_after_not_bridged()
    test_bridge_idempotent()
    print("\nALL PASS: test_repoll_bridge")
