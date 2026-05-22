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

from kentucky_name_resolver import (
    name_tokens,
    score_match,
    _search_variations,
    generate_variants,
    disambiguate,
    CandidatePerson,
)


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


# ── generate_variants case fixtures (spec task 2e-2 / NAME-01) ──────────
# One assertion-bearing fixture per cited case from CONTEXT / lessons.


def test_variants_greathouse_maiden():
    # Jackson titled, but property is under maiden GREATHOUSE (0 rows under
    # JACKSON). The maiden_obit variant must appear AND outrank maiden_positional.
    vs = generate_variants("Dorothy Emma Greathouse Jackson", maiden_name="Greathouse")
    obit = [v for v in vs if v.source == "maiden_obit"]
    assert obit, f"no maiden_obit variant: {vs}"
    assert any("GREATHOUSE DOROTHY" in v.value for v in obit), obit
    obit_conf = obit[0].confidence
    # When maiden is supplied, positional is suppressed; but the obit confidence
    # must still rank above any positional confidence (locked D-02).
    pos = [v for v in vs if v.source == "maiden_positional"]
    assert all(obit_conf >= v.confidence for v in pos), (obit_conf, pos)
    print("PASS: variants Greathouse maiden_obit present + ranked above positional")


def test_variants_underwood_three_surnames():
    # Underwood -> Koenig -> Price: each prior surname yields a prior_married variant.
    vs = generate_variants("Mary Underwood", prior_surnames=["Koenig", "Price"])
    pm = [v for v in vs if v.source == "prior_married"]
    assert any(v.value.startswith("KOENIG ") for v in pm), pm
    assert any(v.value.startswith("PRICE ") for v in pm), pm
    print("PASS: variants Underwood 3-surname prior_married (Koenig, Price)")


def test_variants_farinas_dual_surname():
    # Hispanic paternal+maternal: García AND Fariñas both get a variant.
    vs = generate_variants("Celestino Garcia Farinas")
    vals = [v.value for v in vs]
    assert any("GARCIA" in v for v in vals), vals
    assert any("FARINAS" in v for v in vals), vals
    # A plain 2-token FIRST LAST name must NOT spuriously double via non_anglo.
    plain = generate_variants("John Smith")
    assert not any(v.source == "non_anglo_surname" for v in plain), plain
    print("PASS: variants Farinas dual surname (GARCIA + FARINAS); 2-token no double")


def test_variants_lozinskaya_feminization():
    # Slavic feminization: LOZINSKAYA -> masculine LOZINSKIY.
    vs = generate_variants("Olga Lozinskaya")
    assert any("LOZINSKIY" in v.value for v in vs), vs
    print("PASS: variants Lozinskaya feminization (-AYA -> -IY)")


def test_variants_palmerball_hyphen_split():
    # Hyphenated surname: full PALMER-BALL + each half PALMER and BALL all present.
    vs = generate_variants("Anne Palmer-Ball")
    vals = [v.value for v in vs]
    assert any("PALMER-BALL ANNE" == v for v in vals), vals
    assert any(v.startswith("PALMER ") for v in vals), vals
    # BALL ANNE may be claimed by the higher-confidence primary source after
    # dedup (last-token surname) — assert on the value, not the source label.
    assert any(v == "BALL ANNE" for v in vals), vals
    # Gonzalez-Gonzalez collapses to ONE surname (sibling cohort, not a typo).
    gg = generate_variants("Caridad Gonzalez-Gonzalez")
    assert any("GONZALEZ-GONZALEZ CARIDAD" == v.value for v in gg), gg
    print("PASS: variants Palmer-Ball hyphen split (full + halves); GG one surname")


def test_variants_suffix_stripped():
    # A III/JR name still produces primary variants with the suffix stripped.
    vs = generate_variants("Richard Owen Lewis III")
    assert all("III" not in v.value for v in vs), vs
    assert any(v.source == "primary" for v in vs), vs
    print("PASS: variants suffix III stripped from primary")


def test_variants_fuzzy_gate():
    # D-04: fuzzy off by default == no typo_fuzzy; identical to no-flag call.
    assert generate_variants("John Smith", enable_fuzzy=False) == generate_variants("John Smith")
    # enable_fuzzy=True: Levenshtein<=1 TOMPSON->THOMPSON accepted...
    tom = generate_variants("John Tompson", enable_fuzzy=True)
    assert any(v.source == "typo_fuzzy" for v in tom), tom
    # ...but distance-2 MEIER->MILLER is NEVER caught.
    mei = generate_variants("Frank Meier", enable_fuzzy=True)
    assert not any(v.source == "typo_fuzzy" and "MILLER" in v.value for v in mei), mei
    print("PASS: variants fuzzy gate (off by default; TOMPSON yes, MEIER!=MILLER)")


# ── disambiguate case fixtures (spec task 2e-3 / NAME-02) ───────────────


def test_disambiguate_dead_spouse_dropped():
    # Davis: husband d.2012 — a dod-set candidate is never returned (death guard).
    r = disambiguate("Barry Davis", [CandidatePerson(name="Barry Davis", dod="2012-04-06")])
    assert r is None, r
    print("PASS: disambiguate dead-spouse dropped (Davis husband d.2012 -> None)")


def test_disambiguate_armstrong_wrong_age():
    # Armstrong wrong-Barry age 80 vs an expected younger decedent -> not selected.
    cands = [CandidatePerson(name="Barry Armstrong", age=80)]
    r = disambiguate("Barry Armstrong", cands, expected_dod="2026-04-12", expected_age=55)
    assert r is None, r
    print("PASS: disambiguate Armstrong wrong-age (80 vs ~55) -> None")


def test_disambiguate_three_thomas_shavers():
    # 3 same-name Thomas Shavers; only one overlaps the decedent's parcel -> wins.
    shavers = [
        CandidatePerson(name="Thomas Shaver", addresses=["1234 Other St"]),
        CandidatePerson(name="Thomas Shaver", addresses=["4502 Brownsboro Rd, Louisville KY"]),
        CandidatePerson(name="Thomas Shaver", addresses=["9999 Elsewhere Ave"]),
    ]
    r = disambiguate("Thomas Shaver", shavers, known_addresses=["4502 Brownsboro Rd"])
    assert r is not None, "corroborated Shaver should win"
    assert r.score >= 0.6, r.score
    assert "4502" in r.person.addresses[0], r.person
    assert "address overlap" in r.reason, r.reason
    print("PASS: disambiguate 3 Thomas Shavers (parcel overlap wins, score>=0.6)")


def test_disambiguate_below_threshold_returns_none():
    # Two uncorroborated near-ties -> None (manual queue), never auto-attach.
    cands = [
        CandidatePerson(name="Thomas Shaver"),
        CandidatePerson(name="Thomas Shaver"),
    ]
    r = disambiguate("Thomas Shaver", cands)
    assert r is None, r
    print("PASS: disambiguate uncorroborated tie -> None (manual queue)")


# ── Runner ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Golden behavior-preservation (Plan 01)
    test_name_tokens_strips_suffix_and_short()
    test_variations_comma_format()
    test_variations_natural_equals_comma()
    test_score_surname_only()
    test_score_full_adjacent()
    test_score_business_penalty()
    test_score_no_surname_zero()
    # generate_variants case fixtures (Plan 02, task 2e-2)
    test_variants_greathouse_maiden()
    test_variants_underwood_three_surnames()
    test_variants_farinas_dual_surname()
    test_variants_lozinskaya_feminization()
    test_variants_palmerball_hyphen_split()
    test_variants_suffix_stripped()
    test_variants_fuzzy_gate()
    # disambiguate case fixtures (Plan 02, task 2e-3)
    test_disambiguate_dead_spouse_dropped()
    test_disambiguate_armstrong_wrong_age()
    test_disambiguate_three_thomas_shavers()
    test_disambiguate_below_threshold_returns_none()
    print("\nAll name_resolver tests passed (golden + variant + disambiguate).")
