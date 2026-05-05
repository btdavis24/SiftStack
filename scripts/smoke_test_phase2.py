"""Phase 2 full-pipeline smoke test on real KCOJ cases.

Picks a handful of real case numbers from kcoj_seen_cases.json, synthesizes
minimal NoticeData records (decedent_name is unknown at this stage — it
comes from the docket scraper; for this test we leave it empty), then runs
all four Phase 2 steps in order: 2c → 2a → 2b → 2d.

Note: without the decedent_name from the docket, Phase 2c is the only step
that can run (it needs only case_number). Phase 2a/2b/2d need decedent_name
(2a/2b) or estimated_value (2d). Phase 2c will populate owner_name from the
executor, which 2b can then use for deed lookup.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from notice_parser import NoticeData
from kcoj_case_detail import enrich_case_parties
from kentucky_pva_lookup import probate_property_lookup
from jefferson_deeds_scraper import enrich_mortgage_balances
from kentucky_equity_estimator import enrich_equity

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def load_seen_cases() -> list[str]:
    with open("kcoj_seen_cases.json", encoding="utf-8") as f:
        return list(json.load(f).keys())


async def main() -> None:
    all_cases = load_seen_cases()
    # Pick a diverse sample: 2 from 26-P (recent), 3 from 25-P (older), plus
    # the already-validated 26-P-001544 as a control.
    sample = [
        "26-P-001544",  # ROLAND, WELDON GENE — validated 4-party case
        "26-P-001715",
        "25-P-001477",
        "25-P-003797",
        "26-P-000247",
        "25-P-002387",
        "26-P-001705",
    ]
    sample = [c for c in sample if c in all_cases]
    print(f"Testing {len(sample)} real case(s):")
    for c in sample:
        print(f"  {c}")
    print()

    notices = [
        NoticeData(
            notice_type="probate", county="Jefferson", state="KY",
            case_number=c,
        )
        for c in sample
    ]

    # Phase 2c — CourtNet case parties (backfills decedent_name from the DEC
    # party row, populates owner_name from the petitioner/executor, and
    # estate_attorney_name from the attorney row).
    print("=" * 60)
    print("Phase 2c — CourtNet case parties")
    print("=" * 60)
    await enrich_case_parties(notices)
    print()
    for n in notices:
        print(f"  {n.case_number}: decedent={n.decedent_name!r} executor={n.owner_name!r} attorney={n.estate_attorney_name!r} codes={n.courtnet_party_types!r}")
    print()

    # Phase 2b — Deed history FIRST (reversed-flow order). Walks deed
    # chain to identify the current title holder; populates
    # current_property_holder for Phase 2a to consume.
    print("=" * 60)
    print("Phase 2b — Jefferson Deeds: mortgage + current-holder discovery")
    print("=" * 60)
    enrich_mortgage_balances(notices)
    print()
    for n in notices:
        bits = []
        if n.current_property_holder:
            bits.append(f"holder={n.current_property_holder!r} ({n.current_holder_relationship})")
        if n.mortgage_original_amount and n.mortgage_original_amount != "0":
            bits.append(f"mtg ${n.mortgage_original_amount}->{n.mortgage_balance_estimate}")
        elif n.mortgage_balance_estimate == "0":
            bits.append("mtg paid off")
        if n.heir_transferred_to:
            bits.append(f"heir->{n.heir_transferred_to} on {n.heir_transfer_date}")
        print(f"  {n.case_number}: {' | '.join(bits) if bits else '(no deed match)'}")
    print()

    # Phase 2a — PVA lookup (uses current_property_holder when set)
    print("=" * 60)
    print("Phase 2a — Jefferson PVA lookup (deed-discovered holder primary)")
    print("=" * 60)
    probate_property_lookup(notices)
    print()
    for n in notices:
        print(f"  {n.case_number}: address={n.address!r}  est_value={n.estimated_value!r}  status={n.property_owner_status!r}")
    print()

    # Phase 2d — Equity estimator
    print("=" * 60)
    print("Phase 2d — Equity estimator (gated on property_owner_status)")
    print("=" * 60)
    enrich_equity(notices)
    print()

    # Final summary
    print("=" * 60)
    print("FINAL PER-CASE SUMMARY")
    print("=" * 60)
    for n in notices:
        print()
        print(f"Case {n.case_number}:")
        print(f"  decedent:           {n.decedent_name or '(none)'}")
        print(f"  executor:           {n.owner_name or '(none)'}")
        print(f"  attorney:           {n.estate_attorney_name or '(none)'}")
        print(f"  party types:        {n.courtnet_party_types or '(none)'}")
        print(f"  owner status:       {n.property_owner_status or '(not confirmed)'}")
        if n.current_property_holder:
            print(f"  current holder:     {n.current_property_holder} ({n.current_holder_relationship})")
        print(f"  address:            {n.address or '(none)'}")
        print(f"  tax owner (PVA):    {n.tax_owner_name or '(none)'}")
        print(f"  assessed value:     ${n.estimated_value or '-'}")
        print(f"  mortgage balance:   ${n.mortgage_balance_estimate or '-'}")
        if n.heir_transferred_to:
            print(f"  heir transfer:      {n.heir_transferred_to} on {n.heir_transfer_date} (same_surname={n.heir_same_surname or 'no'})")
        print(f"  estimated equity:   ${n.estimated_equity or '-'} ({n.equity_percent or '-'}%)")


if __name__ == "__main__":
    asyncio.run(main())
