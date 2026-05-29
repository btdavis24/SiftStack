"""Phase 2f — title-path classifier for Kentucky probate records.

Before we trust "CourtNet executor = the person who can sell," classify each
lead's **title path** from the PVA owner string + latest deed (vs DOD) and set
who the real decision-maker is. The CourtNet executor is the wrong DM ~26% of
the time (≈33/128 cases) because title bypasses or sits outside probate; this
classifier is the highest *correctness* lever in the milestone.

``classify_title_path(notice)`` is a PURE function over an already-enriched
``NoticeData`` — it reads the Step 3c deed-chain result fields + the PVA owner
string + the obituary signal and sets, IN PLACE:
  * ``title_path``                  — one of the 5 ordered classes below
  * ``dm_can_sell_without_probate`` — "yes" | "no" | ""
  * ``needs_trustee_research``      — "yes" for successor_trustee
  * ``trustee_unconfirmed``         — "yes" when a trust is detected but the
                                       successor trustee is not recoverable
  * ``current_property_holder``     — the out-of-estate grantee (kept as 3c set)

Classification rules (FIRST MATCH WINS, ordered):
  1. ``no_property``      — no address AND no deed-derived holder → renter
  2. ``out_of_estate``    — latest deed moved the decedent OUT of title
                            (post-death sale, or pre-death transfer to a third
                            party / heir)
  3. ``successor_trustee``— PVA owner string matches a trust pattern → DM is the
                            successor trustee; can sell WITHOUT closing probate
  4. ``surviving_owner``  — latest deed has 2+ grantees and a co-owner is alive →
                            DM is the surviving co-owner; bypasses probate
  5. ``standard_probate`` — default; DM = CourtNet executor

It does NO network or file I/O so it is unit-testable per the spec acceptance.
The live Declaration-of-Trust grantee-chain fetch (``_fetch_deed_list``) is
wired in Plan 02's pipeline step; this module consumes only what 3c produced.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from notice_parser import NoticeData

logger = logging.getLogger(__name__)


# ── Trust-owner detection ─────────────────────────────────────────────
# Bounded, backtracking-free alternation (ReDoS-safe — threat T-02-01).
# Literal tokens anchored on word boundaries; NO nested quantifiers and NO
# ``.*`` between tokens. Seeded from jefferson_deeds_scraper._TRUST_RE
# (DETECT trusts here, don't reject them like _search_names_unique does).
# Matches "<NAME> REVOCABLE LIVING TRUST", "... TRUSTEE", "QPRT",
# "DECLARATION OF TRUST" / "DECL OF TRUST".
TRUST_OWNER_RE = re.compile(
    r"\b(REVOCABLE|LIVING\s+TRUST|TRUST|TRUSTEE|QPRT|DECL(?:ARATION)?\s+OF\s+TRUST)\b",
    re.IGNORECASE,
)

# Splits a multi-grantee deed-holder string into co-owner names. Joint/TBE/
# JTWROS deeds list 2+ grantees joined by "&", "AND", or a comma.
_MULTI_GRANTEE_SPLIT_RE = re.compile(r"\s*(?:&|\bAND\b|,)\s*", re.IGNORECASE)


def _safe_date(s: str) -> date | None:
    """Parse a strict ``"YYYY-MM-DD"`` string into a ``date``; None otherwise.

    Uses ``strptime("%Y-%m-%d")`` inside try/except — NO ``dateutil``-style
    fuzzy/locale parsing (threat T-02-02). Returns None on empty, malformed,
    or partial ("2026-03-xx") input so the caller's date-comparison branch
    fails safe (skips) rather than crashing.
    """
    if not s or not s.strip():
        return None
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _owner_source(notice: "NoticeData") -> str:
    """First non-empty owner string to test for a trust pattern.

    ``pva_owner_string`` is the dedicated, test-stable trust-detection input
    (populated by Step 3d wiring); fall back to ``tax_owner_name`` (the raw PVA
    owner captured elsewhere) and then the deed-derived ``current_property_holder``.
    """
    return (
        (notice.pva_owner_string or "").strip()
        or (notice.tax_owner_name or "").strip()
        or (notice.current_property_holder or "").strip()
    )


def _surname(name: str) -> str:
    """Best-guess upper-case surname. Mirrors jefferson_deeds_scraper._surname.

    Comma format ("SMITH, DOLLY") → first token. All-caps LAST FIRST
    ("SMITH JANE") → first token. Natural order ("Jane Smith") → last token.
    """
    if not name:
        return ""
    if "," in name:
        return name.split(",", 1)[0].strip().upper()
    tokens = [t for t in re.split(r"\s+", name.strip()) if t]
    if not tokens:
        return ""
    letters_only = re.sub(r"[^A-Za-z]", "", name)
    if letters_only and letters_only.isupper():
        return tokens[0].upper()
    return tokens[-1].upper()


def _preceded_in_death(notice: "NoticeData") -> set[str]:
    """Upper-cased set of names the obituary lists as predeceasing the decedent.

    Read defensively via ``getattr`` — there is no flat NoticeData field for
    this yet; it may be supplied as a semicolon/comma-delimited string (the
    CSV-stable form) or be absent (degrades to empty set). Locked decision 4:
    the v1 "co-owner alive" signal is the obituary ``preceded_in_death`` set
    only — no paid death index.
    """
    raw = getattr(notice, "preceded_in_death", "") or ""
    if not isinstance(raw, str):
        # Tolerate a list/iterable if a caller ever sets one directly.
        try:
            return {str(x).strip().upper() for x in raw if str(x).strip()}
        except TypeError:
            return set()
    return {t.strip().upper() for t in re.split(r"[;,]", raw) if t.strip()}


def _extract_successor_trustee(notice: "NoticeData") -> str:
    """Best-effort v1 successor-trustee candidate from already-available signals.

    Consumes only what Step 3c produced (no network calls — the live
    Declaration-of-Trust grantee-chain fetch lives in Plan 02's pipeline step):
      * if the deed chain already resolved the holder as a trust
        (``current_holder_relationship == "trust"``), use that holder string;
      * else try to recover a named "TRUSTEE" grantee from the PVA / tax owner
        string.
    Returns "" when nothing recoverable — the caller then sets
    ``trustee_unconfirmed="yes"`` and falls back to the CourtNet executor
    downstream (locked decision 3, Smith-Charles).
    """
    try:
        if (notice.current_holder_relationship or "").strip().lower() == "trust":
            holder = (notice.current_property_holder or "").strip()
            if holder:
                return holder
        # Look for an explicit "<NAME> TRUSTEE" token in the owner string.
        owner = _owner_source(notice)
        if owner:
            m = re.search(r"([A-Z][A-Za-z.\-]+(?:\s+[A-Z][A-Za-z.\-]+)*)\s+TRUSTEE\b", owner)
            if m:
                return m.group(1).strip()
    except Exception as e:  # noqa: BLE001 — resilient: never crash the classifier
        logger.warning("  [title] successor-trustee extraction failed: %s", e)
    return ""


def _surviving_owner_name(notice: "NoticeData") -> str:
    """Return the alive co-owner's name when the latest deed has 2+ grantees and
    a co-owner is alive, else "".

    Detect 2+ grantees from the deed-derived ``current_property_holder`` string
    (a multi-name holder joined by "&" / "AND" / ","). A co-owner is "alive" in
    v1 when its name differs from ``decedent_name`` AND is NOT in the obituary
    ``preceded_in_death`` set (locked decision 4 — no paid death index). The
    returned name is the surviving co-owner who becomes the decision-maker
    (CR-01); "" means standard probate.

    NOTE (future enhancement): Phase 1 ``kentucky_name_resolver`` name-variant
    disambiguation would tighten the same-name match here. It is intentionally
    NOT imported in v1 — the classifier stays a pure function with no
    cross-module dependency, and v1 relies only on the obituary signal.
    """
    holder = (notice.current_property_holder or "").strip()
    if not holder:
        return ""
    parts = [p.strip() for p in _MULTI_GRANTEE_SPLIT_RE.split(holder) if p.strip()]
    # Need at least two distinct name components to be a joint/survivorship deed.
    if len(parts) < 2:
        return ""

    dec_surname = _surname(notice.decedent_name)
    dec_name_u = (notice.decedent_name or "").strip().upper()
    preceded = _preceded_in_death(notice)

    for part in parts:
        part_u = part.upper()
        # Skip the decedent's own name component (surname match or full-name
        # containment in either direction handles "KAREM" vs "KAREM, DONALD N").
        if dec_surname and dec_surname in part_u and (
            not dec_name_u
            or any(tok in part_u for tok in dec_name_u.replace(",", " ").split())
        ):
            # This component is (a form of) the decedent — not a surviving owner.
            if _component_is_decedent(part_u, dec_name_u, dec_surname):
                continue
        # A non-decedent co-owner who is NOT recorded as predeceased = alive.
        if part_u in preceded:
            continue
        if _component_is_decedent(part_u, dec_name_u, dec_surname):
            continue
        return part  # the surviving co-owner (original deed casing)
    return ""


def _set_title_dm(notice, name: str, relationship: str, source: str, reason: str) -> bool:
    """Set the title-derived decision-maker, OVERRIDING the provisional CourtNet
    executor for trust / survivorship paths (locked decision 1, CR-01).
    Returns True when a DM was set."""
    name = (name or "").strip()
    if not name:
        return False
    notice.decision_maker_name = name
    notice.decision_maker_relationship = relationship
    notice.decision_maker_status = "unverified"  # title-derived; not yet contacted
    notice.decision_maker_source = source
    notice.dm_confidence = "medium"
    notice.dm_confidence_reason = reason
    return True


def _clear_title_dm(notice, reason: str) -> None:
    """Clear any provisional DM — out-of-estate / no-property leads have no party
    who can sell the real property, so no DM is named (CR-01; Phase 4 drops them)."""
    notice.decision_maker_name = ""
    notice.decision_maker_relationship = ""
    notice.decision_maker_status = ""
    notice.decision_maker_source = ""
    notice.dm_confidence = ""
    notice.dm_confidence_reason = reason


def _component_is_decedent(part_u: str, dec_name_u: str, dec_surname: str) -> bool:
    """Heuristic: does this grantee component refer to the decedent?

    Joint deeds repeat the surname for both spouses ("DONALD N KAREM & ANN
    LENORE KAREM"), so a surname match alone is not enough — we also require a
    given-name token overlap with the decedent's full name. Without that, a
    same-surname co-owner (the surviving spouse) is correctly treated as a
    distinct, living person.
    """
    if not part_u:
        return False
    if dec_name_u and (part_u in dec_name_u or dec_name_u in part_u):
        return True
    if not dec_surname or dec_surname not in part_u:
        return False
    # Surname matches; require a non-surname given-name token to also match.
    dec_tokens = {t for t in dec_name_u.replace(",", " ").split() if t and t != dec_surname}
    part_tokens = {t for t in part_u.split() if t and t != dec_surname}
    return bool(dec_tokens & part_tokens)


def classify_title_path(notice: "NoticeData") -> None:
    """Set ``title_path`` + ``dm_can_sell_without_probate`` (+ trust flags) in place.

    First match wins, in spec order (no_property → out_of_estate →
    successor_trustee → surviving_owner → standard_probate). Pure function: no
    network / file I/O. Guarded so a malformed notice never raises — on
    unexpected error it defaults to ``standard_probate`` and logs (threat
    T-02-03, fail safe to the executor path; never auto-attaches a trustee /
    surviving-owner DM on a parse failure).
    """
    try:
        address = (notice.address or "").strip()
        holder = (notice.current_property_holder or "").strip()
        relationship = (notice.current_holder_relationship or "").strip()

        # ── Rule 1: no_property ──────────────────────────────────────
        # Step 3d found nothing after the name fan-out AND there is no deed
        # history → true renter. (Humphrey, Maupin, Peter, Skaggs.)
        if not address and not holder and not relationship:
            notice.title_path = "no_property"
            notice.dm_can_sell_without_probate = ""
            _clear_title_dm(notice, "renter / no real property — no decision-maker named")
            return

        # ── Rule 2: out_of_estate ────────────────────────────────────
        # Latest deed moved the decedent OUT of title. Read the Step 3c result
        # fields — do NOT re-fetch deeds.
        dod = _safe_date(notice.date_of_death)
        transfer_date = _safe_date(notice.heir_transfer_date)
        # (a) post-death sale — the transfer/holder deed date is AFTER the DOD.
        post_death_sale = bool(dod and transfer_date and transfer_date > dod)
        # (b) pre-death transfer-out to a third party / heir — decedent is no
        #     longer the holder ("heir_recent", or an explicit grantee captured)
        #     and the holder is not the decedent ("self").
        transferred_out = (
            relationship == "heir_recent"
            or (
                bool((notice.heir_transferred_to or "").strip())
                and relationship != "self"
            )
        )
        if post_death_sale or transferred_out:
            notice.title_path = "out_of_estate"
            # Keep the new grantee already captured by 3c in current_property_holder.
            notice.dm_can_sell_without_probate = ""
            _clear_title_dm(notice, "decedent left title before death — no estate DM named")
            return

        # ── Rule 3: successor_trustee ────────────────────────────────
        # PVA owner string matches a trust pattern → DM is the successor trustee;
        # can sell WITHOUT closing probate. (Sauer, Schrenger, Williams, Atlas/
        # QPRT, Bryan, Byrd, Guss, Long, Morrison, Mudd-Keysferry, Palmer-Ball,
        # Plymale.)
        if TRUST_OWNER_RE.search(_owner_source(notice)):
            notice.title_path = "successor_trustee"
            notice.dm_can_sell_without_probate = "yes"
            notice.needs_trustee_research = "yes"
            trustee = _extract_successor_trustee(notice)
            if trustee:
                # Title overrides the provisional CourtNet executor as DM source
                # (locked decision 1, CR-01) — the successor trustee can sell.
                _set_title_dm(
                    notice, trustee, "successor_trustee", "title_successor_trustee",
                    "deed shows a revocable/living trust; the successor trustee "
                    "can sell without closing probate",
                )
            else:
                # Trust agreement unrecorded / not recoverable → keep the
                # provisional CourtNet executor as DM (locked decision 3).
                notice.trustee_unconfirmed = "yes"
            return

        # ── Rule 4: surviving_owner ──────────────────────────────────
        # Latest deed has 2+ grantees (joint/TBE/JTWROS) AND a co-owner is alive
        # (not the decedent, not in obituary preceded_in_death). (Hale, Karem,
        # Koch/TBE, Pfeifer, Wagner, Layton, Martin-Bluffview.)
        survivor = _surviving_owner_name(notice)
        if survivor:
            notice.title_path = "surviving_owner"
            notice.dm_can_sell_without_probate = "yes"
            # Surviving co-owner bypasses probate → they are the DM, not the
            # personal-estate executor (locked decision 1, CR-01).
            _set_title_dm(
                notice, survivor, "surviving_owner", "title_surviving_owner",
                "joint/survivorship deed; the surviving co-owner bypasses probate",
            )
            return

        # ── Rule 5: standard_probate (default) ───────────────────────
        # DM = CourtNet executor.
        notice.title_path = "standard_probate"
        notice.dm_can_sell_without_probate = "no"
    except Exception as e:  # noqa: BLE001 — resilient: never crash the pipeline
        logger.warning(
            "  [title] classify_title_path failed (%s) — defaulting to standard_probate",
            e,
        )
        notice.title_path = "standard_probate"
        notice.dm_can_sell_without_probate = "no"
