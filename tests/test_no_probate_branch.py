"""Standalone, network-free routing tests for the no-probate branch (Phase 6 / COVER-02).

Run: .venv/Scripts/python.exe tests/test_no_probate_branch.py

Mirrors the repo's standalone-test convention (bare functions + assert + print PASS,
no pytest, no network). Covers the ROUTING decision that wires the shared
heir_identifier into the pipeline:

  * kcoj_case_detail._classify_party recognizes a Warning-Order-Attorney code
    ("WOA") as its own category (checked BEFORE the generic attorney bucket so a
    plain "AP" still classifies as "attorney").
  * kcoj_case_detail.no_usable_party_graph fires for 0-party / Warning-Order-
    Attorney deaths and is False for a normal executor-filled DM.
  * enrichment_pipeline._run_no_probate_branch routes eligible no-party / WOA
    deaths to identify_heirs (MONKEYPATCHED to canned heirs — never touches the
    network) and writes the result into heir_map_json, while leaving a normal
    probate lead untouched.

The named fixtures (McGarvey tax-foreclosure with no probate ever; Walker ~10
intestate unknown heirs) come from docs/probate_enrichment_lessons.md pattern #5 —
the no-probate / unknown-heir cases that surface with a Warning Order Attorney and
"UNKNOWN HEIRS" defendants instead of a probate party graph.
"""

import json
import os
import sys

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
sys.path.insert(0, _SRC)

import kcoj_case_detail as kcd  # noqa: E402
import heir_identifier as hi  # noqa: E402
import enrichment_pipeline as ep  # noqa: E402
from notice_parser import NoticeData  # noqa: E402


# ── Task 1: Warning-Order-Attorney classification ─────────────────────────────


def test_classify_warning_order_attorney():
    """_classify_party recognizes WOA as its own category; AP stays "attorney"
    (WOA check runs BEFORE the generic attorney bucket so it is not swallowed)."""
    assert kcd._classify_party("WOA") == "warning_order_attorney", \
        kcd._classify_party("WOA")
    assert kcd._classify_party("WO") == "warning_order_attorney", \
        kcd._classify_party("WO")
    # A normal estate attorney is still "attorney", not WOA.
    assert kcd._classify_party("AP") == "attorney", kcd._classify_party("AP")
    # A normal executor is unaffected.
    assert kcd._classify_party("P") == "executor", kcd._classify_party("P")
    print("PASS: test_classify_warning_order_attorney")


def test_warning_order_attorney_not_promoted():
    """A Warning-Order-Attorney is recorded in courtnet_party_types but NEVER
    promoted to owner_name / estate_attorney_name / DM (it cannot sell)."""
    n = NoticeData(notice_type="probate", county="Jefferson",
                   case_number="26-CI-009999")
    parties = [{"partyname": "SMITH, ATTORNEY WARNINGORDER", "partytype": "WOA"}]
    kcd.apply_parties_to_notice(n, parties)
    # Code recorded for analysis...
    assert "WOA" in n.courtnet_party_types, n.courtnet_party_types
    # ...but the WOA is NOT named as owner / attorney / DM.
    assert n.owner_name == "", f"WOA must not become owner_name: {n.owner_name!r}"
    assert n.estate_attorney_name == "", \
        f"WOA must not become estate_attorney_name: {n.estate_attorney_name!r}"
    assert n.decision_maker_name == "", \
        f"WOA must not become DM: {n.decision_maker_name!r}"
    print("PASS: test_warning_order_attorney_not_promoted")


# ── Task 1: no_usable_party_graph predicate ───────────────────────────────────


def test_no_usable_party_graph_predicate():
    """True for empty party graph + blank owner; True for WOA + no executor;
    False for a normal executor-filled DM."""
    # (a) 0 parties, no owner -> no usable party graph.
    empty = NoticeData(owner_deceased="yes", courtnet_party_types="", owner_name="")
    assert kcd.no_usable_party_graph(empty) is True, "0 parties must be no-usable"

    # (b) Warning-Order-Attorney only, no executor -> no usable party graph.
    woa = NoticeData(owner_deceased="yes", courtnet_party_types="WOA|DEC",
                     owner_name="")
    assert kcd.no_usable_party_graph(woa) is True, "WOA-only must be no-usable"
    assert kcd.has_warning_order_attorney(woa) is True

    # (c) Normal executor-filled DM -> usable party graph (NOT touched).
    normal = NoticeData(owner_deceased="yes", courtnet_party_types="P|AP",
                        owner_name="Jane Q Executor")
    assert kcd.no_usable_party_graph(normal) is False, \
        "a real executor owner_name must be usable"
    assert kcd.has_warning_order_attorney(normal) is False
    print("PASS: test_no_usable_party_graph_predicate")


# ── Task 2: routing via _run_no_probate_branch (identify_heirs monkeypatched) ──


def _patch_identify_heirs(monkeypatch, canned):
    """Monkeypatch heir_identifier.identify_heirs to return canned heirs (and set
    heir_id_source like the real helper) — NO network. _run_no_probate_branch does
    `from heir_identifier import identify_heirs`, so patching the module attr is
    picked up at call time."""
    def _fake(notice):
        notice.heir_id_source = "affidavit_descent"
        return list(canned)
    monkeypatch.setattr(hi, "identify_heirs", _fake)


def test_warning_order_attorney_routes_to_identify_heirs(monkeypatch):
    """A deceased notice whose only CourtNet party is a Warning-Order-Attorney
    routes to identify_heirs (monkeypatched) -> heir_map_json populated, source
    set, notice NOT dropped."""
    canned = [{"name": "JOHN HEIR", "relationship": "son",
               "confidence": "medium", "source": "affidavit_descent"}]
    _patch_identify_heirs(monkeypatch, canned)

    n = NoticeData(owner_deceased="yes", decedent_name="DECEASED, NOPROBATE",
                   courtnet_party_types="WOA", owner_name="", heir_map_json="")
    hits, candidates = ep._run_no_probate_branch([n])

    assert candidates == 1, f"WOA death must be a candidate, got {candidates}"
    assert hits == 1, f"WOA death must produce heirs, got {hits}"
    assert n.heir_map_json.strip(), "heir_map_json must be populated"
    assert json.loads(n.heir_map_json)[0]["name"] == "JOHN HEIR"
    assert n.heir_id_source == "affidavit_descent", n.heir_id_source
    print("PASS: test_warning_order_attorney_routes_to_identify_heirs")


def test_mcgarvey_unknown_heir_routes(monkeypatch):
    """McGarvey-style: dead ~4.5 years, NO probate ever, looming tax foreclosure,
    0 CourtNet parties -> the branch fires and populates heir_map_json (instead of
    dropping the most-motivated lead)."""
    canned = [{"name": "KEVIN MCGARVEY", "relationship": "heir",
               "confidence": "medium", "source": "affidavit_descent"},
              {"name": "SHEILA MCGARVEY", "relationship": "heir",
               "confidence": "medium", "source": "affidavit_descent"}]
    _patch_identify_heirs(monkeypatch, canned)

    mcgarvey = NoticeData(owner_deceased="yes", decedent_name="MCGARVEY, ROBERT",
                          notice_type="tax_sale", courtnet_party_types="",
                          owner_name="", heir_map_json="")
    hits, candidates = ep._run_no_probate_branch([mcgarvey])

    assert candidates == 1 and hits == 1, f"McGarvey: {hits}/{candidates}"
    names = {h["name"] for h in json.loads(mcgarvey.heir_map_json)}
    assert "KEVIN MCGARVEY" in names, names
    print("PASS: test_mcgarvey_unknown_heir_routes")


def test_walker_unknown_heir_routes(monkeypatch):
    """Walker-style: intestate ~10 unknown heirs, no probate party graph -> branch
    fires and writes the candidate heirs."""
    canned = [{"name": f"WALKER HEIR {i}", "relationship": "heir",
               "confidence": "manual_review", "source": "deed_grantor"}
              for i in range(10)]
    monkeypatch.setattr(hi, "identify_heirs",
                        lambda notice: (setattr(notice, "heir_id_source",
                                                "deed_grantor") or list(canned)))

    walker = NoticeData(owner_deceased="yes", decedent_name="WALKER, EARL",
                        notice_type="probate", courtnet_party_types="WOA",
                        owner_name="", heir_map_json="")
    hits, candidates = ep._run_no_probate_branch([walker])

    assert candidates == 1 and hits == 1, f"Walker: {hits}/{candidates}"
    assert len(json.loads(walker.heir_map_json)) == 10, "all 10 heirs written"
    assert walker.heir_id_source == "deed_grantor", walker.heir_id_source
    print("PASS: test_walker_unknown_heir_routes")


def test_normal_probate_not_touched(monkeypatch):
    """A normal probate lead with a real executor owner_name + executor party type
    is NOT a candidate (no_usable_party_graph is False) — the branch never
    overwrites owner_name / heir_map_json (T-06-10)."""
    # If identify_heirs were called on this notice the test would (wrongly) write
    # heirs — assert it is NEVER called for the normal lead.
    called = {"n": 0}

    def _spy(notice):
        called["n"] += 1
        notice.heir_id_source = "obituary"
        return [{"name": "SHOULD NOT APPEAR", "relationship": "x",
                 "confidence": "high", "source": "obituary"}]
    monkeypatch.setattr(hi, "identify_heirs", _spy)

    normal = NoticeData(owner_deceased="yes", decedent_name="DOE, RICHARD",
                        notice_type="probate", courtnet_party_types="P|AP",
                        owner_name="Jane Q Executor", heir_map_json="")
    hits, candidates = ep._run_no_probate_branch([normal])

    assert candidates == 0, f"normal probate must NOT be a candidate, got {candidates}"
    assert hits == 0, f"normal probate must produce no branch hits, got {hits}"
    assert called["n"] == 0, "identify_heirs must not be called for normal probate"
    assert normal.owner_name == "Jane Q Executor", "owner_name must be preserved"
    assert normal.heir_map_json == "", "heir_map_json must not be written"
    print("PASS: test_normal_probate_not_touched")


def test_already_has_heirs_skipped(monkeypatch):
    """A deceased no-party notice that ALREADY has heir_map_json (the obituary pass
    at Step 9 populated it) is skipped — the branch only fills empty heirs (T-06-12
    bounds the work)."""
    called = {"n": 0}
    monkeypatch.setattr(hi, "identify_heirs",
                        lambda notice: (called.__setitem__("n", called["n"] + 1)
                                        or []))

    prior = json.dumps([{"name": "EXISTING HEIR", "relationship": "daughter",
                         "confidence": "high", "source": "obituary"}])
    n = NoticeData(owner_deceased="yes", decedent_name="DECEASED, HASOBIT",
                   courtnet_party_types="", owner_name="", heir_map_json=prior)
    hits, candidates = ep._run_no_probate_branch([n])

    assert candidates == 0, f"already-has-heirs must be skipped, got {candidates}"
    assert called["n"] == 0, "identify_heirs must not be called when heirs exist"
    assert json.loads(n.heir_map_json)[0]["name"] == "EXISTING HEIR", \
        "existing heirs must be preserved"
    print("PASS: test_already_has_heirs_skipped")


def test_not_deceased_not_a_candidate(monkeypatch):
    """A living owner with no party graph is NOT eligible_for_heir_id, so the
    branch never fires for it."""
    monkeypatch.setattr(hi, "identify_heirs",
                        lambda notice: [{"name": "X", "relationship": "y",
                                         "confidence": "low", "source": "z"}])
    living = NoticeData(owner_deceased="", deceased_indicator="",
                        decedent_name="", courtnet_party_types="", owner_name="")
    hits, candidates = ep._run_no_probate_branch([living])
    assert candidates == 0, f"living owner must not be a candidate, got {candidates}"
    assert hits == 0
    print("PASS: test_not_deceased_not_a_candidate")


# ── Minimal monkeypatch shim (no pytest dependency) ───────────────────────────
class _MonkeyPatch:
    """Tiny setattr-based monkeypatch with automatic undo, so these tests run
    under bare `python tests/test_no_probate_branch.py` (no pytest installed)."""

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
    _run(test_classify_warning_order_attorney)
    _run(test_warning_order_attorney_not_promoted)
    _run(test_no_usable_party_graph_predicate)
    _run(test_warning_order_attorney_routes_to_identify_heirs)
    _run(test_mcgarvey_unknown_heir_routes)
    _run(test_walker_unknown_heir_routes)
    _run(test_normal_probate_not_touched)
    _run(test_already_has_heirs_skipped)
    _run(test_not_deceased_not_a_candidate)
    print("\nALL PASS: test_no_probate_branch")
