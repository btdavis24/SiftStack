"""Standalone, network-free tests for heir_identifier.identify_heirs (Phase 6 / COVER-02).

Run: .venv/Scripts/python.exe tests/test_heir_identifier.py

Mirrors the repo's standalone-test convention (bare functions + assert + print PASS,
no pytest, no network). External lookups (deeds, people-search) are monkeypatched to
return canned data — NOTHING touches CourtNet / deeds / an LLM.

The obituary source is READ-ONLY off the notice: there is no extraction call to mock.
Its tests set notice.heir_map_json / decision_maker_* directly, exactly as the Step-9
obituary pass would have left them, and prove identify_heirs reads those fields without
making a fresh LLM/URL call.

The named fixtures (McGarvey tax-foreclosure affidavit-of-descent, Walker ~10 intestate
heirs) come from docs/probate_enrichment_lessons.md pattern #5 / #7 — the no-probate /
fractured-heirship cases this helper exists to cover.
"""

import json
import os
import sys

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
sys.path.insert(0, _SRC)

import heir_identifier as hi  # noqa: E402
from notice_parser import NoticeData  # noqa: E402

# A DeedRecord-like canned row for the deed-source monkeypatches. We use a tiny
# stand-in rather than importing jefferson_deeds_scraper.DeedRecord so the test
# stays network/dep-free (bs4/urllib import chain is irrelevant here) — the source
# helpers only read .doc_type / .grantor / .grantee / .filed_date.
class _FakeDeed:
    def __init__(self, doc_type="", grantor="", grantee="", filed_date=""):
        self.doc_type = doc_type
        self.grantor = grantor
        self.grantee = grantee
        self.filed_date = filed_date


def test_obituary_path_from_heir_map_json():
    """Step-9 obituary pass already left ranked heirs on the notice — read them
    READ-ONLY (no extraction mock). Proves the contract: no fresh LLM/URL call."""
    ranked = [
        {"name": "JANE DOE", "relationship": "daughter", "status": "verified_living",
         "source": "obituary_survivors", "signing_authority": True},
        {"name": "JOHN DOE JR", "relationship": "son", "status": "unverified",
         "source": "obituary_survivors", "signing_authority": True},
        {"name": "MARY DOE", "relationship": "wife", "status": "deceased",
         "source": "obituary_survivors", "signing_authority": False},
    ]
    n = NoticeData(owner_deceased="yes", decedent_name="DOE, RICHARD",
                   heir_map_json=json.dumps(ranked))
    heirs = hi.identify_heirs(n)
    assert heirs, f"expected heirs from heir_map_json, got {heirs}"
    # Deceased heir is dropped; living + unverified survive.
    names = {h["name"] for h in heirs}
    assert "JANE DOE" in names and "JOHN DOE JR" in names, f"got {names}"
    assert "MARY DOE" not in names, "deceased heir must be dropped, not returned"
    # Each dict carries the required keys and is JSON-serializable.
    for h in heirs:
        assert "name" in h and "relationship" in h and "confidence" in h, f"bad shape: {h}"
    json.dumps(heirs)  # must not raise
    assert n.heir_id_source == "obituary", f"source should be obituary, got {n.heir_id_source!r}"
    # Confidence mapping: verified_living -> high, unverified -> manual_review.
    by_name = {h["name"]: h for h in heirs}
    assert by_name["JANE DOE"]["confidence"] == "high", by_name["JANE DOE"]
    assert by_name["JOHN DOE JR"]["confidence"] == "manual_review", by_name["JOHN DOE JR"]
    print("PASS: test_obituary_path_from_heir_map_json")


def test_obituary_path_from_decision_maker_fields():
    """heir_map_json empty but decision_maker_* set -> build a heir from those
    fields, still READ-ONLY off the notice."""
    n = NoticeData(
        owner_deceased="yes", decedent_name="SMITH, HAROLD", heir_map_json="",
        decision_maker_name="ALICE SMITH", decision_maker_relationship="daughter",
        decision_maker_status="verified_living",
        decision_maker_2_name="BOB SMITH", decision_maker_2_relationship="son",
        decision_maker_2_status="unverified",
    )
    heirs = hi.identify_heirs(n)
    assert heirs, f"expected a heir from decision_maker_* fields, got {heirs}"
    names = {h["name"] for h in heirs}
    assert "ALICE SMITH" in names, f"primary DM missing, got {names}"
    assert "BOB SMITH" in names, f"DM2 missing, got {names}"
    assert n.heir_id_source == "obituary", f"source should be obituary, got {n.heir_id_source!r}"
    print("PASS: test_obituary_path_from_decision_maker_fields")


def test_mcgarvey_affidavit_fallback(monkeypatch):
    """McGarvey: dead 4.5yrs, NO probate, NO obituary heirs on the notice, looming
    tax foreclosure. The deed source carries an AFFIDAVIT OF DESCENT naming the
    heirs as grantees -> deed fallback fires, heir_id_source == affidavit_descent."""
    n = NoticeData(owner_deceased="yes", decedent_name="MCGARVEY, PATRICK J",
                   heir_map_json="", decision_maker_name="")

    affidavit = _FakeDeed(
        doc_type="AFFIDAVIT OF DESCENT", grantor="MCGARVEY PATRICK J",
        grantee="MCGARVEY KEVIN; MCGARVEY SHEILA", filed_date="2021-03-04",
    )
    other = _FakeDeed(doc_type="MORTGAGE", grantor="MCGARVEY PATRICK J",
                      grantee="WELLS FARGO", filed_date="2009-06-01")
    monkeypatch.setattr(hi, "_fetch_deed_records", lambda notice: [other, affidavit])

    heirs = hi.identify_heirs(n)
    assert heirs, f"affidavit-of-descent grantees should be returned, got {heirs}"
    names = {h["name"].upper() for h in heirs}
    assert any("KEVIN" in nm for nm in names), f"Kevin McGarvey missing, got {names}"
    assert any("SHEILA" in nm for nm in names), f"Sheila McGarvey missing, got {names}"
    assert n.heir_id_source == "affidavit_descent", \
        f"source should be affidavit_descent, got {n.heir_id_source!r}"
    print("PASS: test_mcgarvey_affidavit_fallback")


def test_walker_deed_grantor_fallback(monkeypatch):
    """Walker (~10 intestate heirs): no obit heirs, no affidavit, but a prior
    deed-grantor chain. Deed-grantor fallback fires, heir_id_source == deed_grantor."""
    n = NoticeData(owner_deceased="yes", decedent_name="WALKER, EARL",
                   heir_map_json="", decision_maker_name="")

    # No affidavit-of-descent in the chain — just ordinary deeds. The grantor/
    # grantee parties become candidate heirs.
    deeds = [
        _FakeDeed(doc_type="DEED", grantor="WALKER EARL & WALKER BERTHA",
                  grantee="WALKER EARL", filed_date="1998-05-10"),
        _FakeDeed(doc_type="DEED OF CORRECTION", grantor="WALKER BERTHA",
                  grantee="WALKER EARL", filed_date="2003-08-22"),
    ]
    monkeypatch.setattr(hi, "_fetch_deed_records", lambda notice: deeds)

    heirs = hi.identify_heirs(n)
    assert heirs, f"deed-grantor chain should yield candidate heirs, got {heirs}"
    assert n.heir_id_source == "deed_grantor", \
        f"source should be deed_grantor, got {n.heir_id_source!r}"
    print("PASS: test_walker_deed_grantor_fallback")


def test_below_confidence_flagged_manual(monkeypatch):
    """A people-search candidate below the Phase-1 disambiguation threshold is
    INCLUDED but flagged confidence == manual_review — never auto-promoted."""
    n = NoticeData(owner_deceased="yes", decedent_name="DORSEY, FRANK",
                   heir_map_json="", decision_maker_name="")
    # Force the earlier deed sources to yield nothing so the people-search runs.
    monkeypatch.setattr(hi, "_fetch_deed_records", lambda notice: [])
    # Canned people-search candidate that disambiguate() rejects: a next-of-kin
    # with a DIFFERENT surname (the common real case — married daughter). score_match
    # against the decedent surname is 0 -> below the 0.6 floor -> None -> manual_review.
    # Proves a below-confidence candidate is KEPT (not dropped) and NOT promoted.
    monkeypatch.setattr(hi, "_people_search_candidates",
                        lambda notice, variants: [
                            {"name": "PATRICIA HAWKINS", "relationship": "possible_heir"},
                        ])

    heirs = hi.identify_heirs(n)
    assert heirs, f"below-confidence candidate must be kept (manual review), got {heirs}"
    assert all(h["confidence"] == "manual_review" for h in heirs), \
        f"below-confidence heirs must be flagged manual_review, got {heirs}"
    assert n.heir_id_source == "people_search", \
        f"source should be people_search, got {n.heir_id_source!r}"
    print("PASS: test_below_confidence_flagged_manual")


def test_phase1_absent_graceful(monkeypatch):
    """Phase 1 (kentucky_name_resolver) absent -> people-search step skips
    gracefully; the helper does not crash and earlier-source heirs still flow.
    Here every source is empty, so the result is [] — the assertion is no-crash."""
    n = NoticeData(owner_deceased="yes", decedent_name="HERFLICKER, ANTON",
                   heir_map_json="", decision_maker_name="")
    monkeypatch.setattr(hi, "_fetch_deed_records", lambda notice: [])
    # Simulate the Phase-1 import failing inside the people-search source.
    def _boom(notice):
        raise ImportError("kentucky_name_resolver not available")
    monkeypatch.setattr(hi, "_heirs_from_people_search", _boom)

    heirs = hi.identify_heirs(n)  # must NOT raise
    assert heirs == [], f"all sources empty -> [], got {heirs}"
    print("PASS: test_phase1_absent_graceful")


def test_phase1_absent_keeps_earlier_heirs(monkeypatch):
    """Belt-and-suspenders: with obituary heirs ON the notice, Phase-1 absence is
    irrelevant — the obituary source returns first and people-search never runs."""
    ranked = [{"name": "PAT WALKER", "relationship": "son",
               "status": "verified_living", "source": "obituary_survivors"}]
    n = NoticeData(owner_deceased="yes", decedent_name="WALKER, EARL",
                   heir_map_json=json.dumps(ranked))

    def _boom(notice):
        raise ImportError("kentucky_name_resolver not available")
    monkeypatch.setattr(hi, "_heirs_from_people_search", _boom)

    heirs = hi.identify_heirs(n)
    assert heirs and heirs[0]["name"] == "PAT WALKER", f"got {heirs}"
    assert n.heir_id_source == "obituary"
    print("PASS: test_phase1_absent_keeps_earlier_heirs")


def test_not_deceased_returns_empty():
    """owner_deceased != yes and no deceased_indicator -> [] (eligible gate False)."""
    n = NoticeData(owner_deceased="", deceased_indicator="",
                   decedent_name="LIVING, OWNER")
    assert hi.eligible_for_heir_id(n) is False, "living owner must not be eligible"
    assert hi.identify_heirs(n) == [], "not-deceased notice must return []"
    print("PASS: test_not_deceased_returns_empty")


def test_deceased_indicator_gates_for_phase7():
    """Phase 7 (lis pendens) sets deceased_indicator, not owner_deceased — the
    gate must accept either so the helper is general."""
    n = NoticeData(owner_deceased="", deceased_indicator="et_al",
                   decedent_name="UNKNOWN, HEIRS")
    assert hi.eligible_for_heir_id(n) is True, "deceased_indicator must satisfy the gate"
    print("PASS: test_deceased_indicator_gates_for_phase7")


def test_write_heir_map_serializes():
    """write_heir_map(notice, heirs) json.dumps the list into notice.heir_map_json
    so 06-04 can call one function."""
    n = NoticeData(decedent_name="DOE, RICHARD")
    heirs = [{"name": "JANE DOE", "relationship": "daughter",
              "confidence": "high", "source": "obituary"}]
    hi.write_heir_map(n, heirs)
    assert n.heir_map_json, "heir_map_json should be populated"
    assert json.loads(n.heir_map_json)[0]["name"] == "JANE DOE"
    print("PASS: test_write_heir_map_serializes")


def test_malformed_heir_map_json_degrades(monkeypatch):
    """T-06-04: a malformed heir_map_json must not crash — degrade to the next
    source (here deeds, which is empty, so []), guarded by JSONDecodeError."""
    n = NoticeData(owner_deceased="yes", decedent_name="COOPER, RUTH",
                   heir_map_json="{not valid json", decision_maker_name="")
    monkeypatch.setattr(hi, "_fetch_deed_records", lambda notice: [])
    monkeypatch.setattr(hi, "_heirs_from_people_search", lambda notice: [])
    heirs = hi.identify_heirs(n)  # must NOT raise
    assert heirs == [], f"malformed json -> degrade to empty, got {heirs}"
    print("PASS: test_malformed_heir_map_json_degrades")


# ── Minimal monkeypatch shim (no pytest dependency) ───────────────────────────
class _MonkeyPatch:
    """Tiny setattr-based monkeypatch with automatic undo, so these tests run
    under bare `python tests/test_heir_identifier.py` (no pytest installed)."""

    def __init__(self):
        self._undo = []

    def setattr(self, target, name, value):
        self._undo.append((target, name, getattr(target, name)))
        setattr(target, name, value)

    def undo(self):
        for target, name, old in reversed(self._undo):
            setattr(target, name, old)
        self._undo.clear()


def _run(fn):
    """Run a test fn, supplying a fresh monkeypatch if it takes one, then undo."""
    import inspect
    if "monkeypatch" in inspect.signature(fn).parameters:
        mp = _MonkeyPatch()
        try:
            fn(mp)
        finally:
            mp.undo()
    else:
        fn()


if __name__ == "__main__":
    _run(test_obituary_path_from_heir_map_json)
    _run(test_obituary_path_from_decision_maker_fields)
    _run(test_mcgarvey_affidavit_fallback)
    _run(test_walker_deed_grantor_fallback)
    _run(test_below_confidence_flagged_manual)
    _run(test_phase1_absent_graceful)
    _run(test_phase1_absent_keeps_earlier_heirs)
    _run(test_not_deceased_returns_empty)
    _run(test_deceased_indicator_gates_for_phase7)
    _run(test_write_heir_map_serializes)
    _run(test_malformed_heir_map_json_degrades)
    print("\nALL PASS: test_heir_identifier")
