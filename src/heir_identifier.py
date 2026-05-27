"""Shared best-effort heir identifier (Phase 6 no-probate deaths + Phase 7 lis-pendens).

Turns a decedent with no usable probate party graph into a best-effort list of
candidate heirs, compatible with ``heir_map_json`` so the existing skip-trace
(Phase 5) and report paths work unchanged.

Built ONCE here and consumed by BOTH the Phase-6 no-probate branch (wired in 06-04)
AND Phase 7's lis-pendens unknown-heir cases — so it operates on any ``NoticeData``
with ``owner_deceased="yes"`` (or a death-indexed grantor), not just probate notices.

Source order (best-effort waterfall; returns on the FIRST source that yields heirs):

  1. already-extracted obituary survivors  — READ-ONLY off the notice (NO LLM/URL call)
  2. affidavit of descent                  — deed instrument naming heirs as grantees
  3. deed-grantor history                  — prior grantor/grantee chain as candidates
  4. Phase-1 variant people-search         — defensive import; below-threshold = manual_review

⚠ The obituary source is READ-ONLY. There is no standalone survivor-extraction
callable: the obituary LLM/ranking already ran at enrichment Step 9 and persisted
only its OUTPUT (``notice.heir_map_json`` + ``decision_maker_*`` fields). This module
re-reads those fields; it NEVER calls the obituary enricher, fetches a URL, or runs
an LLM. If nothing usable is on the notice it returns [] and falls through to deeds.

Resilience: each source is wrapped in its own try/except that logs a warning and
continues to the next source — one source failing must not abort the others
(T-06-04). Below-confidence people-search heirs are flagged ``confidence="manual_review"``
and NEVER auto-promoted as confirmed contacts (T-06-05 / T-06-06).
"""

from __future__ import annotations

import json
import logging
import re

from notice_parser import NoticeData

logger = logging.getLogger(__name__)


# ── Constants ─────────────────────────────────────────────────────────

# Affidavit-of-descent instrument types name the decedent's heirs as grantees.
# Regex-bounded match on the (untrusted, scraped) deed doc_type string (T-06-04):
# tolerant of "AFFIDAVIT OF DESCENT", "AFF DESCENT", "AFF. OF DESCENT", etc.
_AFFIDAVIT_OF_DESCENT_RE = re.compile(r"AFF.*DESCENT|AFFIDAVIT OF DESCENT", re.IGNORECASE)

# Map the obituary pass's verified status -> our confidence label.
#   verified_living -> high (corroborated alive); unverified -> manual_review
#   (a real person but not confirmed); deceased -> skip (do not return a dead heir).
_OBIT_STATUS_CONFIDENCE = {
    "verified_living": "high",
    "unverified": "manual_review",
    "deceased": None,  # skip
}

# Phase-1 disambiguation floor (mirror kentucky_name_resolver default).
_MIN_DISAMBIG_SCORE = 0.6

# Bound the number of grantor/grantee parties we mine from a deed chain so a
# pathological scraped page can't explode the heir list (T-06-04).
_MAX_DEED_HEIRS = 25

# Business-entity / non-person tokens to drop from deed grantor/grantee parties.
_ENTITY_RE = re.compile(
    r"\b(LLC|INC|CORP|CO|COMPANY|BANK|TRUST|LP|MORTGAGE|N\.?A\.?|"
    r"ESTATE OF|FARGO|CHASE|CITIZENS|UNION|FEDERAL|CREDIT)\b",
    re.IGNORECASE,
)


# ── Public API ────────────────────────────────────────────────────────


def eligible_for_heir_id(notice: NoticeData) -> bool:
    """Gate: is this notice a candidate for best-effort heir identification?

    PUBLIC so 06-04 (and Phase 7) can pre-check without reaching into a private
    name. True when the owner is a confirmed death (``owner_deceased == "yes"``)
    OR a death-indexed grantor flag is set (``deceased_indicator`` truthy — the
    generic field a lis-pendens caller in Phase 7 can set). This keeps the helper
    general: probate deaths AND lis-pendens unknown heirs both qualify.
    """
    if getattr(notice, "owner_deceased", "") == "yes":
        return True
    if str(getattr(notice, "deceased_indicator", "") or "").strip():
        return True
    return False


def identify_heirs(notice: NoticeData) -> list[dict]:
    """Best-effort heirs for a decedent with no usable probate party graph.

    Sources, in order: obituary survivors (read off the notice) → affidavit of
    descent (deeds) → deed-grantor history → Phase-1 variant people-search.
    Returns heir dicts compatible with ``heir_map_json`` (keys ``name``,
    ``relationship``, ``confidence``, ``source``) and sets ``notice.heir_id_source``
    to whichever source produced the result. Returns [] when the notice is not a
    death (see :func:`eligible_for_heir_id`) or no source yields a heir.
    """
    # Gate FIRST so callers that simply call identify_heirs are correctly gated
    # without needing the predicate (the helper is best-effort, deaths only).
    if not eligible_for_heir_id(notice):
        return []

    sources = (
        ("obituary", _heirs_from_obituary),
        ("affidavit_descent", _heirs_from_affidavit_of_descent),
        ("deed_grantor", _heirs_from_deed_grantor),
        ("people_search", _heirs_from_people_search),
    )

    for source_key, fn in sources:
        try:
            heirs = fn(notice)
        except ImportError as exc:
            # Optional dependency (Phase 1) absent — skip this source gracefully.
            logger.warning("heir_identifier: %s source unavailable (%s) — skipping",
                           source_key, exc)
            continue
        except Exception as exc:  # one source failing must not abort the others
            logger.warning("heir_identifier: %s source failed: %s", source_key, exc)
            continue
        if heirs:
            notice.heir_id_source = source_key
            logger.info("heir_identifier: %d heir(s) from %s for %r",
                        len(heirs), source_key, notice.decedent_name)
            return heirs

    logger.info("heir_identifier: no heirs identified for %r", notice.decedent_name)
    return []


def write_heir_map(notice: NoticeData, heirs: list[dict]) -> None:
    """json.dumps ``heirs`` into ``notice.heir_map_json`` so 06-04 can call one
    function. No-op (and leaves the field unchanged) on a serialization error."""
    try:
        notice.heir_map_json = json.dumps(heirs, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        logger.warning("heir_identifier: could not serialize heir_map_json: %s", exc)


# ── Source 1: obituary survivors (READ-ONLY off the notice) ───────────


def _heirs_from_obituary(notice: NoticeData) -> list[dict]:
    """READ-ONLY obituary heirs already on the notice.

    The Step-9 obituary pass (obituary_enricher) already ran the LLM + ranking and
    persisted its OUTPUT to ``heir_map_json`` and the ``decision_maker_*`` fields.
    This re-reads those — it NEVER calls the obituary enricher, fetches a URL, or
    runs an LLM. Returns [] (falls through) when nothing usable is on the notice.
    """
    # (a) Prefer the full ranked list the obituary pass left in heir_map_json.
    raw = (getattr(notice, "heir_map_json", "") or "").strip()
    if raw:
        try:
            ranked = json.loads(raw)
        except json.JSONDecodeError as exc:
            # Malformed prior output — degrade to the decision_maker_* fallback /
            # the deed sources rather than crashing (T-06-04).
            logger.warning("heir_identifier: malformed heir_map_json, ignoring: %s", exc)
            ranked = None
        if isinstance(ranked, list):
            heirs: list[dict] = []
            for entry in ranked:
                if not isinstance(entry, dict):
                    continue
                name = str(entry.get("name", "")).strip()
                if not name:
                    continue
                status = str(entry.get("status", "unverified")).strip().lower()
                confidence = _OBIT_STATUS_CONFIDENCE.get(status, "manual_review")
                if confidence is None:  # deceased heir — skip, never return a dead heir
                    continue
                heirs.append({
                    "name": name,
                    "relationship": str(entry.get("relationship", "")).strip(),
                    "confidence": confidence,
                    "source": "obituary",
                    "signing_authority": entry.get("signing_authority"),
                })
            if heirs:
                return heirs

    # (b) Fallback: build heirs from the flat decision_maker_* fields.
    heirs = []
    for name_attr, rel_attr, status_attr in (
        ("decision_maker_name", "decision_maker_relationship", "decision_maker_status"),
        ("decision_maker_2_name", "decision_maker_2_relationship", "decision_maker_2_status"),
        ("decision_maker_3_name", "decision_maker_3_relationship", "decision_maker_3_status"),
    ):
        name = (getattr(notice, name_attr, "") or "").strip()
        if not name:
            continue
        status = (getattr(notice, status_attr, "") or "").strip().lower()
        confidence = _OBIT_STATUS_CONFIDENCE.get(status, "manual_review")
        if confidence is None:
            continue
        heirs.append({
            "name": name,
            "relationship": (getattr(notice, rel_attr, "") or "").strip(),
            "confidence": confidence,
            "source": "obituary",
        })
    return heirs


# ── Deed source plumbing (shared by sources 2 & 3) ────────────────────


def _fetch_deed_records(notice: NoticeData) -> list:
    """Fetch the decedent's deed chain via the existing jefferson_deeds_scraper
    plumbing (_search_names_unique → _fetch_deed_list → _parse_deed_list).

    Reuses deed scraping; does NOT rebuild it. Returns [] on any failure or when
    the deeds module / decedent name is unavailable. Monkeypatched in tests so the
    network is never hit.
    """
    query = (getattr(notice, "decedent_name", "") or
             getattr(notice, "owner_name", "") or "").strip()
    if not query:
        return []

    from jefferson_deeds_scraper import (  # imported lazily — deeds is optional
        _search_names_unique, _fetch_deed_list, _parse_deed_list, SUFFIX_RE,
    )

    # Normalize KCOJ "LAST, FIRST MIDDLE" -> space-separated tokens (same as
    # lookup_owner_deed_history does) and strip suffixes for the owner search.
    q = SUFFIX_RE.sub("", query).replace(",", " ")
    q = re.sub(r"\s+", " ", q).strip()

    opener = None
    try:
        from jefferson_deeds_scraper import _make_opener, _accept_disclaimer
        opener = _make_opener()
        _accept_disclaimer(opener)
    except Exception as exc:  # opener setup is best-effort
        logger.warning("heir_identifier: deeds opener setup failed: %s", exc)
        opener = None

    rows = _search_names_unique(opener, q)
    if not rows:
        return []
    # Pick the row with the highest result count (most likely the real person).
    rows_sorted = sorted(rows, key=lambda r: r[2], reverse=True)
    checkbox_value = rows_sorted[0][1]
    html = _fetch_deed_list(opener, checkbox_value)
    if not html:
        return []
    return _parse_deed_list(html)


_NAME_SUFFIXES = frozenset({"JR", "SR", "II", "III", "IV"})


def _split_concatenated_jcd_parties(s: str) -> list[str]:
    """Split a JCD-style concatenated party string into individual parties.

    JCD's ``dlist.php`` renders multi-party grantor/grantee cells with
    HTML structural separators (``<br>``, ``<div>``) that BeautifulSoup's
    ``get_text(" ")`` collapses to plain spaces. The result is one string
    like ``"HUPP CATHY HUPP PAUL E JR"`` (two parties: ``HUPP CATHY`` and
    ``HUPP PAUL E JR``). Each party is in LAST FIRST [MIDDLE] [SUFFIX]
    format per JCD convention.

    Detection algorithm (suffix-anchored):
      1. ``tokens[0]`` is a surname (JCD convention).
      2. Any token immediately following a suffix (``JR``/``SR``/``II``/
         ``III``/``IV``) is a NEW surname.
      3. Walk tokens; close current party + start new when we see a
         surname-marker token (after current has >= 1 token), OR after
         a suffix terminator.

    Limitations: cannot detect a new surname that appears only once and
    isn't preceded by a suffix. E.g. ``"SMITH JOHN JONES JANE"`` (two
    parties, no suffix or repeat) is returned as a single string. This
    is best-effort — better than treating concatenated strings as one
    party, not exhaustive.
    """
    tokens = s.upper().split()
    if not tokens:
        return []

    # Suffix-anchored surname detection: each token following a suffix
    # is confirmed-new-surname for the next party. First token is the
    # initial surname.
    surname_markers: set[str] = {tokens[0]}
    for i, tok in enumerate(tokens):
        if tok in _NAME_SUFFIXES and i + 1 < len(tokens):
            surname_markers.add(tokens[i + 1])

    parties: list[list[str]] = []
    current: list[str] = []
    for tok in tokens:
        if not current:
            current.append(tok)
            continue
        if tok in _NAME_SUFFIXES:
            current.append(tok)
            parties.append(current)
            current = []
            continue
        if tok in surname_markers:
            parties.append(current)
            current = [tok]
            continue
        current.append(tok)
    if current:
        parties.append(current)

    return [" ".join(p) for p in parties]


def _split_deed_parties(party_string: str) -> list[str]:
    """Split a deed grantor/grantee cell into individual party names.

    Three formats seen in JCD data:
      * Explicit separators (clean): "WALKER EARL & WALKER BERTHA",
                                     "MCGARVEY KEVIN; MCGARVEY SHEILA"
      * No separator (concatenated): "HUPP CATHY HUPP PAUL E JR"
                                     "STITH PEGGY ROSE STITH RAYMOND OHARA JAMES"

    Pipeline: first split on explicit separators, then run each result
    through the JCD concatenation splitter when it has >= 4 tokens (the
    longest single name LAST FIRST MIDDLE SUFFIX is 4 tokens — anything
    longer is probably 2+ people). Drop business entities and de-dup
    preserving order. Bounded output.
    """
    if not party_string:
        return []
    parts = re.split(r"\s*(?:&|;|\band\b|,(?!\s*(?:JR|SR|II|III|IV)\b))\s*",
                     party_string, flags=re.IGNORECASE)
    # Each piece may STILL be a concatenated multi-party string.
    expanded: list[str] = []
    for part in parts:
        token_count = len(part.strip().split())
        if token_count >= 4:
            expanded.extend(_split_concatenated_jcd_parties(part))
        else:
            expanded.append(part)
    out: list[str] = []
    seen: set[str] = set()
    for p in expanded:
        name = re.sub(r"\s+", " ", p).strip()
        if not name or len(name) < 3:
            continue
        if _ENTITY_RE.search(name):  # drop banks / LLCs / "ESTATE OF ..."
            continue
        key = name.upper()
        if key in seen:
            continue
        seen.add(key)
        out.append(name)
        if len(out) >= _MAX_DEED_HEIRS:
            break
    return out


# ── Source 2: affidavit of descent ────────────────────────────────────


def _heirs_from_affidavit_of_descent(notice: NoticeData) -> list[dict]:
    """Scan the decedent's deed chain for an AFFIDAVIT OF DESCENT instrument; its
    grantees ARE the named heirs (McGarvey/Walker style). Returns [] when no such
    instrument exists, so the plain deed-grantor source can run next."""
    records = _fetch_deed_records(notice)
    heirs: list[dict] = []
    for rec in records:
        doc_type = getattr(rec, "doc_type", "") or ""
        if not _AFFIDAVIT_OF_DESCENT_RE.search(doc_type):
            continue
        # Grantees on an affidavit of descent are the named heirs.
        for name in _split_deed_parties(getattr(rec, "grantee", "") or ""):
            heirs.append({
                "name": name,
                "relationship": "heir",
                "confidence": "medium",  # named on a recorded instrument, not yet skip-traced
                "source": "affidavit_descent",
            })
    # De-dup across multiple affidavits, preserving order.
    return _dedup_heirs(heirs)


# ── Source 3: deed-grantor history ────────────────────────────────────


def _heirs_from_deed_grantor(notice: NoticeData) -> list[dict]:
    """Fallback: when no affidavit of descent exists, treat the people on the
    decedent's prior deed-grantor chain (grantors + grantees, minus the decedent
    and business entities) as candidate heirs. Lower confidence than an affidavit."""
    records = _fetch_deed_records(notice)
    if not records:
        return []

    dec_surname = _surname(getattr(notice, "decedent_name", ""))
    dec_full = re.sub(r"\s+", " ",
                      (getattr(notice, "decedent_name", "") or "").replace(",", " ")).strip().upper()

    heirs: list[dict] = []
    for rec in records:
        for field in ("grantor", "grantee"):
            for name in _split_deed_parties(getattr(rec, field, "") or ""):
                up = name.upper()
                # Skip the decedent themselves (the deed party that IS the dead owner).
                if up == dec_full:
                    continue
                # Prefer same-surname parties (family transfer heuristic) but keep
                # others at manual_review — never silently drop a candidate.
                if dec_surname and dec_surname in up.split():
                    confidence = "low"
                    relationship = "possible_heir"
                else:
                    confidence = "manual_review"
                    relationship = "deed_party"
                heirs.append({
                    "name": name,
                    "relationship": relationship,
                    "confidence": confidence,
                    "source": "deed_grantor",
                })
    return _dedup_heirs(heirs)


# ── Source 4: Phase-1 variant people-search (defensive import) ────────


def _people_search_candidates(notice: NoticeData, variants: list) -> list[dict]:
    """Seam for the people-search backend. Returns raw candidate dicts
    (``{"name", "relationship", "age"?, "addresses"?, "dod"?}``) for the variant
    surnames. No live people-search backend is wired yet, so this returns [] by
    default — monkeypatched in tests. Kept as its own helper so the test (and a
    future backend) can inject candidates without touching the disambiguation."""
    return []


def _heirs_from_people_search(notice: NoticeData) -> list[dict]:
    """Phase-1 variant people-search for next-of-kin, disambiguated against the
    decedent's DOD / known addresses. Imported DEFENSIVELY — if Phase 1
    (kentucky_name_resolver) is absent this raises ImportError and the waterfall
    skips it gracefully (mirrors the Phase-5 guard).

    Candidates below the Phase-1 disambiguation threshold are KEPT but flagged
    ``confidence="manual_review"`` — never auto-promoted as confirmed (T-06-05/06).
    """
    # Defensive import: absence of Phase 1 -> skip this source (caught upstream).
    from kentucky_name_resolver import (  # noqa: F401  (import is the guard)
        generate_variants, disambiguate, CandidatePerson,
    )

    decedent = (getattr(notice, "decedent_name", "") or "").strip()
    if not decedent:
        return []

    variants = generate_variants(
        decedent,
        maiden_name=getattr(notice, "decedent_obit_maiden_name", None) or None,
        prior_surnames=(
            [s for s in (getattr(notice, "decedent_obit_prior_surnames", "") or "").split(";") if s.strip()]
            or None
        ),
    )

    candidates = _people_search_candidates(notice, variants) or []
    if not candidates:
        return []

    known_addresses = [a for a in (getattr(notice, "address", ""),) if a]
    expected_dod = getattr(notice, "date_of_death", "") or None

    heirs: list[dict] = []
    for cand in candidates:
        name = str(cand.get("name", "")).strip()
        if not name:
            continue
        relationship = str(cand.get("relationship", "possible_heir")).strip() or "possible_heir"
        # Run the Phase-1 disambiguation guard. A confirmed match (>= threshold,
        # with margin) is medium confidence; below-threshold (None) is kept but
        # flagged manual_review — NEVER auto-promoted.
        try:
            cp = CandidatePerson(
                name=name,
                age=cand.get("age"),
                addresses=cand.get("addresses"),
                dod=cand.get("dod"),
            )
            result = disambiguate(
                decedent, [cp],
                expected_dod=expected_dod,
                known_addresses=known_addresses or None,
                min_score=_MIN_DISAMBIG_SCORE,
            )
        except Exception as exc:  # disambiguation failure -> treat as below-confidence
            logger.warning("heir_identifier: disambiguation failed for %r: %s", name, exc)
            result = None

        confidence = "medium" if result is not None else "manual_review"
        heirs.append({
            "name": name,
            "relationship": relationship,
            "confidence": confidence,
            "source": "people_search",
        })
    return _dedup_heirs(heirs)


# ── Shared helpers ────────────────────────────────────────────────────


def _surname(name: str) -> str:
    """Best-effort decedent surname (uppercase). Handles "LAST, FIRST" and
    natural "FIRST LAST" order."""
    name = (name or "").strip()
    if not name:
        return ""
    if "," in name:
        return re.sub(r"[^A-Za-z]", "", name.split(",", 1)[0]).upper()
    tokens = [t for t in re.sub(r"[^A-Za-z\s]", " ", name).upper().split() if len(t) > 1]
    return tokens[-1] if tokens else ""


def _dedup_heirs(heirs: list[dict]) -> list[dict]:
    """De-dup heir dicts on the uppercased name, keeping the first (highest in the
    source order) occurrence."""
    out: list[dict] = []
    seen: set[str] = set()
    for h in heirs:
        key = str(h.get("name", "")).strip().upper()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(h)
    return out
