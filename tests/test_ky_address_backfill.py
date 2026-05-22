"""Network-free unit tests for the KY-aware DM/heir address backfill (task 2g-2).

Covers Task 3 A/B/C:
  * KY dispatch — _lookup_dm_address(..., state="KY") routes to the PVA waterfall
    (search_by_owner), NOT the TN Knox-Tax tier.
  * heir state inheritance — a KY notice's signing heir inherits state "KY"
    (not the hardcoded "TN") through _lookup_missing_heir_addresses.
  * TN fallback preserved — a notice with empty state still falls back to "TN".

No network: kentucky_pva_lookup.search_by_owner and _lookup_dm_address are
monkeypatched in-process. Standalone-script style per TESTING.md.

Run:  python tests/test_ky_address_backfill.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import obituary_enricher  # noqa: E402
import tracerfy_skip_tracer  # noqa: E402
import kentucky_pva_lookup as pva  # noqa: E402
from kentucky_pva_lookup import PvaRow  # noqa: E402
from notice_parser import NoticeData  # noqa: E402


def test_ky_dispatch_calls_pva():
    """state="KY" -> PVA waterfall returns the parcel; Knox-Tax tier NOT used."""
    saved_search = pva.search_by_owner
    saved_knox = obituary_enricher._lookup_dm_address_knox_tax

    def _fake_search_by_owner(session, owner_name, max_pages=None):
        return [PvaRow(address="123 KY St", owner=owner_name,
                       parcel_id="PID123", lrsn="L1", legal="LOT 1")]

    def _explode_knox(name):  # must never be reached for a KY notice
        raise AssertionError("Knox Tax tier called for a KY lookup")

    pva.search_by_owner = _fake_search_by_owner
    obituary_enricher._lookup_dm_address_knox_tax = _explode_knox
    try:
        result = obituary_enricher._lookup_dm_address(
            "John Smith", "Louisville", "", state="KY",
        )
        assert result.get("source") == "ky_pva", result
        assert result.get("street") == "123 KY St", result
        assert result.get("state") == "KY", result
    finally:
        pva.search_by_owner = saved_search
        obituary_enricher._lookup_dm_address_knox_tax = saved_knox
    print("PASS: test_ky_dispatch_calls_pva")


def test_heir_state_inherits_ky():
    """A KY notice's signing heir inherits state KY (not TN) on backfill."""
    saved = obituary_enricher._lookup_dm_address

    def _fake_lookup(name, city, api_key, tracerfy_tier1=False, state=""):
        # Return an address with an EMPTY state so the inheritance branch runs.
        return {"street": "1 A St", "city": "", "state": "", "zip": "", "source": "x"}

    obituary_enricher._lookup_dm_address = _fake_lookup
    try:
        n = NoticeData()
        n.state = "KY"
        n.owner_deceased = "yes"
        n.heir_map_json = json.dumps([
            {"name": "Heir One", "status": "verified_living",
             "signing_authority": True, "street": ""},
        ])
        filled = tracerfy_skip_tracer._lookup_missing_heir_addresses(n, None)
        assert filled == 1, filled
        heirs = json.loads(n.heir_map_json)
        assert heirs[0]["state"] == "KY", heirs[0]
    finally:
        obituary_enricher._lookup_dm_address = saved
    print("PASS: test_heir_state_inherits_ky")


def test_tn_default_preserved():
    """A notice with empty state -> heir state falls back to TN (regression guard)."""
    saved = obituary_enricher._lookup_dm_address

    def _fake_lookup(name, city, api_key, tracerfy_tier1=False, state=""):
        return {"street": "1 A St", "city": "", "state": "", "zip": "", "source": "x"}

    obituary_enricher._lookup_dm_address = _fake_lookup
    try:
        n = NoticeData()
        n.state = ""  # genuinely empty (TN scrape path)
        n.owner_deceased = "yes"
        n.heir_map_json = json.dumps([
            {"name": "Heir One", "status": "verified_living",
             "signing_authority": True, "street": ""},
        ])
        filled = tracerfy_skip_tracer._lookup_missing_heir_addresses(n, None)
        assert filled == 1, filled
        heirs = json.loads(n.heir_map_json)
        assert heirs[0]["state"] == "TN", heirs[0]
    finally:
        obituary_enricher._lookup_dm_address = saved
    print("PASS: test_tn_default_preserved")


def test_ky_pva_miss_falls_through_not_knox():
    """KY PVA miss must fall through to the national WEB tier (people search),
    NOT the TN Knox-Tax tier. All network seams are stubbed (no real HTTP)."""
    saved_search = pva.search_by_owner
    saved_knox = obituary_enricher._lookup_dm_address_knox_tax
    saved_sf = obituary_enricher._lookup_dm_address_serper_firecrawl
    saved_web = obituary_enricher._lookup_dm_address_web

    pva.search_by_owner = lambda session, owner_name, max_pages=None: []

    def _explode_knox(name):
        raise AssertionError("Knox Tax tier called on a KY PVA miss")

    web_called = {"hit": False}

    def _fake_sf(name, city, api_key):
        # The KY fall-through must reach the national web tier — stub it so no
        # real Serper/Firecrawl HTTP fires and the source is people_search.
        web_called["hit"] = True
        return {"street": "500 Web St", "city": city, "state": "KY", "zip": ""}

    def _explode_web(name, city, api_key):
        raise AssertionError("DDG web tier called while Serper stub returned a hit")

    obituary_enricher._lookup_dm_address_knox_tax = _explode_knox
    obituary_enricher._lookup_dm_address_serper_firecrawl = _fake_sf
    obituary_enricher._lookup_dm_address_web = _explode_web
    try:
        result = obituary_enricher._lookup_dm_address(
            "Nobody Here", "Louisville", "", state="KY",
        )
        # Knox Tax was never invoked; the KY miss fell through to the web tier.
        assert web_called["hit"] is True, "web tier not reached on KY PVA miss"
        assert result.get("source") == "people_search", result
        assert result.get("source") != "knox_tax_api", result
    finally:
        pva.search_by_owner = saved_search
        obituary_enricher._lookup_dm_address_knox_tax = saved_knox
        obituary_enricher._lookup_dm_address_serper_firecrawl = saved_sf
        obituary_enricher._lookup_dm_address_web = saved_web
    print("PASS: test_ky_pva_miss_falls_through_not_knox")


if __name__ == "__main__":
    test_ky_dispatch_calls_pva()
    test_heir_state_inherits_ky()
    test_tn_default_preserved()
    test_ky_pva_miss_falls_through_not_knox()
    print("\nALL PASS: ky_address_backfill")
