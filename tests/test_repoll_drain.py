"""Standalone, network-free tests for the re-poll DRAIN side (Phase 6 / COVER-01, plan 06-03b).

Run: .venv/Scripts/python.exe tests/test_repoll_drain.py

Covers scraper.drain_repoll_queue — the START-of-daily-run hook that re-searches every
due re-poll entry through the SAME enrich_case_parties path used for fresh cases:
  * a due entry whose re-search now resolves (a HIT) is removed from the queue and
    returned (with repoll_attempts stamped from the entry) so scrape_all can merge it.
  * a due entry that re-searches still-empty (a MISS) is bumped (attempts++, repoll_after
    pushed forward) and left in the queue.
  * a due entry already at the max-attempts edge that re-searches empty is DROPPED.
  * a not-yet-due (future) entry is left untouched (never re-searched).

All network/browser seams are monkeypatched: kcoj_case_detail.enrich_case_parties is
replaced with a fake that either populates the passed notice (HIT) or leaves it empty
(MISS); the queue is a plain dict; config.KCOJ_REPOLL_FILE is redirected to a tempfile.
Mirrors the repo's standalone-test convention (bare functions + assert + print PASS).
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
sys.path.insert(0, _SRC)

import config  # noqa: E402

# Redirect the queue's state file to a throwaway tempfile (network-free; never
# touches the real kcoj_repoll_queue.json). The store reads config.* at call time.
config.KCOJ_REPOLL_FILE = Path(tempfile.mkdtemp(prefix="repoll_drain_test_")) / "q.json"

import kcoj_case_detail  # noqa: E402
import kcoj_repoll_queue as q  # noqa: E402
import scraper  # noqa: E402
from config import REPOLL_MAX_ATTEMPTS  # noqa: E402


def _patch_enrich(hit: bool):
    """Replace kcoj_case_detail.enrich_case_parties with a network-free fake.

    drain_repoll_queue does a lazy ``from kcoj_case_detail import enrich_case_parties``,
    so patching the attribute on the module is sufficient. On a HIT the fake fills the
    passed notice's owner_name + courtnet_party_types (what apply_parties_to_notice would
    do); on a MISS it leaves the notice empty (a fresh / still-unindexed case).
    """

    async def _fake_enrich(notices, repoll_queue=None, **kwargs):
        # The drain MUST pass repoll_queue=None so the inner re-search does not
        # re-enqueue mid-drain — assert that contract here.
        assert repoll_queue is None, "drain must call enrich_case_parties with repoll_queue=None"
        if hit:
            for n in notices:
                n.owner_name = "DOE JANE"
                n.courtnet_party_types = "P|EE"

    kcoj_case_detail.enrich_case_parties = _fake_enrich


def test_drain_hit_removes_and_returns():
    """A due entry whose re-search now resolves -> returned + removed from queue."""
    _patch_enrich(hit=True)
    queue = {
        "26-P-009101": {"repoll_after": "2026-01-01", "attempts": 1, "reason": "courtnet_0_parties"},
    }
    refound = asyncio.run(scraper.drain_repoll_queue(queue))
    assert len(refound) == 1, f"expected 1 re-found notice, got {len(refound)}"
    n = refound[0]
    assert n.case_number == "26-P-009101", f"reconstructed case_number wrong: {n.case_number!r}"
    assert n.owner_name.strip(), "HIT notice must have owner_name populated"
    assert getattr(n, "repoll_attempts", "") == "1", (
        f"repoll_attempts must be stamped from the entry, got {getattr(n, 'repoll_attempts', None)!r}"
    )
    assert "26-P-009101" not in queue, "a HIT must be removed from the queue"
    print("PASS: test_drain_hit_removes_and_returns")


def test_drain_miss_bumps():
    """A due entry that re-searches empty (under max) -> bumped, stays in queue."""
    _patch_enrich(hit=False)
    queue = {
        "26-P-009102": {"repoll_after": "2026-01-01", "attempts": 0, "reason": "courtnet_0_parties"},
    }
    refound = asyncio.run(scraper.drain_repoll_queue(queue))
    assert refound == [], f"a MISS must return nothing, got {refound}"
    assert "26-P-009102" in queue, "a MISS under max attempts must stay queued"
    assert queue["26-P-009102"]["attempts"] == 1, (
        f"a MISS must increment attempts, got {queue['26-P-009102']}"
    )
    assert queue["26-P-009102"]["repoll_after"] > "2026-01-01", "repoll_after must be bumped forward"
    print("PASS: test_drain_miss_bumps")


def test_drain_miss_drops_at_max():
    """A due entry one bump short of max that re-searches empty -> DROPPED."""
    _patch_enrich(hit=False)
    # attempts = max-1 so the drain's bump reaches max_attempts -> dropped.
    queue = {
        "26-P-009103": {
            "repoll_after": "2026-01-01",
            "attempts": REPOLL_MAX_ATTEMPTS - 1,
            "reason": "courtnet_0_parties",
        },
    }
    refound = asyncio.run(scraper.drain_repoll_queue(queue))
    assert refound == [], f"a MISS must return nothing, got {refound}"
    assert "26-P-009103" not in queue, "an exhausted entry must be dropped from the queue"
    print("PASS: test_drain_miss_drops_at_max")


def test_drain_future_entry_skipped():
    """A not-yet-due (future repoll_after) entry is never re-searched / touched."""
    # If a future entry were re-searched, this fake would raise (asserts repoll_queue
    # is None is fine, but more importantly the entry must stay byte-identical).
    _patch_enrich(hit=True)
    queue = {
        "26-P-009104": {"repoll_after": "2999-12-31", "attempts": 0, "reason": "courtnet_0_parties"},
    }
    before = dict(queue["26-P-009104"])
    refound = asyncio.run(scraper.drain_repoll_queue(queue))
    assert refound == [], "a future entry must not be re-found"
    assert "26-P-009104" in queue, "a future entry must stay queued"
    assert queue["26-P-009104"] == before, "a future entry must be left untouched"
    print("PASS: test_drain_future_entry_skipped")


if __name__ == "__main__":
    test_drain_hit_removes_and_returns()
    test_drain_miss_bumps()
    test_drain_miss_drops_at_max()
    test_drain_future_entry_skipped()
    print("\nALL PASS: test_repoll_drain")
