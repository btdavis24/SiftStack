"""Death/identity guard over the EXISTING skip-trace output (spec task 2g-3).

Runs AFTER ``tracerfy_skip_tracer.batch_skip_trace`` and BEFORE Trestle
``score_record_phones`` to scrub the contact data that the trace returned:

  1. DEATH-SUPPRESSION (free signals first — locked decision #2): drop any
     phone/email tied to a known-dead contact — the decedent themselves, an heir
     flagged ``status == "deceased"``, or a name in the obituary
     ``preceded_in_death`` set. This kills the Davis case (the DM resolved to a
     husband dead since 2012) and the deceased-heir case (an heir flagged dead
     must never be dialed).
  2. IDENTITY CONFIRMATION (Armstrong wrong-Barry): when the DM phones survived
     death-suppression and Tracerfy attached an age/address, corroborate the
     traced contact against the decedent's parcel + expected DOD via Phase 1
     ``kentucky_name_resolver.disambiguate``. Below threshold/margin -> flag the
     DM ``unconfirmed`` and DO NOT promote the phones (locked decision #3:
     below-confidence phones are NEVER promoted to DM #1 flat fields).
  3. AUDIT: every suppression / unconfirmed flag is appended to
     ``notice.skip_trace_guard_notes`` so a reviewer can see exactly why a
     contact was dropped or held (T-05-05).

This is a guard layer — it does NOT reimplement Tracerfy or Trestle.
"""

import json
import logging
import re
from datetime import date, timedelta

from notice_parser import NoticeData

logger = logging.getLogger(__name__)

# Business days to wait before re-polling a record that could not be contacted
# now (no guard-passing phone, no attorney) so it can be queued for an AOC-805
# petition pull. Phase 6 drains repoll_after; Phase 5 only SETS it (2g-4/2g-6).
AOC805_REPOLL_DAYS = 4

# Canonical DM phone-field list — single source of truth lives in phone_validator.
# Import it; do NOT inline a 6-field subset (the full 9 fields ensure mobile_4/5
# + landline_3 are also suppressed, T-05-02). Fall back to the literal only if
# phone_validator can't be imported (degraded environment).
try:
    from phone_validator import DM_PHONE_FIELDS
except ImportError:  # pragma: no cover - phone_validator is always present in-tree
    DM_PHONE_FIELDS = [
        "primary_phone", "mobile_1", "mobile_2", "mobile_3", "mobile_4",
        "mobile_5", "landline_1", "landline_2", "landline_3",
    ]

# DM #1 email block (flat fields).
DM_EMAIL_FIELDS = ["email_1", "email_2", "email_3", "email_4", "email_5"]

# Phase 1 identity resolver — imported DEFENSIVELY. If Phase 1's module is not
# present at execution time, the identity-confirmation half degrades to "flag
# unconfirmed only on an explicit mismatch" rather than crashing. The
# death-suppression half (free signals) works regardless.
try:
    from kentucky_name_resolver import disambiguate
except ImportError:  # pragma: no cover - Phase 1 shipped, but degrade gracefully
    disambiguate = None

# Name suffixes stripped during normalization so "SMITH JOHN JR" and
# "SMITH JOHN" compare equal.
_SUFFIXES = {"JR", "SR", "II", "III", "IV", "V", "ESQ"}
_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[.,]")

# Age/DOD conflict tolerance (years) used only when Phase 1 disambiguate is
# unavailable and we fall back to a conservative explicit-mismatch check.
_AGE_DOD_TOLERANCE_YEARS = 3


def _norm(name: str) -> str:
    """Normalize a person name for set membership: lower, collapse spaces,
    strip punctuation and JR/SR/II/III suffix tokens."""
    if not name:
        return ""
    cleaned = _PUNCT_RE.sub(" ", str(name)).lower()
    tokens = [t for t in _WS_RE.sub(" ", cleaned).strip().split(" ")
              if t and t.upper() not in _SUFFIXES]
    return " ".join(tokens)


def _parse_heirs(notice: NoticeData) -> list:
    """Parse heir_map_json into a list of dicts; [] on any error."""
    raw = getattr(notice, "heir_map_json", "") or ""
    if not raw:
        return []
    try:
        heirs = json.loads(raw)
    except (ValueError, TypeError) as e:
        logger.warning("skip_trace_guard: could not parse heir_map_json: %s", e)
        return []
    return heirs if isinstance(heirs, list) else []


def _known_dead_names(notice: NoticeData, heirs: list) -> set:
    """Build the set of normalized known-dead names from FREE signals:

      * the decedent (dead by definition),
      * any heir with status == "deceased" or a preceded_in_death marker,
      * any name in a parsed obituary preceded_in_death list (if present).
    """
    dead: set = set()

    decedent = _norm(getattr(notice, "decedent_name", ""))
    if decedent:
        dead.add(decedent)

    for heir in heirs:
        if not isinstance(heir, dict):
            continue
        is_dead = (
            (heir.get("status") or "").strip().lower() == "deceased"
            or bool(heir.get("preceded_in_death"))
        )
        if is_dead:
            n = _norm(heir.get("name", ""))
            if n:
                dead.add(n)

    # Accept a parsed preceded_in_death list if one was persisted on the notice
    # (some build paths stash the obituary set). Tolerate str (JSON) or list.
    pre = getattr(notice, "preceded_in_death", None)
    if isinstance(pre, str) and pre.strip():
        try:
            pre = json.loads(pre)
        except (ValueError, TypeError):
            pre = [p.strip() for p in pre.split(";") if p.strip()]
    if isinstance(pre, (list, tuple, set)):
        for nm in pre:
            n = _norm(nm)
            if n:
                dead.add(n)

    return dead


def _clear_dm_flat_contacts(notice: NoticeData) -> tuple:
    """Clear ALL DM #1 flat phone + email fields. Returns (phones_cleared, emails_cleared)."""
    phones_cleared = 0
    emails_cleared = 0
    for field in DM_PHONE_FIELDS:
        if (getattr(notice, field, "") or "").strip():
            setattr(notice, field, "")
            phones_cleared += 1
    for field in DM_EMAIL_FIELDS:
        if (getattr(notice, field, "") or "").strip():
            setattr(notice, field, "")
            emails_cleared += 1
    return phones_cleared, emails_cleared


def _dm_has_flat_phones(notice: NoticeData) -> bool:
    """True if any DM #1 flat phone field is non-empty (survived suppression)."""
    return any((getattr(notice, f, "") or "").strip() for f in DM_PHONE_FIELDS)


def _dm_heir_entry(notice: NoticeData, heirs: list) -> dict | None:
    """Find the heir_map_json entry that corresponds to the DM (by name)."""
    dm = _norm(getattr(notice, "decision_maker_name", ""))
    if not dm:
        return None
    for heir in heirs:
        if isinstance(heir, dict) and _norm(heir.get("name", "")) == dm:
            return heir
    return None


def _append_note(notice: NoticeData, note: str) -> None:
    """Append an audit note to skip_trace_guard_notes (semicolon-joined)."""
    if not note:
        return
    existing = (getattr(notice, "skip_trace_guard_notes", "") or "").strip()
    notice.skip_trace_guard_notes = f"{existing}{note}" if existing else note


def guard_traced_contacts(notice: NoticeData) -> dict:
    """Scrub a single notice's traced contacts (death-suppression + identity).

    Mutates ``notice`` in place: clears suppressed flat phone/email fields and
    deceased-heir phone/email lists, flags an unconfirmed DM (does NOT promote
    its phones), and appends every action to ``notice.skip_trace_guard_notes``.

    Returns ``{"suppressed_phones": int, "suppressed_emails": int,
                "unconfirmed": bool, "notes": str}``.
    """
    suppressed_phones = 0
    suppressed_emails = 0
    unconfirmed = False
    notes: list[str] = []

    heirs = _parse_heirs(notice)
    heirs_mutated = False
    dead_names = _known_dead_names(notice, heirs)

    # ── Pass 1: DEATH-SUPPRESSION (free signals) ──────────────────────────
    # 1a) DM #1 flat block — attributed to decision_maker_name. If the DM name
    #     normalizes to a known-dead name -> drop ALL flat phones+emails (Davis).
    dm_name = getattr(notice, "decision_maker_name", "") or ""
    if _norm(dm_name) and _norm(dm_name) in dead_names:
        p, e = _clear_dm_flat_contacts(notice)
        suppressed_phones += p
        suppressed_emails += e
        if p or e:
            notes.append(
                f"death-suppressed DM phones ({dm_name} matches known-dead);"
            )
            logger.info(
                "  Guard: death-suppressed %d DM phone(s) for %s (known-dead)",
                p, dm_name,
            )

    # 1b) Deceased heirs — clear their phones/emails so they're never dialed.
    for heir in heirs:
        if not isinstance(heir, dict):
            continue
        heir_name = (heir.get("name") or "").strip()
        if not heir_name or _norm(heir_name) not in dead_names:
            continue
        heir_phones = heir.get("phones") or []
        heir_emails = heir.get("emails") or []
        if heir_phones or heir_emails:
            suppressed_phones += len([x for x in heir_phones if x])
            suppressed_emails += len([x for x in heir_emails if x])
            heir["phones"] = []
            heir["emails"] = []
            heirs_mutated = True
            status = (heir.get("status") or "deceased")
            notes.append(
                f"death-suppressed heir phones ({heir_name} status={status});"
            )
            logger.info(
                "  Guard: death-suppressed heir phones for %s (status=%s)",
                heir_name, status,
            )

    # ── Pass 2: IDENTITY CONFIRMATION (Armstrong wrong-Barry) ─────────────
    # Only when the DM flat phones survived suppression AND we have a returned
    # age/address signal to corroborate. Below threshold -> flag unconfirmed,
    # NEVER promote (locked decision #3).
    if _dm_has_flat_phones(notice) and _norm(dm_name):
        dm_entry = _dm_heir_entry(notice, heirs) or {}
        traced_age = dm_entry.get("age")
        traced_addresses = dm_entry.get("addresses") or []
        if isinstance(traced_addresses, str):
            traced_addresses = [traced_addresses] if traced_addresses else []
        has_signal = traced_age is not None or bool(traced_addresses)

        if has_signal:
            known_addresses = []
            parcel_addr = (getattr(notice, "address", "") or "").strip()
            if parcel_addr:
                known_addresses.append(parcel_addr)
            # any prior addresses already on the DM entry corroborate too
            for a in (dm_entry.get("prior_addresses") or []):
                if a:
                    known_addresses.append(a)
            expected_dod = (getattr(notice, "date_of_death", "") or "").strip() or None

            confirmed = True
            reason = ""
            if disambiguate is not None:
                try:
                    from kentucky_name_resolver import CandidatePerson
                    candidate = CandidatePerson(
                        name=dm_name,
                        age=traced_age if isinstance(traced_age, int) else None,
                        addresses=list(traced_addresses) or None,
                    )
                    res = disambiguate(
                        dm_name, [candidate],
                        expected_dod=expected_dod,
                        known_addresses=known_addresses or None,
                        min_score=0.6,
                    )
                    if res is None:
                        confirmed = False
                        reason = "below confidence threshold/margin (no age/address corroboration)"
                except Exception as e:  # never crash the trace pass
                    logger.warning(
                        "  Guard: disambiguate failed for %s: %s — leaving confirmed",
                        dm_name, e,
                    )
            else:
                # Phase 1 resolver unavailable — conservatively flag unconfirmed
                # ONLY on an explicit age/DOD conflict; otherwise leave confirmed.
                logger.debug(
                    "  Guard: kentucky_name_resolver unavailable — "
                    "identity confirmation degraded to explicit-mismatch only"
                )
                if isinstance(traced_age, int) and expected_dod:
                    exp_age = _expected_age_from_dod(notice)
                    if exp_age is not None and abs(traced_age - exp_age) > _AGE_DOD_TOLERANCE_YEARS:
                        confirmed = False
                        reason = (
                            f"traced age {traced_age} conflicts with expected "
                            f"age ~{exp_age} (>{_AGE_DOD_TOLERANCE_YEARS}yr)"
                        )

            if not confirmed:
                unconfirmed = True
                # Flag but DO NOT clear/promote — keep for manual review.
                notice.decision_maker_status = "unconfirmed"
                notes.append(
                    f"identity-unconfirmed DM ({dm_name}): {reason};"
                )
                logger.info(
                    "  Guard: DM %s flagged unconfirmed (%s) — phones held, not promoted",
                    dm_name, reason,
                )

    # ── Pass 3: AUDIT ─────────────────────────────────────────────────────
    if heirs_mutated:
        try:
            notice.heir_map_json = json.dumps(heirs, ensure_ascii=False)
        except (TypeError, ValueError) as e:
            logger.warning("skip_trace_guard: could not re-serialize heir_map_json: %s", e)

    note_str = "".join(notes)
    if note_str:
        _append_note(notice, note_str)

    return {
        "suppressed_phones": suppressed_phones,
        "suppressed_emails": suppressed_emails,
        "unconfirmed": unconfirmed,
        "notes": note_str,
    }


def _expected_age_from_dod(notice: NoticeData) -> int | None:
    """Best-effort decedent age from any obituary age field — used only for the
    degraded (no-Phase-1) explicit-mismatch fallback. Returns None when unknown."""
    for field in ("age_at_death", "decedent_age", "obit_age"):
        val = getattr(notice, field, None)
        if val:
            try:
                return int(str(val).strip())
            except (ValueError, TypeError):
                continue
    return None


def guard_all(notices: list) -> dict:
    """Run guard_traced_contacts over a list of notices; aggregate stats.

    Returns ``{records, suppressed_phones, suppressed_emails, unconfirmed}`` and
    logs a one-line summary (CONVENTIONS logging style).
    """
    agg = {
        "records": 0,
        "suppressed_phones": 0,
        "suppressed_emails": 0,
        "unconfirmed": 0,
    }
    for notice in notices or []:
        try:
            r = guard_traced_contacts(notice)
        except Exception:
            logger.exception("skip_trace_guard: guard pass failed for a notice")
            continue
        agg["records"] += 1
        agg["suppressed_phones"] += r["suppressed_phones"]
        agg["suppressed_emails"] += r["suppressed_emails"]
        if r["unconfirmed"]:
            agg["unconfirmed"] += 1

    logger.info(
        "Skip-trace guard: %d record(s) — %d phone(s) + %d email(s) "
        "death-suppressed, %d DM(s) flagged unconfirmed",
        agg["records"], agg["suppressed_phones"],
        agg["suppressed_emails"], agg["unconfirmed"],
    )
    return agg


# ── Empty-trace fallback + re-poll helpers (2g-4 / 2g-6) ──────────────────


def _today() -> date:
    """Indirection so tests/callers reason about 'today' consistently."""
    return date.today()


def set_repoll_after(notice: NoticeData, days: int = AOC805_REPOLL_DAYS) -> str:
    """Set ``notice.repoll_after`` to today + ``days`` BUSINESS days (skipping
    Sat/Sun), as a ``YYYY-MM-DD`` string, and return it.

    Idempotent: if ``repoll_after`` is already a future date, leave it untouched
    and return the existing value. ``repoll_after`` is Phase-5-owned; Phase 6
    drains it — this only SETS the signal (2g-4 AOC-805, 2g-6 credits).
    """
    today = _today()
    existing = (getattr(notice, "repoll_after", "") or "").strip()
    if existing:
        try:
            if date.fromisoformat(existing) > today:
                return existing  # already queued for the future — leave it
        except (ValueError, TypeError):
            pass  # malformed -> overwrite below

    d = today
    remaining = max(0, int(days))
    while remaining > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:  # Mon-Fri
            remaining -= 1
    out = d.isoformat()
    notice.repoll_after = out
    return out


def _has_guard_passing_phone(notice: NoticeData) -> bool:
    """True if the DM has at least one guard-passing phone.

    A phone is guard-passing only when a DM #1 flat phone (any field in the
    canonical DM_PHONE_FIELDS — never a 6-field subset) survived the guard AND
    the DM identity is NOT flagged ``unconfirmed`` (T-05-09: an unconfirmed DM
    phone is treated as NOT contactable, so the record falls back to the
    verified estate-attorney channel instead of dialing an unconfirmed number).
    """
    status = (getattr(notice, "decision_maker_status", "") or "").strip().lower()
    if status == "unconfirmed":
        return False
    return any((getattr(notice, f, "") or "").strip() for f in DM_PHONE_FIELDS)


def apply_contact_fallback(notice: NoticeData) -> str:
    """Apply the empty-trace fallback when the DM has no guard-passing phone.

    Returns the channel applied:
      * ``""``              — none needed (DM already has a guard-passing phone),
      * ``"attorney"``      — estate attorney (AP) flagged as the contact channel,
      * ``"aoc805_queued"`` — neither phone nor attorney; queued for AOC-805
                              (``repoll_after`` set; Phase 6 drains it).
    """
    if _has_guard_passing_phone(notice):
        return ""

    attorney = (getattr(notice, "estate_attorney_name", "") or "").strip()
    if attorney:
        notice.contact_via_attorney = "yes"
        # The attorney phone may be empty here — the CHANNEL is what matters;
        # downstream marketing routes via the attorney.
        _append_note(notice, "fallback=attorney (no guard-passing DM phone);")
        logger.info("  Fallback: route via estate attorney %s (no DM phone)", attorney)
        return "attorney"

    # No phone AND no attorney -> queue for an AOC-805 petition pull.
    set_repoll_after(notice)
    _append_note(notice, "fallback=aoc805_queued (no phone, no attorney);")
    logger.info("  Fallback: queued for AOC-805 re-poll after %s (no phone, no attorney)",
                notice.repoll_after)
    return "aoc805_queued"


def apply_contact_fallbacks(notices: list) -> dict:
    """Run ``apply_contact_fallback`` over a list; aggregate per-channel counts.

    Returns ``{records, attorney, aoc805_queued}`` and logs a one-line summary.
    """
    agg = {"records": 0, "attorney": 0, "aoc805_queued": 0}
    for notice in notices or []:
        try:
            ch = apply_contact_fallback(notice)
        except Exception:
            logger.exception("skip_trace_guard: contact fallback failed for a notice")
            continue
        agg["records"] += 1
        if ch == "attorney":
            agg["attorney"] += 1
        elif ch == "aoc805_queued":
            agg["aoc805_queued"] += 1

    logger.info(
        "Contact fallback: %d record(s) — %d via attorney, %d queued for AOC-805",
        agg["records"], agg["attorney"], agg["aoc805_queued"],
    )
    return agg


def handle_credits_exhausted(notices: list, stats: dict,
                             days: int = AOC805_REPOLL_DAYS) -> dict:
    """Salvage a credits-exhausted Tracerfy batch (2g-6, T-05-11).

    When ``stats["credits_exhausted"]`` is True, every notice that STILL has no
    DM phone (no field in the canonical DM_PHONE_FIELDS populated) is enqueued
    for a re-poll by setting ``repoll_after`` (reusing ``set_repoll_after``) and
    a guard note — so the unfinished remainder is auditable and re-tried rather
    than silently dropped. Records that DID get a phone are left untouched.

    Returns ``{"queued": <count>}``. Phase 6 drains ``repoll_after``; this only
    SETS the signal.
    """
    if not (stats or {}).get("credits_exhausted"):
        return {"queued": 0}

    queued = 0
    for notice in notices or []:
        if any((getattr(notice, f, "") or "").strip() for f in DM_PHONE_FIELDS):
            continue  # already has a phone — nothing to salvage
        try:
            set_repoll_after(notice, days)
            _append_note(notice, "credits_exhausted → repoll;")
            queued += 1
        except Exception:
            logger.exception("skip_trace_guard: credits-exhausted enqueue failed for a notice")

    logger.info("Credits exhausted: %d phone-less record(s) queued for re-poll", queued)
    return {"queued": queued}
