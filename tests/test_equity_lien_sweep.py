"""Unit tests for the Phase 2d lien/encumbrance sweep (kentucky_equity_estimator).

Standalone script per TESTING.md — run directly:

    python tests/test_equity_lien_sweep.py          # (use .venv/Scripts/python.exe on Windows)

NO network: every test drives the injectable ``estimate_equity(notice, records=...)``
path with hand-built DeedRecord fixtures. No ``scan_liens`` / ``_make_opener``
call appears anywhere in this file. Each cited case from the 128-case review
(pattern #4) gets a fixture; an invariant test + safety tests round it out.

Bare ``assert`` + ``print("PASS: ...")``; an AssertionError propagates to a
non-zero exit so the harness sees failure.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from notice_parser import NoticeData
from jefferson_deeds_scraper import DeedRecord
from kentucky_equity_estimator import (
    estimate_equity,
    _net_encumbrances,
    _classify_lien,
    _has_medicaid_signal,
)


# ── Fixture helpers ───────────────────────────────────────────────────────
def _rec(doc_type, *, instnum="2020000001", year="2020", filed_date="2020-01-01",
         grantor="", grantee="", legal_desc="", amount=None, xrefs=None):
    """Build a DeedRecord with sensible defaults. ``amount`` (when set) is the
    dollar figure _record_amount reads via the optional ``amount`` attribute —
    this is how the suite supplies lien/mortgage amounts with NO network."""
    r = DeedRecord(
        instnum=instnum, year=year, db="", filed_date=filed_date,
        book_page="", doc_type=doc_type, grantor=grantor, grantee=grantee,
        legal_desc=legal_desc, detail_url="", view_img="",
        xrefs=list(xrefs) if xrefs else [],
    )
    if amount is not None:
        r.amount = amount  # optional attribute read by _record_amount
    return r


def _notice(assessed, **kw):
    n = NoticeData(state="KY", county="Jefferson", property_owner_status="direct",
                   estimated_value=str(assessed))
    for k, v in kw.items():
        setattr(n, k, v)
    return n


# ── HECM (no straight-line) — Wheatley / Herflicker ───────────────────────
def test_wheatley_hecm():
    n = _notice(300000, decedent_name="WHEATLEY MARY")
    recs = [_rec("MORTGAGE", grantee="FINANCIAL FREEDOM REVERSE MORTGAGE", amount="150000")]
    assert estimate_equity(n, records=recs) is True
    assert "hecm" in n.lien_flags, n.lien_flags
    assert float(n.equity_percent) < 100, n.equity_percent
    # HECM is flagged + depressed, NOT reported as full equity.
    assert int(n.estimated_equity) < 300000, n.estimated_equity
    print("PASS: test_wheatley_hecm")


def test_herflicker_hecm():
    # Unknown HECM balance: still flagged, still below 100 via the ceiling, and
    # never straight-line amortized (no amount supplied).
    n = _notice(250000, decedent_name="HERFLICKER ANN")
    recs = [_rec("HOME EQUITY CONVERSION MORTGAGE", grantee="AMERICAN ADVISORS GROUP")]
    estimate_equity(n, records=recs)
    assert "hecm" in n.lien_flags, n.lien_flags
    assert float(n.equity_percent) < 100, n.equity_percent
    print("PASS: test_herflicker_hecm")


# ── Junior liens eat equity — Presley / Logsdon ───────────────────────────
def test_presley_junior_liens():
    # VA + credit-card junior liens on top of value.
    n = _notice(200000, decedent_name="PRESLEY ELVIS")
    recs = [
        _rec("WARRANTY DEED", instnum="2010000001", grantee="PRESLEY ELVIS"),
        _rec("JUDGMENT", instnum="2021000002", grantor="PRESLEY ELVIS",
             grantee="CREDIT ACCEPTANCE", amount="25000"),
        _rec("CREDIT CARD LIEN", instnum="2022000003", grantor="PRESLEY ELVIS",
             grantee="CAPITAL ONE", amount="8000"),
    ]
    estimate_equity(n, records=recs)
    assert "judgment" in n.lien_flags, n.lien_flags
    assert float(n.equity_percent) < 100, n.equity_percent
    assert int(n.estimated_equity) < 200000, n.estimated_equity
    print("PASS: test_presley_junior_liens")


def test_logsdon_state_liens():
    # Four unreleased state liens.
    n = _notice(386000, decedent_name="LOGSDON RICKY")
    recs = [_rec("WARRANTY DEED", instnum="2001000001", grantee="LOGSDON RICKY")]
    for i, amt in enumerate(("4000", "3000", "5000", "2500")):
        recs.append(_rec("STATE LIEN", instnum=f"201{i}000099",
                         grantor="LOGSDON RICKY", grantee="KY DEPT OF REVENUE", amount=amt))
    estimate_equity(n, records=recs)
    assert "judgment" in n.lien_flags, n.lien_flags
    assert float(n.equity_percent) < 100, n.equity_percent
    # 4 liens netted -> equity below assessed by their sum.
    assert int(n.estimated_equity) <= 386000 - 14000, n.estimated_equity
    print("PASS: test_logsdon_state_liens")


# ── Tax/code liens exceed value -> negative equity — Walker / Thompson-Hale ─
def test_walker_tax_code_negative():
    # Mortgage-FREE low-end home; tax-cert + code liens sum ABOVE value.
    n = _notice(60000, decedent_name="WALKER LORETTO")
    recs = [
        _rec("WARRANTY DEED", instnum="1999000001", grantee="WALKER LORETTO"),
        _rec("CERTIFICATE OF DELINQUENCY", instnum="2022000010",
             grantor="WALKER LORETTO", grantee="JEFFERSON COUNTY CLERK", amount="40000"),
        _rec("CODE ENFORCEMENT LIEN", instnum="2023000011",
             grantor="WALKER LORETTO", grantee="LOUISVILLE METRO", amount="30000"),
    ]
    estimate_equity(n, records=recs)
    assert "tax_cert" in n.lien_flags, n.lien_flags
    assert int(n.estimated_equity) < 0, n.estimated_equity  # NEGATIVE on a "mortgage-free" home
    print("PASS: test_walker_tax_code_negative")


def test_thompson_hale_negative():
    n = _notice(55000, decedent_name="THOMPSON HALE")
    recs = [
        _rec("WARRANTY DEED", instnum="2000000001", grantee="THOMPSON HALE"),
        _rec("TAX CERTIFICATE", instnum="2024000020",
             grantor="THOMPSON HALE", grantee="COUNTY CLERK", amount="35000"),
        _rec("DEMOLITION LIEN", instnum="2024000021",
             grantor="THOMPSON HALE", grantee="LOUISVILLE METRO", amount="28000"),
    ]
    estimate_equity(n, records=recs)
    assert "tax_cert" in n.lien_flags, n.lien_flags
    assert int(n.estimated_equity) < 0, n.estimated_equity
    print("PASS: test_thompson_hale_negative")


# ── Release hidden past the first mortgage — Murphy / Mudd-Francis ─────────
def test_murphy_hidden_release():
    # Mortgage EARLY in the list; its matching RELEASE placed LATE (where a
    # first-page-only scan would have stopped). The full-history scan finds the
    # release via xref -> mortgage is treated as released, no open_mortgage flag.
    mtg = _rec("MORTGAGE", instnum="2015100000", year="2015", filed_date="2015-03-01",
               grantor="MURPHY JOHN", grantee="CHASE BANK", amount="120000")
    deed = _rec("WARRANTY DEED", instnum="2010000001", year="2010", grantee="MURPHY JOHN")
    rel = _rec("REL MTG", instnum="2018200000", year="2018", filed_date="2018-06-01",
               grantor="CHASE BANK", grantee="MURPHY JOHN", xrefs=["2015100000"])
    # Order: deed, mortgage early, release LAST.
    recs = [deed, mtg, rel]
    estimate_equity(n := _notice(310000, decedent_name="MURPHY JOHN"), records=recs)
    assert n.lien_flags == "", f"expected no flags, got {n.lien_flags!r}"
    assert "open_mortgage" not in n.lien_flags
    assert n.equity_percent == "100.0", n.equity_percent
    print("PASS: test_murphy_hidden_release")


def test_mudd_francis_hidden_release():
    mtg = _rec("MORTGAGE", instnum="2008500000", year="2008", filed_date="2008-10-08",
               grantor="MUDD FRANCIS", grantee="COUNTRYWIDE", amount="200000")
    rel = _rec("RELEASE OF MORTGAGE", instnum="2017900000", year="2017",
               filed_date="2017-02-01", grantee="MUDD FRANCIS", xrefs=["2008500000"])
    recs = [mtg, _rec("WARRANTY DEED", instnum="2005000001", grantee="MUDD FRANCIS"), rel]
    n = _notice(360000, decedent_name="MUDD FRANCIS")
    estimate_equity(n, records=recs)
    assert n.lien_flags == "", f"expected no flags, got {n.lien_flags!r}"
    assert n.equity_percent == "100.0", n.equity_percent
    print("PASS: test_mudd_francis_hidden_release")


# ── Medicaid / MERP — Duckworth (DMS party) / Underwood (elder-law attorney) ─
def test_duckworth_medicaid_dms():
    n = _notice(250000, decedent_name="DUCKWORTH CHRISTINE",
                courtnet_party_types="P|AP|DMS")
    recs = [_rec("WARRANTY DEED", grantee="DUCKWORTH CHRISTINE")]  # clean otherwise
    estimate_equity(n, records=recs)
    assert "medicaid" in n.lien_flags, n.lien_flags
    assert float(n.equity_percent) < 100, n.equity_percent  # invariant: no dollar lien, still < 100
    print("PASS: test_duckworth_medicaid_dms")


def test_underwood_medicaid_elder_law():
    n = _notice(180000, decedent_name="UNDERWOOD KAREN",
                estate_attorney_name="Linda Bullock, KY Elder Law")
    recs = [_rec("WARRANTY DEED", grantee="UNDERWOOD KAREN")]
    estimate_equity(n, records=recs)
    assert "medicaid" in n.lien_flags, n.lien_flags
    assert float(n.equity_percent) < 100, n.equity_percent
    print("PASS: test_underwood_medicaid_elder_law")


# ── Genuine clean free-and-clear ──────────────────────────────────────────
def test_clean_free_and_clear():
    # Mortgage records present but ALL released, no liens, no Medicaid signal.
    mtg = _rec("MORTGAGE", instnum="2010100000", year="2010", filed_date="2010-01-01",
               grantee="OLD BANK", amount="150000")
    rel = _rec("REL MTG", instnum="2020200000", year="2020", xrefs=["2010100000"])
    deed = _rec("WARRANTY DEED", instnum="2005000001", grantee="SMITH CLEAN")
    n = _notice(225000, decedent_name="SMITH CLEAN")
    estimate_equity(n, records=[deed, mtg, rel])
    assert n.lien_flags == "", f"expected no flags, got {n.lien_flags!r}"
    assert n.equity_percent == "100.0", n.equity_percent
    print("PASS: test_clean_free_and_clear")


# ── Invariant: never 100% when any flag is set ────────────────────────────
def test_invariant_never_full_when_flagged():
    cases = [
        ("WHEATLEY HECM", _notice(300000), [_rec("MORTGAGE", grantee="REVERSE MORTGAGE", amount="100000")]),
        ("LOGSDON LIEN", _notice(200000), [_rec("STATE LIEN", grantor="X", grantee="KY DOR", amount="5000")]),
        ("DUCKWORTH MEDICAID", _notice(150000, courtnet_party_types="DMS"), [_rec("WARRANTY DEED")]),
        ("UNKNOWN HECM", _notice(400000), [_rec("HECM", grantee="FINANCIAL FREEDOM")]),
    ]
    for label, n, recs in cases:
        estimate_equity(n, records=recs)
        assert n.lien_flags != "", f"{label}: expected a flag"
        assert not (n.lien_flags and n.equity_percent == "100.0"), \
            f"{label}: flagged record read 100%! flags={n.lien_flags} pct={n.equity_percent}"
        assert float(n.equity_percent) < 100, f"{label}: pct={n.equity_percent}"
    print("PASS: test_invariant_never_full_when_flagged")


# ── _classify_lien unit ───────────────────────────────────────────────────
def test_classify_lien_unit():
    assert _classify_lien("MORTGAGE", "HECM REVERSE") == "hecm"
    assert _classify_lien("MORTGAGE", "FINANCIAL FREEDOM") == "hecm"
    assert _classify_lien("STATE LIEN", "KY DEPT OF REVENUE") == "judgment"
    assert _classify_lien("JUDGMENT", "") == "judgment"
    assert _classify_lien("LIS PENDENS", "") == "lis_pendens"
    assert _classify_lien("CERTIFICATE OF DELINQUENCY", "") == "tax_cert"
    assert _classify_lien("CODE ENFORCEMENT LIEN", "") == "tax_cert"
    assert _classify_lien("WARRANTY DEED", "SMITH JOHN") == ""
    assert _classify_lien("", "") == ""
    print("PASS: test_classify_lien_unit")


def test_has_medicaid_signal_unit():
    assert _has_medicaid_signal(_notice(100000, courtnet_party_types="P|AP|DMS")) is True
    assert _has_medicaid_signal(_notice(100000, estate_attorney_name="Jane KY Elder Law")) is True
    assert _has_medicaid_signal(_notice(100000, estate_attorney_name="Linda Bullock")) is True
    assert _has_medicaid_signal(_notice(100000, courtnet_party_types="P|AP|EE")) is False
    assert _has_medicaid_signal(_notice(100000)) is False
    print("PASS: test_has_medicaid_signal_unit")


# ── Safety: malformed record must not crash ───────────────────────────────
def test_malformed_record_no_crash():
    n = _notice(100000, decedent_name="GARBAGE TEST")
    bad = _rec("@@@###$$$", instnum="", filed_date="not-a-date", amount="$$$")
    # Must not raise; produces a non-crashing result.
    result = estimate_equity(n, records=[bad])
    assert isinstance(result, bool)
    # equity_percent should be a parseable float string (or empty if it bailed).
    if n.equity_percent:
        float(n.equity_percent)
    print("PASS: test_malformed_record_no_crash")


# ── _net_encumbrances direct unit (pure, no network) ──────────────────────
def test_net_encumbrances_pure():
    n = _notice(100000)
    haircut, flags = _net_encumbrances(
        n,
        [_rec("STATE LIEN", grantor="X", grantee="KY DOR", amount="10000")],
        100000.0,
    )
    assert haircut == 10000, haircut
    assert flags == ["judgment"], flags
    print("PASS: test_net_encumbrances_pure")


if __name__ == "__main__":
    test_wheatley_hecm()
    test_herflicker_hecm()
    test_presley_junior_liens()
    test_logsdon_state_liens()
    test_walker_tax_code_negative()
    test_thompson_hale_negative()
    test_murphy_hidden_release()
    test_mudd_francis_hidden_release()
    test_duckworth_medicaid_dms()
    test_underwood_medicaid_elder_law()
    test_clean_free_and_clear()
    test_invariant_never_full_when_flagged()
    test_classify_lien_unit()
    test_has_medicaid_signal_unit()
    test_malformed_record_no_crash()
    test_net_encumbrances_pure()
    print("\nALL TESTS PASSED")
