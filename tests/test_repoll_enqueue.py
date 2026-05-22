"""Standalone, network-free tests for the re-poll ENQUEUE side (Phase 6 / COVER-01, plan 06-03a).

Run: .venv/Scripts/python.exe tests/test_repoll_enqueue.py

Covers the two enqueue trigger points wired in this plan:
  * kcoj_case_detail.enrich_case_parties — a 0-party CourtNet result enqueues the case
    for re-poll (when a queue is passed); passing no queue is a no-op (backward compatible).
  * obituary_enricher.enrich_obituary_data — a just-filed decedent whose obituary search
    returns nothing enqueues that decedent for re-poll.

All network/browser seams are monkeypatched: CourtNet's Playwright + search_case are
replaced with fakes, the obituary search is stubbed to return no results, and the queue
is a plain dict. Mirrors the repo's standalone-test convention (bare functions + assert +
print PASS, no pytest, no network).
"""

import asyncio
import os
import sys

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
sys.path.insert(0, _SRC)

import kcoj_case_detail  # noqa: E402
import kcoj_repoll_queue as q  # noqa: E402
import obituary_enricher  # noqa: E402
from notice_parser import NoticeData  # noqa: E402


# ── Fake async-Playwright machinery so enrich_case_parties never launches a real
#    browser or touches the network. enrich_case_parties does a lazy
#    `from playwright.async_api import async_playwright`, so we patch the symbol on
#    the playwright module that the import resolves to.
class _FakePage:
    def __init__(self):
        # Make the mid-batch session-check (`"CourtNet" not in page.url`) pass so the
        # loop reaches search_case without trying to re-authenticate.
        self.url = "https://kcoj.kycourts.net/CourtNet/Search/Index"


class _FakeCtx:
    async def new_page(self):
        return _FakePage()

    async def close(self):
        return None


class _FakeBrowser:
    async def new_context(self, **kwargs):
        return _FakeCtx()

    async def close(self):
        return None


class _FakeChromium:
    async def launch(self, **kwargs):
        return _FakeBrowser()


class _FakePW:
    chromium = _FakeChromium()


class _FakeAsyncPlaywright:
    async def __aenter__(self):
        return _FakePW()

    async def __aexit__(self, *exc):
        return False


def _fake_async_playwright():
    return _FakeAsyncPlaywright()


def _patch_courtnet(monkey_search_returns):
    """Patch the CourtNet seams: fake Playwright, guest login, and search_case.

    Returns nothing; mutates kcoj_case_detail + the playwright module in place.
    Callers run within a single test and don't restore (the process is short-lived).
    """
    import playwright.async_api as pw_api

    pw_api.async_playwright = _fake_async_playwright

    async def _fake_login_as_guest(page):
        return True

    async def _fake_search_case(page, case_number):
        return list(monkey_search_returns)

    kcoj_case_detail.login_as_guest = _fake_login_as_guest
    kcoj_case_detail.search_case = _fake_search_case
    # No real polite-sleep between cases.
    kcoj_case_detail.COURTNET_DELAY_MIN = 0
    kcoj_case_detail.COURTNET_DELAY_MAX = 0


def test_courtnet_0_parties_enqueues():
    """A docket-known case that returns 0 CourtNet parties lands in the queue."""
    _patch_courtnet([])  # search_case -> [] (fresh / unindexed case)
    notice = NoticeData(
        notice_type="probate",
        county="Jefferson",
        case_number="26-P-009001",
        decedent_name="TESTCASE ZERO",
    )
    queue: dict = {}
    asyncio.run(kcoj_case_detail.enrich_case_parties([notice], repoll_queue=queue))

    key = q.make_key(notice)
    assert key == "26-P-009001", f"expected case_number key, got {key!r}"
    assert key in queue, f"0-party case must be enqueued; queue={queue}"
    entry = queue[key]
    assert entry["attempts"] == 0, f"new entry attempts should be 0, got {entry}"
    today = obituary_enricher.datetime.now().strftime("%Y-%m-%d")
    assert entry["repoll_after"] > today, f"repoll_after should be future, got {entry}"
    assert entry["reason"] == "courtnet_0_parties", f"unexpected reason: {entry}"
    print("PASS: test_courtnet_0_parties_enqueues")


def test_courtnet_no_queue_noop():
    """No queue passed -> no enqueue, no crash (backward compatible)."""
    _patch_courtnet([])
    notice = NoticeData(
        notice_type="probate",
        county="Jefferson",
        case_number="26-P-009002",
        decedent_name="TESTCASE NOQUEUE",
    )
    # Default repoll_queue=None — must not raise and must not enqueue anywhere.
    asyncio.run(kcoj_case_detail.enrich_case_parties([notice]))
    print("PASS: test_courtnet_no_queue_noop")


def test_courtnet_blank_case_not_enqueued():
    """Guard: a candidate with no case_number is never a candidate, so nothing enqueues."""
    _patch_courtnet([])
    notice = NoticeData(
        notice_type="probate",
        county="Jefferson",
        case_number="   ",  # blank -> not a candidate, no enqueue
        decedent_name="TESTCASE BLANK",
    )
    queue: dict = {}
    asyncio.run(kcoj_case_detail.enrich_case_parties([notice], repoll_queue=queue))
    assert queue == {}, f"blank-case-number must not enqueue; queue={queue}"
    print("PASS: test_courtnet_blank_case_not_enqueued")


def _patch_obit_no_results():
    """Stub the obituary search/LLM seams so Phase A finds no obituary, network-free."""
    obituary_enricher._search_obituary = lambda *a, **k: []
    # Belt-and-suspenders: if any path tries to fetch/parse, return nothing.
    obituary_enricher._fetch_page_text = lambda *a, **k: ""
    obituary_enricher._parse_obituary_with_llm = lambda *a, **k: None


def test_obit_empty_enqueues():
    """A just-filed decedent with no obituary found is enqueued for re-poll."""
    _patch_obit_no_results()
    today = obituary_enricher.datetime.now().strftime("%Y-%m-%d")
    notice = NoticeData(
        notice_type="probate",
        county="Jefferson",
        state="KY",
        city="Louisville",
        decedent_name="NOOBIT FRESHFILING",
        case_number="26-P-009003",
        date_added=today,  # fresh filing -> plausibly just-not-posted-yet
    )
    queue: dict = {}
    obituary_enricher.enrich_obituary_data(
        [notice],
        api_key="x",
        skip_heir_verification=True,
        skip_dm_address=True,
        skip_ancestry=True,
        repoll_queue=queue,
    )
    key = q.make_key(notice)
    assert key in queue, f"empty-obit fresh decedent must be enqueued; queue={queue}"
    assert queue[key]["reason"] == "obituary_empty", f"unexpected reason: {queue[key]}"
    assert queue[key]["attempts"] == 0
    print("PASS: test_obit_empty_enqueues")


def test_obit_no_queue_noop():
    """No queue passed to the obit step -> no crash, no enqueue (backward compatible)."""
    _patch_obit_no_results()
    today = obituary_enricher.datetime.now().strftime("%Y-%m-%d")
    notice = NoticeData(
        notice_type="probate",
        county="Jefferson",
        state="KY",
        decedent_name="NOOBIT NOQUEUE",
        case_number="26-P-009004",
        date_added=today,
    )
    obituary_enricher.enrich_obituary_data(
        [notice],
        api_key="x",
        skip_heir_verification=True,
        skip_dm_address=True,
        skip_ancestry=True,
    )
    print("PASS: test_obit_no_queue_noop")


def test_enqueue_idempotent_on_existing():
    """A key already in the queue at attempts=2 is NOT reset to 0 by a fresh enqueue."""
    _patch_courtnet([])
    notice = NoticeData(
        notice_type="probate",
        county="Jefferson",
        case_number="26-P-009005",
        decedent_name="TESTCASE EXISTING",
    )
    key = q.make_key(notice)
    # Pre-seed the queue as if a prior bump raised attempts to 2.
    queue = {key: {"repoll_after": "2026-12-31", "attempts": 2, "reason": "prior"}}
    asyncio.run(kcoj_case_detail.enrich_case_parties([notice], repoll_queue=queue))
    assert queue[key]["attempts"] == 2, (
        f"re-enqueue must NOT reset attempts; got {queue[key]}"
    )
    assert queue[key]["repoll_after"] == "2026-12-31", "re-enqueue must NOT change date"
    print("PASS: test_enqueue_idempotent_on_existing")


if __name__ == "__main__":
    test_courtnet_0_parties_enqueues()
    test_courtnet_no_queue_noop()
    test_courtnet_blank_case_not_enqueued()
    test_obit_empty_enqueues()
    test_obit_no_queue_noop()
    test_enqueue_idempotent_on_existing()
    print("\nALL PASS: test_repoll_enqueue")
