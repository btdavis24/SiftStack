"""Network-free tests for kcoj_case_detail.enrich_case_parties_sync.

Regression context: the 2026-05-26+ Apify runs surfaced
``[CourtNet] pipeline already in an event loop — scheduling is caller's
responsibility; skipping`` — Actor.main is async, so the pipeline's
``asyncio.run()`` couldn't fire and CourtNet silently no-op'd, leaving every
probate record with no DM / attorney / party graph. The sync wrapper
detects the context and dispatches: asyncio.run() when no loop is active,
worker-thread + fresh loop when one is.

These tests pin the wrapper's contract by monkey-patching the async function
``enrich_case_parties`` with a fast stub — no Playwright, no CourtNet, no
2Captcha network calls.

Run:  python tests/test_kcoj_async_bridge.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import kcoj_case_detail  # noqa: E402
from notice_parser import NoticeData  # noqa: E402


def _make_notice(case_number: str = "26-P-001234") -> NoticeData:
    n = NoticeData()
    n.notice_type = "probate"
    n.county = "Jefferson"
    n.case_number = case_number
    return n


# ── No running loop (CLI path) ────────────────────────────────────────────
def test_no_loop_runs_coroutine():
    """When called outside an event loop, the wrapper uses asyncio.run()
    and the coroutine mutates the input notices."""
    calls = []

    async def fake_enrich(notices, repoll_queue=None):
        calls.append(("called", len(notices), repoll_queue))
        for n in notices:
            n.owner_name = "Test PR"

    original = kcoj_case_detail.enrich_case_parties
    try:
        kcoj_case_detail.enrich_case_parties = fake_enrich
        notices = [_make_notice()]
        kcoj_case_detail.enrich_case_parties_sync(notices)
        assert calls == [("called", 1, None)], calls
        assert notices[0].owner_name == "Test PR", notices[0].owner_name
    finally:
        kcoj_case_detail.enrich_case_parties = original
    print("PASS: test_no_loop_runs_coroutine")


def test_no_loop_propagates_exception():
    """Exceptions from the coroutine must surface to the caller, not vanish."""
    class BoomError(Exception):
        pass

    async def fake_enrich(notices, repoll_queue=None):
        raise BoomError("simulated CourtNet failure")

    original = kcoj_case_detail.enrich_case_parties
    try:
        kcoj_case_detail.enrich_case_parties = fake_enrich
        caught = False
        try:
            kcoj_case_detail.enrich_case_parties_sync([_make_notice()])
        except BoomError:
            caught = True
        assert caught, "expected BoomError to propagate"
    finally:
        kcoj_case_detail.enrich_case_parties = original
    print("PASS: test_no_loop_propagates_exception")


# ── Inside a running loop (Apify Actor path) — the bug fix proper ─────────
def test_inside_loop_uses_thread():
    """When the caller is inside a running event loop (mirrors Actor.main),
    the wrapper must NOT skip — it must run the coroutine in a worker thread
    on its own loop. Before this fix, the Apify path silently no-op'd."""
    calls = []

    async def fake_enrich(notices, repoll_queue=None):
        calls.append(("called", len(notices), repoll_queue))
        for n in notices:
            n.owner_name = "Test PR (threaded)"

    async def driver():
        # The outer event loop is now active — same shape as Actor.main.
        notices = [_make_notice()]
        kcoj_case_detail.enrich_case_parties_sync(notices)
        return notices

    original = kcoj_case_detail.enrich_case_parties
    try:
        kcoj_case_detail.enrich_case_parties = fake_enrich
        notices = asyncio.run(driver())
        assert calls == [("called", 1, None)], calls
        assert notices[0].owner_name == "Test PR (threaded)", notices[0].owner_name
    finally:
        kcoj_case_detail.enrich_case_parties = original
    print("PASS: test_inside_loop_uses_thread")


def test_inside_loop_propagates_exception():
    """Exceptions raised inside the worker thread must re-raise on the caller,
    not get swallowed by the thread boundary."""
    class BoomError(Exception):
        pass

    async def fake_enrich(notices, repoll_queue=None):
        raise BoomError("simulated CourtNet failure in worker thread")

    async def driver():
        try:
            kcoj_case_detail.enrich_case_parties_sync([_make_notice()])
        except BoomError as e:
            return f"caught: {e}"
        return "no exception"

    original = kcoj_case_detail.enrich_case_parties
    try:
        kcoj_case_detail.enrich_case_parties = fake_enrich
        result = asyncio.run(driver())
        assert "caught" in result, result
    finally:
        kcoj_case_detail.enrich_case_parties = original
    print("PASS: test_inside_loop_propagates_exception")


# ── Argument forwarding ───────────────────────────────────────────────────
def test_repoll_queue_forwarded():
    """The optional repoll_queue arg must reach the async function unchanged
    (used by Phase 6 / COVER-01 for 0-party re-poll)."""
    seen = {"queue": None}

    async def fake_enrich(notices, repoll_queue=None):
        seen["queue"] = repoll_queue

    queue = {"existing": "data"}
    original = kcoj_case_detail.enrich_case_parties
    try:
        kcoj_case_detail.enrich_case_parties = fake_enrich
        kcoj_case_detail.enrich_case_parties_sync(
            [_make_notice()], repoll_queue=queue,
        )
        assert seen["queue"] is queue, seen
    finally:
        kcoj_case_detail.enrich_case_parties = original
    print("PASS: test_repoll_queue_forwarded")


def test_repoll_queue_forwarded_inside_loop():
    """Same forwarding guarantee through the worker-thread path."""
    seen = {"queue": None}

    async def fake_enrich(notices, repoll_queue=None):
        seen["queue"] = repoll_queue

    queue = {"existing": "data"}

    async def driver():
        kcoj_case_detail.enrich_case_parties_sync(
            [_make_notice()], repoll_queue=queue,
        )

    original = kcoj_case_detail.enrich_case_parties
    try:
        kcoj_case_detail.enrich_case_parties = fake_enrich
        asyncio.run(driver())
        assert seen["queue"] is queue, seen
    finally:
        kcoj_case_detail.enrich_case_parties = original
    print("PASS: test_repoll_queue_forwarded_inside_loop")


if __name__ == "__main__":
    test_no_loop_runs_coroutine()
    test_no_loop_propagates_exception()
    test_inside_loop_uses_thread()
    test_inside_loop_propagates_exception()
    test_repoll_queue_forwarded()
    test_repoll_queue_forwarded_inside_loop()
    print("\nALL PASS: kcoj_async_bridge")
