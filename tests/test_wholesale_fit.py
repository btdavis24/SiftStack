"""Unit tests for the wholesale-fit scorer (Phase 4 / src/wholesale_fit.py).

Each test is one of the locked case fixtures from
.planning/phases/04-wholesale-fit-gate/04-01-PLAN.md (<behavior> table). They prove
the FIXED scoring rules: hard-drops (no_property / out_of_estate / negative_equity /
teardown), soft-demotions (luxury kept-but-low, sophisticated DM lowered), a clean
mid-value high score, and distress RAISING the score (locked decision 2).

Standalone script per the codebase test style (TESTING.md): no pytest, bare
test_*() functions, assert + print("PASS"), run via `python tests/test_wholesale_fit.py`.
A failing assert exits non-zero; all-pass exits 0.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from notice_parser import NoticeData
from wholesale_fit import FitResult, score_wholesale_fit


def _clean_workable(**overrides) -> NoticeData:
    """A clean, free-and-clear, mid-value probate with a real DM — the baseline
    that soft-demotions and distress are measured against."""
    base = dict(
        notice_type="probate",
        title_path="standard_probate",
        estimated_value="245000",
        equity_percent="100",
        decision_maker_name="Jane Smith",
    )
    base.update(overrides)
    return NoticeData(**base)


# ── HARD DROPS ────────────────────────────────────────────────────────


def test_hard_drop_no_property():
    """Humphrey: decedent owned no Jefferson real estate → title_path=no_property."""
    n = _clean_workable(title_path="no_property")
    r = score_wholesale_fit(n)
    assert isinstance(r, FitResult), f"Got: {type(r)}"
    assert r.drop is True, f"Got drop={r.drop}"
    assert r.score == 0, f"Got score={r.score}"
    assert r.reason == "no_property", f"Got reason={r.reason!r}"
    print("PASS: hard_drop no_property (Humphrey) -> drop, score 0")


def test_hard_drop_out_of_estate():
    """Bell / Caffee: property already out of the estate (deeded pre-death)."""
    n = _clean_workable(title_path="out_of_estate")
    r = score_wholesale_fit(n)
    assert r.drop is True, f"Got drop={r.drop}"
    assert r.score == 0, f"Got score={r.score}"
    assert r.reason == "out_of_estate", f"Got reason={r.reason!r}"
    print("PASS: hard_drop out_of_estate (Bell/Caffee) -> drop, score 0")


def test_hard_drop_negative_equity():
    """Jackson-Lorene: 100% LTV — equity floor + active senior mortgage."""
    n = _clean_workable(
        equity_percent="0",
        estimated_value="180000",
        mortgage_balance_estimate="180000",
    )
    r = score_wholesale_fit(n)
    assert r.drop is True, f"Got drop={r.drop}"
    assert r.score == 0, f"Got score={r.score}"
    assert r.reason == "negative_equity", f"Got reason={r.reason!r}"
    print("PASS: hard_drop negative_equity (Jackson-Lorene 100% LTV) -> drop, score 0")


def test_hard_drop_teardown():
    """Cooper / Dorsey: $5K vacant lot below WHOLESALE_MIN_VALUE + teardown signal."""
    n = _clean_workable(
        estimated_value="5000",
        equity_percent="100",
        property_type="vacant lot",
        bedrooms="",
        sqft="",
    )
    r = score_wholesale_fit(n)
    assert r.drop is True, f"Got drop={r.drop}"
    assert r.reason == "teardown", f"Got reason={r.reason!r}"
    print("PASS: hard_drop teardown ($5K vacant lot) -> drop")


def test_cheap_but_real_house_not_dropped():
    """Conservative teardown gate: a cheap-but-REAL house (has beds + sqft) below
    min value must NOT be a hard drop — only vacant-lot/teardown signals trigger it."""
    n = _clean_workable(
        estimated_value="25000",
        equity_percent="100",
        property_type="Single Family",
        bedrooms="3",
        sqft="980",
    )
    r = score_wholesale_fit(n)
    assert r.drop is False, f"Got drop={r.drop} reason={r.reason!r}"
    print("PASS: cheap-but-real house below min value -> kept (not teardown)")


# ── SOFT DEMOTIONS (KEPT) ─────────────────────────────────────────────


def test_soft_demote_luxury_kept_low():
    """Atlas $1.7M: above WHOLESALE_MAX_VALUE → kept, reason contains 'luxury',
    score strictly below a clean mid-value baseline."""
    luxury = _clean_workable(
        estimated_value="1720000",
        title_path="successor_trustee",
    )
    baseline = _clean_workable()  # clean mid-value, same equity
    r_lux = score_wholesale_fit(luxury)
    r_base = score_wholesale_fit(baseline)
    assert r_lux.drop is False, f"Got drop={r_lux.drop}"
    assert "luxury" in r_lux.reason, f"Got reason={r_lux.reason!r}"
    assert r_lux.score < r_base.score, f"luxury {r_lux.score} not < baseline {r_base.score}"
    print(
        f"PASS: soft_demote luxury (Atlas $1.7M) -> kept, score {r_lux.score} "
        f"< baseline {r_base.score}"
    )


def test_soft_demote_sophisticated_dm():
    """Williams (RIA) / Zacharias: dm_sophisticated=yes → kept, score lowered vs
    the same record WITHOUT the flag."""
    soph = _clean_workable(dm_sophisticated="yes")
    plain = _clean_workable()
    r_soph = score_wholesale_fit(soph)
    r_plain = score_wholesale_fit(plain)
    assert r_soph.drop is False, f"Got drop={r_soph.drop}"
    assert "sophisticated" in r_soph.reason, f"Got reason={r_soph.reason!r}"
    assert r_soph.score < r_plain.score, (
        f"sophisticated {r_soph.score} not < plain {r_plain.score}"
    )
    print(
        f"PASS: soft_demote sophisticated DM (Williams RIA) -> kept, "
        f"score {r_soph.score} < plain {r_plain.score}"
    )


def test_soft_demote_entity_type():
    """entity_type set (LLC/trust/corp) is the v1 proxy for a sophisticated seller
    even without the manual flag → kept, lowered."""
    ent = _clean_workable(entity_type="llc")
    plain = _clean_workable()
    r_ent = score_wholesale_fit(ent)
    r_plain = score_wholesale_fit(plain)
    assert r_ent.drop is False, f"Got drop={r_ent.drop}"
    assert r_ent.score < r_plain.score, f"entity {r_ent.score} not < plain {r_plain.score}"
    print("PASS: soft_demote entity_type=llc -> kept, lowered")


# ── CLEAN MID-VALUE HIGH ──────────────────────────────────────────────


def test_clean_mid_value_high():
    """A clean free-and-clear mid-value probate with a real DM scores high (>= 70)."""
    n = _clean_workable()  # title=standard_probate, value=245000, equity=100, no liens
    r = score_wholesale_fit(n)
    assert r.drop is False, f"Got drop={r.drop}"
    assert r.score >= 70, f"Got score={r.score} (expected >= 70)"
    assert r.reason == "", f"Got reason={r.reason!r}"
    print(f"PASS: clean mid-value free-and-clear -> kept, score {r.score} >= 70")


# ── DISTRESS RAISES SCORE (locked decision 2) ─────────────────────────


def test_distress_raises_score():
    """Two otherwise-identical workable records: the one with distress signals
    (lien_flags=tax_cert;code) scores HIGHER than the clean twin — distress is
    motivation, not penalty (locked decision 2)."""
    distressed = _clean_workable(lien_flags="tax_cert;code")
    clean = _clean_workable()
    r_distress = score_wholesale_fit(distressed)
    r_clean = score_wholesale_fit(clean)
    assert r_distress.drop is False and r_clean.drop is False
    assert r_distress.score > r_clean.score, (
        f"distress {r_distress.score} not > clean {r_clean.score}"
    )
    print(
        f"PASS: distress raises score -> distressed {r_distress.score} "
        f"> clean {r_clean.score}"
    )


def test_distress_via_notice_type():
    """A foreclosure (notice_type) is itself a distress/motivation signal and
    raises the score vs an otherwise-identical clean probate."""
    fc = _clean_workable(notice_type="foreclosure")
    clean = _clean_workable()
    r_fc = score_wholesale_fit(fc)
    r_clean = score_wholesale_fit(clean)
    assert r_fc.score > r_clean.score, f"foreclosure {r_fc.score} not > clean {r_clean.score}"
    print("PASS: foreclosure notice_type raises distress component")


# ── DEFENSIVE PARSING (T-04-01) ───────────────────────────────────────


def test_malformed_numbers_do_not_crash():
    """Untrusted/malformed value & equity strings must degrade gracefully, never
    raise (threat T-04-01)."""
    for bad in ("$1,720,000", "N/A", "", "  ", "-12", "abc", "1.2.3"):
        n = _clean_workable(estimated_value=bad, equity_percent=bad)
        r = score_wholesale_fit(n)  # must not raise
        assert isinstance(r, FitResult)
        assert 0 <= r.score <= 100, f"score out of range for {bad!r}: {r.score}"
    print("PASS: malformed value/equity strings degrade gracefully (no crash)")


def test_dollar_formatted_value_parsed():
    """'$1,720,000' parses to the luxury tier (defensive _to_float strips $/,)."""
    n = _clean_workable(estimated_value="$1,720,000", title_path="successor_trustee")
    r = score_wholesale_fit(n)
    assert r.drop is False
    assert "luxury" in r.reason, f"Got reason={r.reason!r}"
    print("PASS: '$1,720,000' parsed -> luxury tier")


if __name__ == "__main__":
    test_hard_drop_no_property()
    test_hard_drop_out_of_estate()
    test_hard_drop_negative_equity()
    test_hard_drop_teardown()
    test_cheap_but_real_house_not_dropped()
    test_soft_demote_luxury_kept_low()
    test_soft_demote_sophisticated_dm()
    test_soft_demote_entity_type()
    test_clean_mid_value_high()
    test_distress_raises_score()
    test_distress_via_notice_type()
    test_malformed_numbers_do_not_crash()
    test_dollar_formatted_value_parsed()
    print("\nAll tests passed!")
