"""Network-free tests for wholesale buyer-profit math + exit-strategy ranking.

Regression context (CODE-REVIEW-WHOLE-REPO.md W3-CR-01 / W3-WR-05): calculate_wholesale
omitted the end-buyer's HOLDING costs and transfer tax (which the flip path charges)
and was fed the FLIP MAO as the contract price, double-counting the spread -> an
inflated buyer_profit_estimate that gated the WHOLESALE recommendation. And
_make_recommendation ranked WHOLESALE on a hardcoded score of 100, so any
qualifying wholesale always beat a superior flip/hold.

Run:  python tests/test_deal_analyzer_wholesale.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from deal_analyzer import (  # noqa: E402
    calculate_wholesale, _make_recommendation,
    FlipProjection, WholesaleProjection, HoldProjection, ARVResult,
    DEFAULT_WHOLESALE_FEE, DEFAULT_AGENT_COMMISSION, DEFAULT_CLOSING_COSTS_PCT,
    DEFAULT_TRANSFER_TAX_PCT,
)


def test_wholesale_charges_buyer_holding_and_transfer():
    """Buyer profit now includes HOLDING + transfer tax on the same basis as a
    flip (W3-CR-01) — holding reduces buyer profit dollar-for-dollar."""
    arv, contract, rehab, holding = 300000.0, 180000.0, 30000.0, 8000.0
    w0 = calculate_wholesale(arv, contract, rehab, holding_total=0.0)
    wh = calculate_wholesale(arv, contract, rehab, holding_total=holding)
    assert wh.buyer_profit_estimate == w0.buyer_profit_estimate - round(holding), (
        wh.buyer_profit_estimate, w0.buyer_profit_estimate)
    sell_pct = DEFAULT_AGENT_COMMISSION + DEFAULT_CLOSING_COSTS_PCT + DEFAULT_TRANSFER_TAX_PCT
    expected = round(arv - contract - DEFAULT_WHOLESALE_FEE - rehab - holding - arv * sell_pct)
    assert wh.buyer_profit_estimate == expected, (wh.buyer_profit_estimate, expected)
    print("PASS: test_wholesale_charges_buyer_holding_and_transfer")


def test_strong_flip_outranks_wholesale():
    """A strong flip must outrank a qualifying wholesale — the old hardcoded
    score of 100 made WHOLESALE always win (W3-WR-05)."""
    flip = FlipProjection(roi_pct=35.0, net_profit=45000)
    wholesale = WholesaleProjection(assignment_fee=10000, buyer_profit_estimate=25000,
                                    contract_price=150000)
    hold = HoldProjection(cash_on_cash=5.0, cash_flow_annual=3000)
    arv = ARVResult(confidence="high")
    rec = _make_recommendation(flip, wholesale, hold, arv)
    assert rec.startswith("GO"), rec
    assert "FLIP" in rec and "WHOLESALE" not in rec, rec
    print("PASS: test_strong_flip_outranks_wholesale")


def test_wholesale_wins_when_flip_weak():
    """When flip ROI is below the GO threshold but wholesale qualifies, WHOLESALE
    is recommended — no longer auto-suppressed by a strong flip nor auto-dominant."""
    flip = FlipProjection(roi_pct=12.0, net_profit=9000)   # below FLIP gate (25% / $25k)
    wholesale = WholesaleProjection(assignment_fee=12000, buyer_profit_estimate=30000,
                                    contract_price=120000)
    hold = HoldProjection(cash_on_cash=4.0, cash_flow_annual=2000)  # below 8% gate
    arv = ARVResult(confidence="high")
    rec = _make_recommendation(flip, wholesale, hold, arv)
    assert "WHOLESALE" in rec, rec
    print("PASS: test_wholesale_wins_when_flip_weak")


if __name__ == "__main__":
    test_wholesale_charges_buyer_holding_and_transfer()
    test_strong_flip_outranks_wholesale()
    test_wholesale_wins_when_flip_weak()
    print("\nAll deal-analyzer wholesale tests passed.")
