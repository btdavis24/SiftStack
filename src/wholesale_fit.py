"""Wholesale-fit scoring engine (Phase 4 / FIT-01, FIT-02).

Scores each enriched lead 0-100 for wholesale fit and decides whether it is
worth PAID skip trace (Tracerfy/Trestle). ~25% of probate leads (≈32/128 in the
manual review) are weak fits the naive pipeline still spends credits on; this
scorer is the credit-protection gate.

It is a PURE in-memory function — no I/O, no network, no credentials. A single
``score_wholesale_fit(notice) -> FitResult`` is the contract Plan 02 wires into
``enrichment_pipeline`` (as the final filter step) and ``main.py`` (the skip-trace
gate via ``config.SKIP_TRACE_MIN_FIT``).

Locked decisions (docs/phase_2h_fit_gate_spec.md):
  1. Hard-drop ONLY the unworkable (no_property / out_of_estate / true negative
     equity / sub-min teardown). Everything else is a soft demotion that STAYS in
     the list with a lowered score + reason — never silently lose a mailable lead.
  2. Distress = positive signal (motivation): code/tax/foreclosure/Medicaid raise
     the score's distress component even though they lower equity.
  3. DM sophistication is a MANUAL flag in v1 (dm_sophisticated / entity_type),
     not auto-detected from occupation.
  4. The four thresholds are config constants (config.WHOLESALE_*), not hardcoded.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import config
from notice_parser import NoticeData

logger = logging.getLogger(__name__)


# ── Scoring weights (tunable; thresholds live in config, not here) ────────
_BASE_SCORE = 50

# Equity buckets: more equity = more spread for the wholesale assignment.
_EQUITY_HIGH = 30   # >= 70% equity
_EQUITY_MID = 20    # 40-69%
_EQUITY_LOW = 10    # 20-39%
_EQUITY_NONE = 0    # < 20% (or unknown)

# Distress / motivation (locked decision 2). Per-signal bonus, capped — the more
# motivated-seller signals, the higher the score even as equity drops.
_DISTRESS_PER_SIGNAL = 7
_DISTRESS_CAP = 15

# Soft-demotion penalties (never set drop=True).
_LUXURY_PENALTY = 25            # estimated_value > WHOLESALE_MAX_VALUE
_PER_LIEN_HAIRCUT = 3           # economic thin-equity haircut per active lien flag
_DM_SOPHISTICATION_PENALTY = 10  # sophisticated DM (manual flag or entity)

# lien_flags tokens (from Phase 3 kentucky_equity_estimator) that count as
# motivated-seller distress. tax_cert / judgment / lis_pendens / medicaid are
# the canonical Phase 3 flags; "code" (code-violation) is accepted too since it is
# an equally strong motivation signal per the spec (code/tax/foreclosure/Medicaid).
_DISTRESS_LIEN_FLAGS = {"tax_cert", "code", "judgment", "lis_pendens", "medicaid"}

# Notice types that are themselves a distress/motivation signal.
_DISTRESS_NOTICE_TYPES = {"foreclosure", "tax_sale", "tax_delinquent"}

# Near-teardown / vacant-lot hints in property_type or raw_text. Conservative: a
# cheap-but-real house (has beds + sqft) is NOT a teardown.
_TEARDOWN_RE = re.compile(r"\b(?:vacant\s+lot|teardown|tear\s*down|raw\s+land|lot|land)\b", re.IGNORECASE)

# Strip everything but digits, a leading minus, and the decimal point.
_NUM_STRIP_RE = re.compile(r"[^\d.\-]")


@dataclass
class FitResult:
    """Result of scoring one lead for wholesale fit."""
    score: int   # 0-100
    drop: bool   # True = hard fail → exclude from PAID skip trace
    reason: str  # hard-drop reason, or ";"-joined soft-demotion reasons, or ""


def _to_float(s: str) -> float | None:
    """Parse an untrusted money/percent string to float, or None on bad input.

    Strips ``$``, ``,``, whitespace and stray non-numeric characters; returns
    None for empty/malformed input instead of raising (threat T-04-01 — a bad
    value degrades to "no gate", never crashes the pipeline).
    """
    if not s:
        return None
    cleaned = _NUM_STRIP_RE.sub("", str(s)).strip()
    # Guard against partial junk like "1.2.3" or a lone "-"/"."
    if not cleaned or cleaned in ("-", ".", "-."):
        return None
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def _has_active_senior_mortgage(notice: NoticeData) -> bool:
    """An active senior mortgage exists if Phase 2b estimated a balance or found
    an origination date for an unreleased mortgage."""
    return bool(
        getattr(notice, "mortgage_balance_estimate", "").strip()
        or getattr(notice, "mortgage_origination_date", "").strip()
    )


def _is_teardown(notice: NoticeData, val: float | None) -> bool:
    """Conservative sub-min-value teardown / vacant-lot detection.

    True only when value is below the floor AND a teardown/vacant-lot signal is
    present: either an explicit "lot/land/teardown" hint, or no structure data
    at all (no bedrooms and no sqft). A cheap-but-real house is kept.
    """
    if val is None or val >= config.WHOLESALE_MIN_VALUE:
        return False
    blob = f"{getattr(notice, 'property_type', '')} {getattr(notice, 'raw_text', '')}"
    if _TEARDOWN_RE.search(blob):
        return True
    # No structure data = looks like raw land / nothing to wholesale.
    has_structure = bool(
        getattr(notice, "bedrooms", "").strip() or getattr(notice, "sqft", "").strip()
    )
    return not has_structure


def _equity_bucket(notice: NoticeData) -> int:
    """Map equity to a 0-30 bucket. Prefers equity_percent; falls back to a rough
    bucket derived from estimated_equity / estimated_value; +0 if unknown."""
    pct = _to_float(getattr(notice, "equity_percent", ""))
    if pct is None:
        equity = _to_float(getattr(notice, "estimated_equity", ""))
        val = _to_float(getattr(notice, "estimated_value", ""))
        if equity is not None and val is not None and val > 0:
            pct = (equity / val) * 100.0
    if pct is None:
        return _EQUITY_NONE
    if pct >= 70:
        return _EQUITY_HIGH
    if pct >= 40:
        return _EQUITY_MID
    if pct >= 20:
        return _EQUITY_LOW
    return _EQUITY_NONE


def _distress_bonus(notice: NoticeData) -> int:
    """Count motivated-seller signals and award points (capped). Locked decision 2:
    distress (code/tax/foreclosure/Medicaid) RAISES the score."""
    signals = 0
    lien_flags = notice.lien_flags  # confirmed NoticeData field (Phase 3)
    if lien_flags:
        active = {f.strip().lower() for f in lien_flags.split(";") if f.strip()}
        signals += len(active & _DISTRESS_LIEN_FLAGS)
    if getattr(notice, "tax_delinquent_years", "").strip():
        signals += 1
    if getattr(notice, "notice_type", "").strip().lower() in _DISTRESS_NOTICE_TYPES:
        signals += 1
    return min(_DISTRESS_CAP, signals * _DISTRESS_PER_SIGNAL)


def _active_lien_count(notice: NoticeData) -> int:
    """Number of active lien flags (for the per-lien economic haircut)."""
    # title_path and lien_flags are confirmed NoticeData fields (notice_parser.py)
    # — read directly; the genuinely-optional Phase-2/3 reads above stay defensive.
    lien_flags = notice.lien_flags
    if not lien_flags:
        return 0
    return len([f for f in lien_flags.split(";") if f.strip()])


def score_wholesale_fit(notice: NoticeData) -> FitResult:
    """Score one enriched lead 0-100 for wholesale fit.

    Returns a FitResult. Hard drops (score 0, drop=True): no_property /
    out_of_estate title path, sub-min teardown/vacant-lot, true negative equity
    (equity floor + active senior mortgage). Everything else is kept (drop=False)
    with a possibly-lowered score and a ";"-joined soft-demotion reason.
    """
    # ── HARD DROPS (return immediately) ──────────────────────────────
    # title_path is a confirmed NoticeData field (Phase 2 / notice_parser.py).
    title_path = notice.title_path
    if title_path in ("no_property", "out_of_estate"):
        return FitResult(score=0, drop=True, reason=title_path)

    val = _to_float(getattr(notice, "estimated_value", ""))

    if _is_teardown(notice, val):
        return FitResult(score=0, drop=True, reason="teardown")

    pct = _to_float(getattr(notice, "equity_percent", ""))
    if (
        pct is not None
        and pct <= config.WHOLESALE_MIN_EQUITY_PCT
        and _has_active_senior_mortgage(notice)
    ):
        # True negative equity. (Equity at/below the floor WITHOUT an active
        # mortgage is lien-driven distress = a soft demotion + motivation, not a
        # hard drop — so it falls through to the score composition below.)
        return FitResult(score=0, drop=True, reason="negative_equity")

    # ── SCORE COMPOSITION (no hard drop fired) ───────────────────────
    score = _BASE_SCORE
    reasons: list[str] = []

    score += _equity_bucket(notice)
    score += _distress_bonus(notice)

    # Luxury soft demotion (locked decision 1: kept, never dropped).
    if val is not None and val > config.WHOLESALE_MAX_VALUE:
        score -= _LUXURY_PENALTY
        reasons.append("luxury_tier")

    # Per-lien economic haircut — a SEPARATE thin-equity penalty from the distress
    # bonus. Distress can both raise (motivation) and lower (equity) the score;
    # that is intended.
    score -= _PER_LIEN_HAIRCUT * _active_lien_count(notice)

    # DM-sophistication soft demotion (locked decision 3: manual flag only in v1;
    # an occupation auto-detect hook is deferred to a later phase).
    if (
        getattr(notice, "dm_sophisticated", "").strip().lower() == "yes"
        or getattr(notice, "entity_type", "").strip()
    ):
        score -= _DM_SOPHISTICATION_PENALTY
        reasons.append("sophisticated_dm")

    score = max(0, min(100, score))
    return FitResult(score=int(score), drop=False, reason=";".join(reasons))
