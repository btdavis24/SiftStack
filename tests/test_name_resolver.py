"""Golden behavior-preservation tests for kentucky_name_resolver primitives.

Locks the LEGACY behavior of the name primitives promoted out of
kentucky_pva_lookup (spec task 2e-1) so the extraction is provably
behavior-preserving and Plan 02 has a regression baseline before it adds
variant sources.

Standalone script (per .planning/codebase/TESTING.md) — NOT pytest.
Run: python tests/test_name_resolver.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from kentucky_name_resolver import name_tokens, score_match, _search_variations


# ── name_tokens ────────────────────────────────────────────────────────

def test_name_tokens_strips_suffix_and_short():
    # JR suffix dropped, comma punctuation removed, uppercased, len>1 only.
    assert name_tokens("EWING, WELDON GENE JR") == ["EWING", "WELDON", "GENE"], \
        f"Got: {name_tokens('EWING, WELDON GENE JR')}"
    # ESQ suffix + a 1-char token are both dropped.
    assert name_tokens("smith j esq") == ["SMITH"], f"Got: {name_tokens('smith j esq')}"
    print("PASS: name_tokens strips suffix + short tokens, uppercases")


# ── _search_variations ─────────────────────────────────────────────────

def test_variations_comma_format():
    got = _search_variations("ROLAND, WELDON GENE")
    assert got == [
        "ROLAND WELDON",
        "ROLAND WELDON GENE",
        "ESTATE OF ROLAND WELDON",
        "ESTATE OF ROLAND WELDON GENE",
    ], f"Got: {got}"
    print("PASS: _search_variations comma format -> LAST FIRST / +MIDDLE / ESTATE OF ...")


def test_variations_natural_equals_comma():
    comma = _search_variations("ROLAND, WELDON GENE")
    natural = _search_variations("WELDON GENE ROLAND")
    assert natural == comma, f"natural={natural} comma={comma}"
    print("PASS: _search_variations natural order == comma order")


# ── score_match ────────────────────────────────────────────────────────

def test_score_surname_only():
    # Comma format ("SMITH, JOHN") => surname is SMITH (first token); JANE shares
    # only the surname, no first-name bonus => base 0.5.
    s = score_match("SMITH, JOHN", "SMITH JANE")
    assert abs(s - 0.5) < 1e-9, f"Got: {s}"
    print("PASS: score_match surname-only == 0.5")


def test_score_full_adjacent():
    s = score_match("ROLAND, WELDON GENE", "ROLAND WELDON GENE")
    assert s >= 0.85, f"Got: {s}"
    print("PASS: score_match full adjacent >= 0.85")


def test_score_business_penalty():
    # Business-entity tokens (TRUST/LLC) apply a penalty, so a match buried in a
    # business string scores lower than a clean person-to-person match.
    biz = score_match("SMITH, JOHN", "SMITH JOHN TRUST LLC")
    clean = score_match("SMITH, JOHN", "SMITH JOHN")
    assert biz < clean, f"biz={biz} clean={clean}"
    print("PASS: score_match business penalty (biz < clean)")


def test_score_no_surname_zero():
    s = score_match("SMITH JOHN", "EASTSIDE REAL ESTATE LLC")
    assert s == 0.0, f"Got: {s}"
    print("PASS: score_match no surname overlap == 0.0")


# ── Runner ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    test_name_tokens_strips_suffix_and_short()
    test_variations_comma_format()
    test_variations_natural_equals_comma()
    test_score_surname_only()
    test_score_full_adjacent()
    test_score_business_penalty()
    test_score_no_surname_zero()
    print("\nAll name_resolver golden tests passed.")
