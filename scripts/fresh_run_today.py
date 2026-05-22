"""Fresh end-to-end run on today's Jefferson District probate docket.

Reversed property-discovery flow (2026-04-23):
  1. Scrape KCOJ dockets for today → case numbers + decedent names
  2. Phase 2c — CourtNet → executor + attorney + decedent confirmation
  3. Phase 2b — Deeds → mortgage balance + walk deed chain to identify
     the CURRENT property holder (decedent / estate / trust / heir)
  4. Phase 2a — PVA lookup using ``current_property_holder`` from 2b
     (falls back to decedent_name if 2b found no deeds)
  5. Phase 2d — Equity computation (gated on property_owner_status)

Step 3d.5 (separate heir PVA pass) was removed — Phase 2a now handles
the heir/trust paths in a single search.

Passes an empty seen_cases dict to KCOJ so all qualifying cases surface
(cases carried over from earlier-day dockets are still valid test material).
"""
from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from kcoj_scraper import scrape_kcoj_dockets
from kcoj_case_detail import enrich_case_parties
from kentucky_pva_lookup import probate_property_lookup
from jefferson_deeds_scraper import enrich_mortgage_balances
from kentucky_equity_estimator import enrich_equity

logging.basicConfig(level=logging.INFO, format="%(message)s")


async def main() -> None:
    # Use most recent business day. KCOJ docket is empty on Sat/Sun.
    from datetime import timedelta
    target = datetime.now()
    while target.weekday() >= 5:  # 5=Sat, 6=Sun
        target -= timedelta(days=1)
    today = target.strftime("%Y-%m-%d")
    print(f"=== Fresh Phase 2 run for Jefferson County, KY — {today} ===")
    print()

    # ── Step 1: KCOJ docket ─────────────────────────────────────────
    print("=" * 60)
    print(f"KCOJ docket scrape — Jefferson District {today}")
    print("=" * 60)
    notices = await scrape_kcoj_dockets(
        county="Jefferson",
        division="District",
        target_date=today,
        headless=True,
        seen_cases={},  # empty to force all cases through
    )
    if not notices:
        print()
        print("No qualifying cases on today's docket.")
        print("(Today may be a weekend/holiday, or the portal hasn't published yet.)")
        return

    print(f"\nScraped {len(notices)} total cases on today's docket.")
    # For a readable smoke test, cap at a modest sample. The full 57-case
    # run will work in production but this script prioritizes visibility.
    SAMPLE = 10
    if len(notices) > SAMPLE:
        notices = notices[:SAMPLE]
        print(f"Sampling first {SAMPLE} for this run:")
    for n in notices:
        print(f"  {n.case_number:<15} | {n.decedent_name}")
    print()

    # ── Step 2: Phase 2c CourtNet enrichment ───────────────────────
    print("=" * 60)
    print("Phase 2c — CourtNet case-detail enrichment")
    print("=" * 60)
    await enrich_case_parties(notices)
    print()
    for n in notices:
        print(f"  {n.case_number}: executor={n.owner_name or '-'}  attorney={n.estate_attorney_name or '-'}  codes={n.courtnet_party_types or '-'}")
    print()

    # ── Step 3: Phase 2b — Deeds first (NEW ORDER) ─────────────────
    # Walk the decedent's deed chain to identify the current title holder.
    # The current_property_holder field then drives Phase 2a's PVA search.
    print("=" * 60)
    print("Phase 2b — Jefferson Deeds: mortgage + current-holder discovery")
    print("=" * 60)
    enrich_mortgage_balances(notices)
    print()
    active_mtg = sum(1 for n in notices if n.mortgage_original_amount and n.mortgage_original_amount != "0")
    paid_off = sum(1 for n in notices if n.mortgage_balance_estimate == "0")
    holders = sum(1 for n in notices if n.current_property_holder)
    print(f"Active mortgages: {active_mtg}  |  Paid-off: {paid_off}  |  Current holder identified: {holders}/{len(notices)}")
    for n in notices:
        bits = []
        if n.current_property_holder:
            bits.append(f"holder={n.current_property_holder!r} ({n.current_holder_relationship})")
        if n.mortgage_original_amount and n.mortgage_original_amount != "0":
            bits.append(f"mtg ${n.mortgage_original_amount}→${n.mortgage_balance_estimate}")
        elif n.mortgage_balance_estimate == "0":
            bits.append("mtg paid off")
        if bits:
            print(f"  {n.case_number}: {' | '.join(bits)}")
    print()

    # ── Step 4: Phase 2a — PVA lookup using current-holder ─────────
    print("=" * 60)
    print("Phase 2a — Jefferson PVA lookup (uses current_property_holder)")
    print("=" * 60)
    probate_property_lookup(notices)
    print()
    matched_2a = sum(1 for n in notices if n.estimated_value)
    print(f"PVA matched: {matched_2a}/{len(notices)}")
    for n in notices:
        if n.estimated_value:
            print(f"  {n.case_number}: {n.address}  (${n.estimated_value}, status={n.property_owner_status})")
    print()

    # ── Step 5: Phase 2d — equity (gated) ──────────────────────────
    print("=" * 60)
    print("Phase 2d — Equity estimator (gated on confirmed ownership)")
    print("=" * 60)
    enrich_equity(notices)
    print()

    # ── Final summary ──────────────────────────────────────────────
    print("=" * 60)
    print("FINAL SUMMARY")
    print("=" * 60)
    with_equity = sum(1 for n in notices if n.estimated_equity)
    print(f"Cases with computed equity: {with_equity}/{len(notices)}")
    print()
    for n in notices:
        print(f"Case {n.case_number}")
        print(f"  decedent:        {n.decedent_name or '-'}")
        print(f"  executor:        {n.owner_name or '-'}")
        print(f"  attorney:        {n.estate_attorney_name or '-'}")
        print(f"  owner status:    {n.property_owner_status or '(not confirmed)'}")
        print(f"  address:         {n.address or '-'}")
        print(f"  assessed value:  ${n.estimated_value or '-'}")
        print(f"  mortgage:        ${n.mortgage_balance_estimate or '-'}")
        if n.heir_transferred_to:
            marker = " (family)" if n.heir_same_surname == "yes" else ""
            print(f"  heir transfer:   {n.heir_transferred_to} on {n.heir_transfer_date}{marker}")
        print(f"  estimated equity: ${n.estimated_equity or '-'} ({n.equity_percent or '-'}%)")
        print()


if __name__ == "__main__":
    asyncio.run(main())
