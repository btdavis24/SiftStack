"""Phase 2d — equity estimator for Kentucky probate records.

Computes ``estimated_equity`` + ``equity_percent`` from the Jefferson PVA
assessed value (Phase 2a) and the mortgage balance estimate (Phase 2b).

Policy (2026-04-23): equity is only computed when we have BOTH
  * a confirmed assessed value from PVA (Phase 2a), AND
  * a mortgage signal from JCD deed history (Phase 2b), where a confirmed
    "$0" (all mortgages released) counts as a valid signal.
When either is missing, ``estimated_equity`` and ``equity_percent`` are
left empty. No 85%-of-assessed fallback — we'd rather show "unknown"
than fabricate a number that could be off by tens of thousands.

Guardrails:
  * Only runs for KY records. TN records already get equity from
    ``property_enricher`` via Zillow and we don't want to overwrite.
  * Skips records where equity is already populated (e.g. Zillow ran).
  * Gated on ``property_owner_status`` — equity only for properties still
    held by the decedent, estate, or a recent-transfer heir.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from notice_parser import NoticeData

logger = logging.getLogger(__name__)


def estimate_equity(notice: "NoticeData") -> bool:
    """Populate ``estimated_equity`` and ``equity_percent`` on a KY notice.

    Only runs when current ownership is confirmed, per the product rule:
    equity is meaningless if the decedent no longer owns the property.
    Valid ``property_owner_status`` values for equity computation:
      * "direct"      — decedent is the PVA owner
      * "estate"      — PVA shows "ESTATE OF <decedent>"
      * "heir_recent" — heir received property via deed in the last 24 months

    Returns True if any field was written, False otherwise. Idempotent —
    does nothing if equity is already populated.
    """
    if notice.state.upper() != "KY":
        return False
    if notice.estimated_equity.strip() and notice.equity_percent.strip():
        return False
    if notice.property_owner_status not in ("direct", "estate", "trust", "heir_recent"):
        # No confirmed current-ownership signal — refuse to compute equity
        # even if we somehow have an estimated_value. Prevents asserting
        # equity for properties the estate may not actually hold.
        # Accepted statuses:
        #   direct       — decedent is the named PVA owner
        #   estate       — PVA shows "ESTATE OF <decedent>"
        #   trust        — title held by a trust the decedent created
        #   heir_recent  — title transferred to an heir within 24 months
        return False

    try:
        assessed = float(notice.estimated_value or "0")
    except ValueError:
        assessed = 0.0
    if assessed <= 0:
        return False

    # Mortgage signal required. An empty mortgage_balance_estimate means
    # Phase 2b couldn't determine the mortgage state (owner not matched in
    # deeds, or matched but no mortgage records found). In either case we
    # leave equity unknown rather than fabricate a fallback. A confirmed
    # "0" (all mortgages released, or property found but none ever filed
    # against this owner) IS a valid signal → produces 100% equity.
    if not notice.mortgage_balance_estimate.strip():
        return False

    try:
        mortgage = float(notice.mortgage_balance_estimate)
    except ValueError:
        return False

    equity = max(0.0, assessed - mortgage)
    percent = (equity / assessed) * 100 if assessed > 0 else 0.0

    notice.estimated_equity = str(int(round(equity)))
    notice.equity_percent = f"{percent:.1f}"

    logger.info(
        "  [Equity] %s -> $%s (%.1f%%) from assessed $%s - mortgage $%s",
        notice.case_number or notice.address or notice.decedent_name,
        f"{int(round(equity)):,}",
        percent,
        f"{int(assessed):,}",
        f"{int(mortgage):,}",
    )
    return True


def enrich_equity(notices: list["NoticeData"]) -> int:
    """Batch entry point. Returns count of records enriched."""
    if not notices:
        return 0

    enriched = 0
    for n in notices:
        if n.county.lower() != "jefferson":
            continue
        if estimate_equity(n):
            enriched += 1
    if enriched:
        logger.info("  [Equity] KY equity enrichment: %d record(s)", enriched)
    return enriched
