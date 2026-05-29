"""Network-free test for kentucky_pva_lookup._parse_money (G2-WR-04).

The PVA money parser stripped ALL non-digits including the decimal point, so
"$399,990.00" became "39999000" — 100x the real value — which then flowed into
estimated_value / equity_percent. The fix keeps the decimal and drops the cents.

Run:  python tests/test_pva_money.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from kentucky_pva_lookup import _parse_money  # noqa: E402


def test_money_with_cents_not_inflated():
    assert _parse_money("$399,990.00") == "399990", _parse_money("$399,990.00")
    assert _parse_money("$1,234.56") == "1234", _parse_money("$1,234.56")
    print("PASS: test_money_with_cents_not_inflated")


def test_money_without_cents_unchanged():
    assert _parse_money("$399,990") == "399990", _parse_money("$399,990")
    assert _parse_money("250000") == "250000"
    print("PASS: test_money_without_cents_unchanged")


def test_non_money_returns_empty():
    assert _parse_money("") == ""
    assert _parse_money("N/A") == ""
    assert _parse_money("—") == ""
    assert _parse_money("1.2.3") == ""   # malformed -> float() raises -> ""
    print("PASS: test_non_money_returns_empty")


if __name__ == "__main__":
    test_money_with_cents_not_inflated()
    test_money_without_cents_unchanged()
    test_non_money_returns_empty()
    print("\nAll PVA _parse_money tests passed.")
