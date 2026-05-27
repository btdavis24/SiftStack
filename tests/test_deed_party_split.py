"""Network-free tests for the multi-grantor party splitter in
heir_identifier._split_deed_parties.

Regression context: JCD's dlist.php renders multi-party grantor/grantee
cells with HTML structural separators (`<br>`, `<div>`) that
BeautifulSoup's `get_text(" ")` collapses to plain spaces — producing
strings like `"HUPP CATHY HUPP PAUL E JR"` (2 people) or, worst case,
`"STITH PEGGY ROSE STITH RAYMOND OHARA JAMES ..."` (9+ people).

Before this fix, the heir builder treated each such string as a single
person, producing malformed heir_map_json entries flagged for manual
review but unusable for DM identification. The new
`_split_concatenated_jcd_parties` algorithm uses suffix anchoring + the
first token as surname markers to detect party boundaries.

Run:  python tests/test_deed_party_split.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from heir_identifier import (  # noqa: E402
    _split_concatenated_jcd_parties,
    _split_deed_parties,
)


# ── _split_concatenated_jcd_parties — direct unit tests ───────────────────
def test_hupp_pattern_splits_on_repeated_surname():
    """The 2026-05-27 HUPP case: surname repeats, suffix terminates party 2."""
    result = _split_concatenated_jcd_parties("HUPP CATHY HUPP PAUL E JR")
    assert result == ["HUPP CATHY", "HUPP PAUL E JR"], result
    print("PASS: test_hupp_pattern_splits_on_repeated_surname")


def test_walker_pattern_splits_on_repeated_surname():
    """Classic two-spouse pattern without an explicit `&` separator."""
    result = _split_concatenated_jcd_parties("WALKER EARL WALKER BERTHA")
    assert result == ["WALKER EARL", "WALKER BERTHA"], result
    print("PASS: test_walker_pattern_splits_on_repeated_surname")


def test_stith_pattern_via_suffix_anchor():
    """The 2026-05-27 STITH case: 19 tokens, JR appears twice. Each JR
    anchors the next token as a new surname (OHARA both times). Plus the
    first-token surname (STITH) marks STITH party boundaries."""
    s = ("STITH PEGGY ROSE STITH RAYMOND OHARA JAMES RAYMOND OHARA DORIS "
         "OHARA JOHN FRANCIS JR OHARA ESTHER OHARA JAMES R OHARA DORIS J "
         "OHARA JOHN F JR OHARA ESTHER E")
    result = _split_concatenated_jcd_parties(s)
    # Expected boundaries (from the suffix-anchored algorithm):
    expected = [
        "STITH PEGGY ROSE",
        "STITH RAYMOND",
        "OHARA JAMES RAYMOND",
        "OHARA DORIS",
        "OHARA JOHN FRANCIS JR",
        "OHARA ESTHER",
        "OHARA JAMES R",
        "OHARA DORIS J",
        "OHARA JOHN F JR",
        "OHARA ESTHER E",
    ]
    assert result == expected, f"\nGOT: {result}\nWANT: {expected}"
    print("PASS: test_stith_pattern_via_suffix_anchor")


def test_single_name_with_suffix_not_split():
    """A bare single name like BAKER FLOYD JR must NOT be over-split."""
    result = _split_concatenated_jcd_parties("BAKER FLOYD JR")
    # JR terminates the only party; nothing follows. Result is one entry.
    assert result == ["BAKER FLOYD JR"], result
    print("PASS: test_single_name_with_suffix_not_split")


def test_single_name_two_tokens_not_split():
    """LAST FIRST (2 tokens) — one party, no split possible."""
    result = _split_concatenated_jcd_parties("WALKER EARL")
    assert result == ["WALKER EARL"], result
    print("PASS: test_single_name_two_tokens_not_split")


def test_single_name_three_tokens_not_split():
    """LAST FIRST MIDDLE (3 tokens) — one party."""
    result = _split_concatenated_jcd_parties("WALKER EARL THOMAS")
    assert result == ["WALKER EARL THOMAS"], result
    print("PASS: test_single_name_three_tokens_not_split")


def test_empty_string_returns_empty():
    assert _split_concatenated_jcd_parties("") == []
    assert _split_concatenated_jcd_parties("   ") == []
    print("PASS: test_empty_string_returns_empty")


def test_undetectable_two_distinct_surnames_returns_unsplit():
    """The MIDDLETON case: two parties, neither surname repeats and there's
    no suffix. The algorithm CAN'T detect the boundary — it returns one
    string. This documents the limitation."""
    result = _split_concatenated_jcd_parties("SMITH JOHN JONES JANE")
    # Documents the limitation, doesn't try to detect.
    assert result == ["SMITH JOHN JONES JANE"], result
    print("PASS: test_undetectable_two_distinct_surnames_returns_unsplit")


# ── _split_deed_parties — full pipeline (separator + concatenation) ───────
def test_explicit_ampersand_separator_still_works():
    """Backwards compat: WALKER EARL & WALKER BERTHA (with `&`) still
    splits cleanly via the existing separator pass."""
    result = _split_deed_parties("WALKER EARL & WALKER BERTHA")
    assert result == ["WALKER EARL", "WALKER BERTHA"], result
    print("PASS: test_explicit_ampersand_separator_still_works")


def test_explicit_semicolon_separator_still_works():
    """Backwards compat: MCGARVEY KEVIN; MCGARVEY SHEILA still works."""
    result = _split_deed_parties("MCGARVEY KEVIN; MCGARVEY SHEILA")
    assert result == ["MCGARVEY KEVIN", "MCGARVEY SHEILA"], result
    print("PASS: test_explicit_semicolon_separator_still_works")


def test_concatenated_walker_now_splits():
    """The bug fix: WALKER EARL WALKER BERTHA (no `&`) now splits via the
    JCD concatenation pass."""
    result = _split_deed_parties("WALKER EARL WALKER BERTHA")
    assert result == ["WALKER EARL", "WALKER BERTHA"], result
    print("PASS: test_concatenated_walker_now_splits")


def test_entity_filter_drops_business_grantors():
    """Banks, LLCs, ESTATE OF ... still get filtered."""
    result = _split_deed_parties("WALKER EARL & WELLS FARGO BANK NA")
    assert result == ["WALKER EARL"], result  # bank dropped
    print("PASS: test_entity_filter_drops_business_grantors")


def test_dedup_preserves_order():
    """If the same name appears twice (e.g. via concatenation matching the
    explicit-separator output), dedup keeps the first occurrence."""
    result = _split_deed_parties("WALKER EARL & WALKER EARL")
    assert result == ["WALKER EARL"], result
    print("PASS: test_dedup_preserves_order")


def test_short_single_name_not_split_by_concat_pass():
    """3-token names skip the concat splitter entirely (token_count < 4)."""
    result = _split_deed_parties("WALKER EARL JR")
    assert result == ["WALKER EARL JR"], result
    print("PASS: test_short_single_name_not_split_by_concat_pass")


def test_hupp_pattern_via_public_api():
    """End-to-end: the actual 2026-05-27 HUPP case in production."""
    result = _split_deed_parties("HUPP CATHY HUPP PAUL E JR")
    assert result == ["HUPP CATHY", "HUPP PAUL E JR"], result
    print("PASS: test_hupp_pattern_via_public_api")


def test_max_deed_heirs_cap_still_enforced():
    """The output is capped at _MAX_DEED_HEIRS (25) to prevent runaway."""
    from heir_identifier import _MAX_DEED_HEIRS
    # Build a string with 50 unique parties (each "LAST<i> FIRST<i>").
    parties = " ".join(f"SURNAME{i} FIRST{i} SR" for i in range(50))
    result = _split_deed_parties(parties)
    assert len(result) <= _MAX_DEED_HEIRS, len(result)
    print("PASS: test_max_deed_heirs_cap_still_enforced")


if __name__ == "__main__":
    test_hupp_pattern_splits_on_repeated_surname()
    test_walker_pattern_splits_on_repeated_surname()
    test_stith_pattern_via_suffix_anchor()
    test_single_name_with_suffix_not_split()
    test_single_name_two_tokens_not_split()
    test_single_name_three_tokens_not_split()
    test_empty_string_returns_empty()
    test_undetectable_two_distinct_surnames_returns_unsplit()
    test_explicit_ampersand_separator_still_works()
    test_explicit_semicolon_separator_still_works()
    test_concatenated_walker_now_splits()
    test_entity_filter_drops_business_grantors()
    test_dedup_preserves_order()
    test_short_single_name_not_split_by_concat_pass()
    test_hupp_pattern_via_public_api()
    test_max_deed_heirs_cap_still_enforced()
    print("\nALL PASS: deed_party_split")
