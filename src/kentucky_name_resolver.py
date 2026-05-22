"""Canonical Kentucky name-variant resolver.

Owns the name primitives shared by PVA, deeds, and obituary enrichment.
Imports nothing from those modules — no cycles.

This module is the foundation of Phase 2e (name-variant resolution). It owns:

  * ``SUFFIX_RE`` — the single canonical JR/SR/II/III/IV/ESQ name-suffix regex
    (de-duplicated from ``kentucky_pva_lookup`` and ``jefferson_deeds_scraper``).
  * ``name_tokens`` / ``score_match`` / ``_search_variations`` — promoted verbatim
    from ``kentucky_pva_lookup`` (behavior-preserving; spec task 2e-1).
  * ``NameVariant`` / ``CandidatePerson`` / ``DisambigResult`` dataclass contracts
    and ``generate_variants`` / ``disambiguate`` stubs that later plans (2e-2/2e-3)
    fill in.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# ── Name matching / scoring ───────────────────────────────────────────

SUFFIX_RE = re.compile(r"\b(JR|SR|II|III|IV|ESQ)\b\.?", re.IGNORECASE)


def name_tokens(name: str) -> list[str]:
    """Normalize a name to a list of uppercase alphabetical tokens."""
    cleaned = SUFFIX_RE.sub("", name).upper()
    cleaned = re.sub(r"[^A-Z\s]", " ", cleaned)
    return [t for t in cleaned.split() if len(t) > 1]


def _search_variations(name: str) -> list[str]:
    """Generate PVA search variations for a decedent name.

    KCOJ decedent names come in multiple formats:
      * "ROLAND, WELDON GENE"     — LAST, FIRST MIDDLE (court format)
      * "WELDON GENE ROLAND"      — FIRST MIDDLE LAST  (natural format)
      * "EWING, WELDON GENE JR"   — with suffix

    PVA owner-search is substring match. Return variations in priority order:
      1. Plain LAST FIRST — matches when decedent is current owner directly
      2. LAST FIRST MIDDLE — same, with middle name/initial
      3. ESTATE OF LAST FIRST — matches when PVA has retitled the property
         to the estate (common after probate is opened; the property is
         still controlled by the estate until distributed to heirs)
    """
    tokens = name_tokens(name)
    if not tokens:
        return []

    variations: list[str] = []
    last = ""
    first_parts: list[str] = []

    comma_match = re.match(r"\s*([^,]+),\s*(.+)", name)
    if comma_match:
        last = " ".join(name_tokens(comma_match.group(1)))
        first_parts = name_tokens(comma_match.group(2))
    elif len(tokens) >= 2:
        # Natural order "FIRST MIDDLE LAST" — assume last token is surname
        last = tokens[-1]
        first_parts = tokens[:-1]

    if last and first_parts:
        # Direct-ownership variations
        variations.append(f"{last} {first_parts[0]}")            # LAST first
        if len(first_parts) > 1:
            variations.append(f"{last} {' '.join(first_parts)}")  # LAST first middle

        # Estate-titled variations. PVA stores these verbatim, e.g.
        # "ESTATE OF SMITH DOLLY" — common format for properties where
        # probate has been opened and title re-issued to the estate.
        variations.append(f"ESTATE OF {last} {first_parts[0]}")
        if len(first_parts) > 1:
            variations.append(f"ESTATE OF {last} {' '.join(first_parts)}")

    # Dedup preserving order, filter empties
    return list(dict.fromkeys(v.strip() for v in variations if v.strip()))


def score_match(decedent_name: str, owner_string: str) -> float:
    """Score how well an owner string matches a decedent name.

    Returns 0..1. Joint owners ("SMITH JOHN & SMITH JANE") score high if the
    decedent's first+last both appear as adjacent tokens.
    """
    dec_tokens = name_tokens(decedent_name)
    owner_tokens = name_tokens(owner_string)
    if not dec_tokens or not owner_tokens:
        return 0.0

    # Must have last name present
    # Assume last token of decedent name is surname for natural order;
    # comma-formatted ("SMITH, JOHN") starts with surname.
    dec_surname = dec_tokens[-1]
    if "," in decedent_name.split(" ", 1)[0]:
        dec_surname = dec_tokens[0]
    if dec_surname not in owner_tokens:
        return 0.0

    # Base: surname match
    score = 0.5

    # Bonus: first-name token appears
    dec_first_candidates = [t for t in dec_tokens if t != dec_surname]
    if dec_first_candidates:
        dec_first = dec_first_candidates[0]
        if dec_first in owner_tokens:
            score += 0.35
            # Extra bonus if surname + first are adjacent (dominant owner,
            # not just a buried joint-owner mention)
            try:
                si = owner_tokens.index(dec_surname)
                fi = owner_tokens.index(dec_first)
                if abs(si - fi) <= 2:
                    score += 0.1
            except ValueError:
                pass

    # Penalty: owner string is an obvious business entity
    if re.search(r"\b(LLC|INC|CORP|TRUST|LP|CO|COMPANY|BANK)\b", owner_string.upper()):
        score -= 0.2

    return max(0.0, min(score, 1.0))


# ── Variant generation + disambiguation contracts ─────────────────────
# Dataclass field shapes are stable now so Plans 02/03/04 implement against
# a fixed contract; the generator/disambiguator bodies land in those plans.


@dataclass
class NameVariant:
    value: str        # normalized search string, e.g. "GREATHOUSE DOROTHY"
    fmt: str          # LAST_FIRST | LAST_FIRST_MIDDLE | ESTATE_OF | SURNAME_ONLY
    source: str       # primary | maiden_obit | maiden_positional | prior_married
                      #  | non_anglo_surname | name_change | typo_fuzzy
    confidence: float


@dataclass
class CandidatePerson:
    name: str
    age: int | None = None
    addresses: list[str] | None = None
    dod: str | None = None


@dataclass
class DisambigResult:
    person: CandidatePerson
    score: float
    reason: str


# Confidence ranking for the variant sources (D-01..D-04). maiden_obit MUST
# outrank maiden_positional (D-02); typo_fuzzy is last and off by default (D-04).
_SOURCE_CONFIDENCE = {
    "primary": 0.90,
    "maiden_obit": 0.95,        # higher than positional per D-02
    "maiden_positional": 0.55,  # fallback-only penultimate guess
    "prior_married": 0.70,
    "non_anglo_surname": 0.65,
    "typo_fuzzy": 0.40,         # last resort, off by default per D-04
}

# Max name length we parse — bounds tokenization/regex cost (T-02-02).
_MAX_NAME_LEN = 200


def _fmt_for_value(value: str) -> str:
    """Derive the structural ``fmt`` label from a search-string shape.

    ESTATE OF ... -> ESTATE_OF; LAST FIRST MIDDLE -> LAST_FIRST_MIDDLE;
    LAST FIRST -> LAST_FIRST; a single token -> SURNAME_ONLY.
    """
    if value.upper().startswith("ESTATE OF "):
        return "ESTATE_OF"
    n = len(value.split())
    if n >= 3:
        return "LAST_FIRST_MIDDLE"
    if n == 2:
        return "LAST_FIRST"
    return "SURNAME_ONLY"


def _maiden_positional(decedent_name: str) -> str | None:
    """Penultimate-token maiden guess (ported from TN ``_maiden_name_variant``).

    For 4+ token names like "LULA ELIZABETH MASSIE JONES" the penultimate token
    ("MASSIE") is the likely maiden surname and the property may be titled
    "MASSIE LULA". Returns ``{penultimate} {first}`` or None for shorter names.
    Fallback ONLY — obituary maiden (``maiden_obit``) outranks it (D-02).
    """
    tokens = name_tokens(decedent_name)
    if len(tokens) < 4:  # need FIRST MIDDLE MAIDEN MARRIED
        return None
    first = tokens[0]
    maiden = tokens[-2]  # penultimate
    return f"{maiden} {first}"


def _levenshtein_le1(a: str, b: str) -> bool:
    """True iff edit distance(a, b) <= 1. Bounded, early-exit (T-02-01).

    Used only for the surname-token typo gate (D-04): MUST accept distance-1
    (TOMPSON->THOMPSON, JACSON->JACKSON) and MUST reject distance-2
    (MEIER->MILLER). Length difference > 1 is already > 1 edit, so reject fast.
    """
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    # Identify the single allowed edit (substitution / insertion / deletion).
    if la == lb:
        # one substitution allowed
        diffs = sum(1 for x, y in zip(a, b) if x != y)
        return diffs <= 1
    # lengths differ by exactly 1 -> one insertion/deletion allowed.
    shorter, longer = (a, b) if la < lb else (b, a)
    i = j = 0
    edited = False
    while i < len(shorter) and j < len(longer):
        if shorter[i] == longer[j]:
            i += 1
            j += 1
        else:
            if edited:
                return False
            edited = True
            j += 1  # skip the extra char in the longer string
    return True


def _non_anglo_variants(decedent_name: str) -> list[str]:
    """Emit per-surname variants for compound / maternal / hyphenated names.

    Covers (CONTEXT-cited cases):
      * Hyphenated: "PALMER-BALL X" -> full + each half ("PALMER X", "BALL X").
        Compound same-token "GONZALEZ-GONZALEZ" collapses to ONE surname (sibling
        cohort, not a typo) — only the deduped halves emit.
      * Hispanic paternal+maternal (3 natural-order tokens FIRST PATERNAL MATERNAL):
        a variant on EACH surname (Farinas: "GARCIA X" AND "FARINAS X"). A plain
        2-token "FIRST LAST" name does NOT double.
      * Slavic feminization: a surname ending in -AYA emits the masculine -IY form
        (LOZINSKAYA -> LOZINSKIY).
    """
    tokens = name_tokens(decedent_name)
    if len(tokens) < 2:
        return []

    out: list[str] = []
    first = tokens[0]

    # Hyphenated surname — look at the RAW (suffix-stripped, uppercased) string so
    # the hyphen survives name_tokens (which would split on it).
    raw = SUFFIX_RE.sub("", decedent_name).upper()
    raw = re.sub(r"[^A-Z\s-]", " ", raw)
    raw_parts = [p for p in raw.split() if len(p) > 1 or "-" in p]
    hyphen_surnames = [p for p in raw_parts if "-" in p]
    for surname in hyphen_surnames:
        out.append(f"{surname} {first}")           # full hyphenated form
        for half in surname.split("-"):
            if half and half != first:
                out.append(f"{half} {first}")       # each half

    # Hispanic paternal+maternal: exactly 3 natural-order tokens, no comma, no
    # hyphen — treat the last TWO tokens as candidate surnames (paternal+maternal).
    if (len(tokens) == 3 and "," not in decedent_name and not hyphen_surnames):
        paternal, maternal = tokens[1], tokens[2]
        out.append(f"{paternal} {first}")
        out.append(f"{maternal} {first}")

    # Slavic feminization: surname ending -AYA -> masculine -IY form.
    surname_last = tokens[-1]
    if surname_last.endswith("AYA") and len(surname_last) > 3:
        masculine = surname_last[:-3] + "IY"
        out.append(f"{masculine} {first}")

    return out


def generate_variants(decedent_name: str, *, maiden_name: str | None = None,
                      prior_surnames: list[str] | None = None,
                      enable_fuzzy: bool = False) -> list[NameVariant]:
    """Produce ordered name-search variants for a decedent (spec task 2e-2).

    Returns a list of ``NameVariant`` ordered highest-confidence-first and
    deduped on ``.value`` (first occurrence wins, so the highest-confidence
    source owns a shared string). Sources, in fixed order (D-01..D-04):

      1. primary            — the existing ``_search_variations`` set.
      2. maiden_obit        — when ``maiden_name`` given; outranks positional.
      3. maiden_positional  — penultimate-token guess, fallback ONLY (no obit).
      4. prior_married      — one ``{surname} {first}`` per ``prior_surnames``.
      5. non_anglo_surname  — Hispanic dual / hyphen split / Slavic feminization.
      6. typo_fuzzy         — surname Levenshtein<=1, ONLY if ``enable_fuzzy``.

    Args:
        decedent_name: the decedent's name (court or natural order).
        maiden_name: obituary-confirmed maiden surname (preferred maiden source).
        prior_surnames: prior-married / legal-change surnames (obit aka / deeds).
        enable_fuzzy: opt-in clerk-typo tolerance (off by default, D-04).
    """
    if not decedent_name:
        return []
    # Bound parsing cost on adversarial / oversized input (T-02-02).
    if len(decedent_name) > _MAX_NAME_LEN:
        decedent_name = decedent_name[:_MAX_NAME_LEN]

    tokens = name_tokens(decedent_name)
    first = tokens[0] if tokens else ""
    variants: list[NameVariant] = []

    def _add(value: str, source: str) -> None:
        value = value.strip()
        if not value:
            return
        variants.append(NameVariant(
            value=value, fmt=_fmt_for_value(value),
            source=source, confidence=_SOURCE_CONFIDENCE[source],
        ))

    # 1. primary — reuse the promoted _search_variations set verbatim.
    for v in _search_variations(decedent_name):
        _add(v, "primary")

    # 2. maiden_obit — preferred maiden source (D-02). Higher confidence.
    if maiden_name and first:
        maiden_tok = name_tokens(maiden_name)
        if maiden_tok:
            maiden_str = " ".join(maiden_tok)
            _add(f"{maiden_str} {first}", "maiden_obit")
            _add(f"ESTATE OF {maiden_str} {first}", "maiden_obit")
    # 3. maiden_positional — fallback ONLY when no obit maiden was supplied.
    elif first:
        positional = _maiden_positional(decedent_name)
        if positional:
            _add(positional, "maiden_positional")

    # 4. prior_married — one variant per prior surname (Underwood->Koenig->Price).
    if prior_surnames and first:
        for surname in prior_surnames:
            stok = name_tokens(surname)
            if stok:
                _add(f"{' '.join(stok)} {first}", "prior_married")

    # 5. non_anglo_surname — Hispanic dual / hyphen split / Slavic feminization.
    for v in _non_anglo_variants(decedent_name):
        _add(v, "non_anglo_surname")

    # 6. typo_fuzzy — last resort, opt-in only (D-04). Surname Levenshtein<=1,
    #    generated only after the exact sources are built.
    if enable_fuzzy and len(tokens) >= 2:
        surname = tokens[-1]
        # Curated near-miss corrections keyed by the typo'd surname token.
        _FUZZY_CANDIDATES = ("THOMPSON", "JACKSON", "JOHNSON", "WILLIAMS",
                             "ROBINSON", "ANDERSON", "THOMAS", "RICHARDSON")
        for cand in _FUZZY_CANDIDATES:
            if cand != surname and _levenshtein_le1(surname, cand):
                _add(f"{cand} {first}", "typo_fuzzy")

    # Sort highest-confidence first (stable -> preserves intra-source order),
    # then dedup on .value (first/highest-confidence occurrence wins).
    variants.sort(key=lambda v: v.confidence, reverse=True)
    seen: set[str] = set()
    deduped: list[NameVariant] = []
    for v in variants:
        if v.value not in seen:
            seen.add(v.value)
            deduped.append(v)
    return deduped


def disambiguate(query_name: str, candidates: list[CandidatePerson], *,
                 expected_dod: str | None = None, known_addresses: list[str] | None = None,
                 min_score: float = 0.6) -> "DisambigResult | None":
    raise NotImplementedError  # filled in Task 2 (spec task 2e-3)
