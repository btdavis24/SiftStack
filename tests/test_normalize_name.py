"""Network-free tests for jefferson_deeds_scraper._normalize_name.

Regression context: in the 2026-05-27 Apify run, the LP record for
'ATKINSON SAMPLE GWENDOLYN' arrived at PVA lookup as 'Sample Atkinson' —
GWENDOLYN was silently dropped by _normalize_name, which only returned
parts[1] + parts[0] for 3+ token inputs. PVA stores her as
'ATKINSON SAMPLE GWENDOLYN' so the variants generator (which builds
LAST/FIRST permutations from the supplied owner_name) never produced a
matching query → 51 same-name parcels declined.

Fix preserves middle name(s) and handles JR/SR/II/III/IV suffix by moving
it to natural-order tail position.

Run:  python tests/test_normalize_name.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from jefferson_deeds_scraper import _normalize_name  # noqa: E402


# ── 3-token names: the main bug fix ───────────────────────────────────────
def test_atkinson_pattern_preserves_middle():
    """The 2026-05-27 ATKINSON SAMPLE GWENDOLYN case."""
    assert _normalize_name("ATKINSON SAMPLE GWENDOLYN") == "Sample Gwendolyn Atkinson"
    print("PASS: test_atkinson_pattern_preserves_middle")


def test_blevins_pattern_preserves_middle():
    """Today's BLEVINS WILLIAM PATRICK case (probate path, but same parser)."""
    assert _normalize_name("BLEVINS WILLIAM PATRICK") == "William Patrick Blevins"
    print("PASS: test_blevins_pattern_preserves_middle")


def test_harvey_deborah_lee():
    assert _normalize_name("HARVEY DEBORAH LEE") == "Deborah Lee Harvey"
    print("PASS: test_harvey_deborah_lee")


def test_acosta_compound_first_name():
    """Joint-name LP — ACOSTA GEORGENIS HERNANDEZ. JCD format treats
    everything after surname as first/middle, so HERNANDEZ becomes a middle
    name. This preserves token order even when the 'middle' is actually a
    maiden or compound surname element."""
    assert _normalize_name("ACOSTA GEORGENIS HERNANDEZ") == "Georgenis Hernandez Acosta"
    print("PASS: test_acosta_compound_first_name")


# ── Suffix handling ───────────────────────────────────────────────────────
def test_suffix_jr_moves_to_end():
    assert _normalize_name("SMITH JOHN JR") == "John Smith Jr"
    print("PASS: test_suffix_jr_moves_to_end")


def test_suffix_with_middle_name():
    assert _normalize_name("SMITH JOHN PAUL JR") == "John Paul Smith Jr"
    print("PASS: test_suffix_with_middle_name")


def test_suffix_iii_moves_to_end():
    assert _normalize_name("BAKER FLOYD S III") == "Floyd S Baker III"
    print("PASS: test_suffix_iii_moves_to_end")


def test_suffix_sr_moves_to_end():
    assert _normalize_name("DOE JANE MARIE SR") == "Jane Marie Doe Sr"
    print("PASS: test_suffix_sr_moves_to_end")


def test_suffix_ii_moves_to_end():
    """COPLEY ROBERT W II — middle initial + Roman numeral suffix."""
    assert _normalize_name("COPLEY ROBERT W II") == "Robert W Copley II"
    print("PASS: test_suffix_ii_moves_to_end")


def test_surname_plus_suffix_only():
    """Pathological edge: 'SMITH JR' with no first name — keep both tokens."""
    assert _normalize_name("SMITH JR") == "Jr Smith"
    # Note: the 2-token path returns parts[1] parts[0] = "Jr Smith".
    # Not aesthetically ideal but preserves all input. The 3+ token path
    # only fires for true 3+ inputs.
    print("PASS: test_surname_plus_suffix_only")


# ── 1- and 2-token names (unchanged behavior) ─────────────────────────────
def test_single_token_unchanged():
    assert _normalize_name("JONES") == "Jones"
    print("PASS: test_single_token_unchanged")


def test_two_token_swaps():
    """LAST FIRST → Firstname Lastname."""
    assert _normalize_name("BAKER FLOYD") == "Floyd Baker"
    assert _normalize_name("DOMINGUEZ DANIEL") == "Daniel Dominguez"
    print("PASS: test_two_token_swaps")


def test_blank_string_returns_empty():
    assert _normalize_name("") == ""
    assert _normalize_name("   ") == ""
    print("PASS: test_blank_string_returns_empty")


# ── Entity-name passthrough (unchanged) ───────────────────────────────────
def test_bank_entity_unchanged():
    assert _normalize_name("WELLS FARGO BANK NA") == "Wells Fargo Bank Na"
    print("PASS: test_bank_entity_unchanged")


def test_llc_entity_unchanged():
    assert _normalize_name("LAWHORN REMODELING LLC") == "Lawhorn Remodeling Llc"
    print("PASS: test_llc_entity_unchanged")


def test_government_entity_unchanged():
    assert _normalize_name("COMMONWEALTH OF KENTUCKY") == "Commonwealth Of Kentucky"
    assert _normalize_name("UNITED STATES OF AMERICA") == "United States Of America"
    print("PASS: test_government_entity_unchanged")


def test_inc_entity_unchanged():
    assert _normalize_name("ABC HOLDINGS INC") == "Abc Holdings Inc"
    print("PASS: test_inc_entity_unchanged")


# ── 4+ token names ────────────────────────────────────────────────────────
def test_four_tokens_no_suffix():
    """Four real name tokens, no suffix — preserves all."""
    assert _normalize_name("DOZIER DIEGO DION TRAYNOR") == "Diego Dion Traynor Dozier"
    print("PASS: test_four_tokens_no_suffix")


def test_five_tokens_with_suffix():
    """Long name with JR suffix."""
    assert _normalize_name("WHEATLEY MARY ELLEN JANE JR") == "Mary Ellen Jane Wheatley Jr"
    print("PASS: test_five_tokens_with_suffix")


# ── PVA query contract: ensure the LP-resolution path works ───────────────
def test_atkinson_round_trip_preserves_pva_searchable_form():
    """The whole point of the fix: after normalization, the resulting name
    string contains all tokens needed to re-form a PVA query that hits
    'ATKINSON SAMPLE GWENDOLYN'. Tokens are preserved; the variants
    generator downstream will produce a LAST FIRST [MIDDLE] permutation."""
    result = _normalize_name("ATKINSON SAMPLE GWENDOLYN")
    tokens_upper = {t.upper() for t in result.split()}
    assert "ATKINSON" in tokens_upper
    assert "SAMPLE" in tokens_upper
    assert "GWENDOLYN" in tokens_upper
    print("PASS: test_atkinson_round_trip_preserves_pva_searchable_form")


if __name__ == "__main__":
    test_atkinson_pattern_preserves_middle()
    test_blevins_pattern_preserves_middle()
    test_harvey_deborah_lee()
    test_acosta_compound_first_name()
    test_suffix_jr_moves_to_end()
    test_suffix_with_middle_name()
    test_suffix_iii_moves_to_end()
    test_suffix_sr_moves_to_end()
    test_suffix_ii_moves_to_end()
    test_surname_plus_suffix_only()
    test_single_token_unchanged()
    test_two_token_swaps()
    test_blank_string_returns_empty()
    test_bank_entity_unchanged()
    test_llc_entity_unchanged()
    test_government_entity_unchanged()
    test_inc_entity_unchanged()
    test_four_tokens_no_suffix()
    test_five_tokens_with_suffix()
    test_atkinson_round_trip_preserves_pva_searchable_form()
    print("\nALL PASS: normalize_name")
