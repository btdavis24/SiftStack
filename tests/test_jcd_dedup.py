"""Network-free standalone tests for the JCD lis-pendens cross-run dedup cache.

Covers spec 3a (stale-prune on load) and 3b (gate the PDF fetch inside
scrape_jefferson_deeds — two-run zero-fetch + mark-seen-after-append, the LP-02
OCR-cost-saving invariant).

No pytest, no mock framework: module-level functions are monkeypatched BY
ASSIGNMENT (matches .planning/codebase/TESTING.md). The test never touches the
network, credentials, or env vars.

Run: .venv/Scripts/python.exe tests/test_jcd_dedup.py
"""

import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import config
import jefferson_deeds_scraper as jcd


# ── Network-free monkeypatch scaffolding ──────────────────────────────
# Two canned LP records carrying the dedup-key fields the gate reads
# (instnum/year/db) plus the fields the loop builds NoticeData from.
_FAKE_RECORDS = [
    {
        "instnum": "100001", "year": "2026", "db": "P",
        "detail_url": "https://search.jeffersondeeds.com/pdetail.php?instnum=100001&year=2026&db=P",
        "grantor": "DOE JOHN", "grantees": "ACME BANK",
        "legal_desc": "LOT 1 BLOCK A FAKE SUBDIVISION", "case_num": "26-CI-000001",
        "date_filed": "05/01/2026", "book_page": "", "view_img": "imgkey-aaa",
    },
    {
        "instnum": "100002", "year": "2026", "db": "P",
        "detail_url": "https://search.jeffersondeeds.com/pdetail.php?instnum=100002&year=2026&db=P",
        "grantor": "ROE JANE", "grantees": "BETA CREDIT UNION",
        "legal_desc": "LOT 2 BLOCK B FAKE SUBDIVISION", "case_num": "26-CI-000002",
        "date_filed": "05/01/2026", "book_page": "", "view_img": "imgkey-bbb",
    },
]

# Counts how many times the expensive PDF/OCR fetch is invoked. The LP-02
# invariant is that an already-seen instrument never triggers this.
_fetch_count = 0


def _fake_fetch_address(view_img):
    global _fetch_count
    _fetch_count += 1
    return ("123 FAKE ST", "Louisville", "40202", "CONST-PARCEL", "ocr")


def _install_network_free_stubs():
    """Replace every network/IO function the scraper would call with stubs."""
    jcd._post = lambda url, params: "HIT LIST"        # passes the early guard
    jcd._parse_results_table = lambda html: [dict(r) for r in _FAKE_RECORDS]
    jcd._fetch_address_from_document = _fake_fetch_address
    jcd._delay = lambda: None


# ── Tests ─────────────────────────────────────────────────────────────


def test_instrument_key():
    assert jcd._instrument_key("123456", "2026", "P") == "123456-2026-P"
    print("PASS: test_instrument_key -> 123456-2026-P")


def test_load_jcd_seen_prunes_stale():
    """3a: a >120-day-old key is dropped on load; a fresh key survives."""
    tmp = Path(tempfile.gettempdir()) / "jcd_seen_dedup_test.json"
    orig_file = config.JCD_SEEN_FILE
    config.JCD_SEEN_FILE = tmp
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        stale = (datetime.now() - timedelta(days=200)).strftime("%Y-%m-%d")
        jcd.save_jcd_seen({"FRESH-2026-P": today, "STALE-2024-P": stale})
        loaded = jcd.load_jcd_seen()
        assert "FRESH-2026-P" in loaded, loaded
        assert "STALE-2024-P" not in loaded, loaded
        print("PASS: test_load_jcd_seen_prunes_stale (stale dropped, fresh kept)")
    finally:
        config.JCD_SEEN_FILE = orig_file
        for p in [tmp, tmp.with_suffix(".json.bak"), tmp.with_suffix(".tmp")]:
            if p.exists():
                p.unlink()


def test_two_run_zero_fetch():
    """3b/LP-02: a 2nd scrape over an unchanged window with the same
    seen_instruments dict returns [] and performs ZERO PDF/OCR fetches; and
    instruments are marked seen only after their NoticeData is appended."""
    global _fetch_count
    _install_network_free_stubs()
    seen: dict[str, str] = {}

    # Run 1: both filings are new → 2 notices emitted, 2 fetches paid, both
    # instrument keys recorded (mark-after-append).
    _fetch_count = 0
    r1 = jcd.scrape_jefferson_deeds(
        "2026-05-01", "2026-05-02", seen_instruments=seen,
    )
    assert len(r1) == 2, f"run 1 expected 2 notices, got {len(r1)}"
    assert _fetch_count == 2, f"run 1 expected 2 fetches, got {_fetch_count}"
    assert len(seen) == 2, f"run 1 expected 2 seen keys, got {len(seen)}: {seen}"
    assert "100001-2026-P" in seen and "100002-2026-P" in seen, seen

    # Run 2: same window, same cache → every instrument is already seen, so the
    # loop skips before the PDF fetch. Zero notices, ZERO OCR cost (LP-02).
    _fetch_count = 0
    r2 = jcd.scrape_jefferson_deeds(
        "2026-05-01", "2026-05-02", seen_instruments=seen,
    )
    assert r2 == [], f"run 2 expected [], got {r2}"
    assert _fetch_count == 0, f"run 2 expected 0 fetches (LP-02), got {_fetch_count}"
    print("PASS: test_two_run_zero_fetch (run1=2 notices/2 fetches/2 seen; run2=[] /0 fetches)")


# ── Main runner ───────────────────────────────────────────────────────
if __name__ == "__main__":
    test_instrument_key()
    test_load_jcd_seen_prunes_stale()
    test_two_run_zero_fetch()
    print("ALL PASS")
