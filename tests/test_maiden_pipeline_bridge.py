"""Production-flow regression test for the obituary -> PVA maiden bridge.

This test exercises the REAL enrichment pipeline ordering that the Phase 1
verifier found broken (SC-1): the live pipeline runs the PVA probate lookup
(Step 3d) BEFORE obituary enrichment (Step 9), so on the first PVA pass a
property titled under a maiden/prior surname (the canonical Jackson ->
GREATHOUSE 0-row case) cannot resolve. The fix is the obituary step writing
notice.decedent_obit_maiden_name onto the notice plus a post-obituary PVA
maiden-retry (Step 9c) that re-runs the lookup for the eligible subset.

Unlike tests/test_name_resolver_wiring.py (which manually injects the maiden
attribute), this test calls the ACTUAL production code that sets it:
obituary_enricher._apply_obituary_match. It therefore reproduces the exact
sequence that was dead in production and would have caught the gap:

    1. Step 3d (first PVA pass)      -> no maiden context  -> address STAYS empty
    2. Step 9  (obituary)            -> _apply_obituary_match SETS the maiden field
    3. Step 9c (post-obituary retry) -> PVA re-reads maiden -> address RESOLVES

It also asserts the fail-safe: a notice whose obituary never finds a maiden
name (the bridge never fires) stays empty after the same full sequence, so the
retry never auto-attaches a wrong parcel.

Network-free: the PVA per-query primitive ``search_by_owner`` and the
session/login/detail helpers are stubbed; the obituary LLM/web-search layer is
NOT called — instead the real ``_apply_obituary_match`` is invoked with a
pre-built ``parsed`` dict (the shape an obituary LLM extraction would return),
so zero HTTP is made. Standalone-script style per TESTING.md (no pytest; bare
asserts + print PASS; ``__main__`` runner).

Run:  python tests/test_maiden_pipeline_bridge.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import kentucky_pva_lookup as pva  # noqa: E402
from kentucky_pva_lookup import PvaRow, probate_property_lookup  # noqa: E402
from obituary_enricher import _apply_obituary_match  # noqa: E402
from notice_parser import NoticeData  # noqa: E402


# ── Stub seam (network-free PVA) ──────────────────────────────────────
# search_by_owner returns the GREATHOUSE parcel ONLY for the maiden query
# ("GREATHOUSE ..."), [] for every JACKSON variant — exactly the live
# "0 rows under the married name" case. Session/login/detail helpers are
# no-ops; get_detail returns {} so _apply_to_notice falls back to row fields.

_GREATHOUSE_ROW = PvaRow(
    address="2120 Hale Ave",
    owner="GREATHOUSE DOROTHY E",
    parcel_id="ABC123456789",
    lrsn="999999",
    legal="LOT 7 PARK HILL",
)


def _fake_search_by_owner(session, owner_name, max_pages=None):
    """Maiden-only parcel; mirrors the live primitive's signature."""
    if "GREATHOUSE" in (owner_name or "").upper():
        return [_GREATHOUSE_ROW]
    return []


def _install_stubs():
    """Replace the PVA network seam with in-process no-ops/fakes.

    Returns a restore() callable so the module is left clean for other tests.
    """
    orig = {
        "search_by_owner": pva.search_by_owner,
        "_make_session": pva._make_session,
        "_login": pva._login,
        "_logout": pva._logout,
        "get_detail": pva.get_detail,
    }
    pva.search_by_owner = _fake_search_by_owner
    pva._make_session = lambda: object()        # no real requests.Session
    pva._login = lambda session: True           # pretend auth succeeded
    pva._logout = lambda session: None          # no-op
    pva.get_detail = lambda session, lrsn: {}   # no detail-page HTTP

    def restore():
        for k, v in orig.items():
            setattr(pva, k, v)

    return restore


def _make_notice():
    return NoticeData(
        notice_type="probate",
        county="Jefferson",
        state="KY",
        decedent_name="Dorothy Emma Jackson",
    )


# The shape an obituary LLM extraction returns for a maiden-name decedent.
# _apply_obituary_match reads maiden_name / also_known_as defensively and
# (post-fix) writes them onto the notice object.
_OBIT_PARSED_WITH_MAIDEN = {
    "date_of_death": "2026-01-03",
    "maiden_name": "Greathouse",
    "also_known_as": [],
    "survivors": [],
    "executor_named": "Monroe Jackson Jr",
    "full_name": "Dorothy Emma Jackson",
}

# An obituary that confirms death but yields NO maiden / aka surname — the
# bridge must not fire, and the retry must not resolve (fail-safe).
_OBIT_PARSED_NO_MAIDEN = {
    "date_of_death": "2026-01-03",
    "maiden_name": "",
    "also_known_as": [],
    "survivors": [],
    "executor_named": "Monroe Jackson Jr",
    "full_name": "Dorothy Emma Jackson",
}


# ── Tests ─────────────────────────────────────────────────────────────
def test_pipeline_order_resolves_maiden_via_post_obituary_retry():
    """Full production sequence: 3d (miss) -> 9 (set maiden) -> 9c (resolve)."""
    restore = _install_stubs()
    try:
        notice = _make_notice()

        # ── Step 3d analog: first PVA pass, BEFORE obituary ──────────────
        # No maiden context yet -> JACKSON variants return 0 rows -> empty.
        probate_property_lookup([notice])
        assert not notice.address, (
            "first PVA pass wrongly resolved an address before obituary ran "
            f"(got {notice.address!r}) — the maiden case must miss here"
        )
        assert not notice.decedent_obit_maiden_name, (
            "maiden field should not be set before the obituary step"
        )

        # ── Step 9 analog: REAL obituary apply sets the maiden field ─────
        _apply_obituary_match(
            notice, _OBIT_PARSED_WITH_MAIDEN,
            "https://example.com/obit", source_type="full_page",
        )
        assert notice.decedent_obit_maiden_name == "Greathouse", (
            "obituary step did not bridge the maiden name onto the notice "
            f"(got {notice.decedent_obit_maiden_name!r}) — this is the gap"
        )
        assert notice.owner_deceased == "yes", "obituary should mark deceased"

        # ── Step 9c analog: post-obituary PVA maiden retry resolves ──────
        # PVA re-reads getattr(notice, 'decedent_obit_maiden_name') -> emits +
        # searches the GREATHOUSE variant -> attaches the parcel.
        probate_property_lookup([notice])
        assert notice.address, (
            "post-obituary maiden retry did not populate address "
            f"(got address={notice.address!r}, parcel={notice.parcel_id!r}) — "
            "the obituary->PVA maiden bridge is still broken in production"
        )
        assert "Hale Ave" in notice.address, f"Got: {notice.address!r}"
        assert notice.parcel_id == "ABC123456789", (
            f"expected GREATHOUSE parcel attached, got {notice.parcel_id!r}"
        )
    finally:
        restore()
    print(
        "PASS: test_pipeline_order_resolves_maiden_via_post_obituary_retry "
        "(3d miss -> 9 sets maiden -> 9c resolves)"
    )


def test_failsafe_without_bridge_stays_empty():
    """No maiden found -> bridge never fires -> retry never attaches a parcel.

    This is the negative control proving the resolution is caused by the
    maiden bridge specifically: same code path, same stubs, but the obituary
    yields no maiden surname, so the field stays empty and the retry resolves
    nothing (it must NOT auto-attach a wrong-person parcel).
    """
    restore = _install_stubs()
    try:
        notice = _make_notice()

        # First PVA pass: miss (as above).
        probate_property_lookup([notice])
        assert not notice.address

        # Obituary confirms death but extracts NO maiden name -> no bridge.
        _apply_obituary_match(
            notice, _OBIT_PARSED_NO_MAIDEN,
            "https://example.com/obit", source_type="full_page",
        )
        assert not notice.decedent_obit_maiden_name, (
            "no maiden in the obituary, but the field was set anyway "
            f"(got {notice.decedent_obit_maiden_name!r})"
        )

        # Retry: still no maiden context -> JACKSON variants 0 rows -> empty.
        probate_property_lookup([notice])
        assert not notice.address, (
            f"retry without a maiden bridge wrongly attached {notice.address!r}"
        )
        assert not notice.parcel_id, (
            f"retry without a maiden bridge wrongly attached {notice.parcel_id!r}"
        )
    finally:
        restore()
    print(
        "PASS: test_failsafe_without_bridge_stays_empty "
        "(no maiden -> no attach)"
    )


if __name__ == "__main__":
    test_pipeline_order_resolves_maiden_via_post_obituary_retry()
    test_failsafe_without_bridge_stays_empty()
    print(
        "\nAll maiden-pipeline-bridge tests passed "
        "(production ordering, network-free)."
    )
