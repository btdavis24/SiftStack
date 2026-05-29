"""Re-poll queue store for fresh 0-row KY probate / obituary leads (Phase 6 / COVER-01).

The daily pipeline currently DROPS a just-filed lead when CourtNet returns 0 parties
or the obituary isn't posted yet — the very freshest, most-distressed leads. This store
lets the drain step (06-03b) re-search those leads after a short delay instead.

It mirrors the existing cross-run dedup plumbing in ``kcoj_scraper.load_kcoj_seen_cases``
/ ``save_kcoj_seen_cases`` (kcoj_scraper.py:58-79): same module shape, same
``config.load_state`` / ``config.save_state`` persistence on a dedicated state file
(``KCOJ_REPOLL_FILE``), Apify-KVS-mirrorable exactly like ``kcoj_seen_cases``.

Value-shape divergence from seen-cases (documented intentionally): seen-cases is
``dict[str, str]`` (case_number -> first-seen date, used only for pruning). The re-poll
queue is ``dict[str, dict]`` because each entry must also carry an attempt counter and an
audit reason::

    {
      "<key>": {"repoll_after": "YYYY-MM-DD", "attempts": int, "reason": str},
      ...
    }

``<key>`` is the case_number when known, else ``"<decedent_name>|<filing-or-today date>"``
(see ``make_key``).

Unlike seen-cases there is NO time-based prune: entries self-expire — they are removed on
success by the drain (06-03b) or dropped at ``REPOLL_MAX_ATTEMPTS`` by ``bump_or_drop``.
This caps unbounded growth (threat T-06-02) and stops a poisoned entry re-polling forever
(threat T-06-01); a missing/corrupt file degrades to ``{}`` via ``config.load_state``'s
.bak fallback rather than crashing the run.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import config
from config import KCOJ_REPOLL_FILE, REPOLL_DELAY_BUSINESS_DAYS, REPOLL_MAX_ATTEMPTS

logger = logging.getLogger(__name__)

_DATE_FMT = "%Y-%m-%d"


# ── Persistence (mirrors kcoj_scraper.load/save_kcoj_seen_cases) ──────────
# Same shape as the seen-cases store, but no 90-day prune: re-poll entries
# self-expire (removed on success, or dropped at max attempts). The value is a
# richer dict (attempts + reason), not a bare date — see module docstring.


def load_repoll_queue() -> dict[str, dict]:
    """Load the re-poll queue, or ``{}`` if no file exists / it is unreadable.

    Tolerates a missing or corrupt state file via ``config.load_state``'s .bak
    fallback (returns ``{}``) rather than crashing the daily run (threat T-06-01)."""
    data = config.load_state(KCOJ_REPOLL_FILE)
    return data or {}


def save_repoll_queue(queue: dict[str, dict]) -> None:
    """Persist the queue atomically (tmp -> rename + .bak) via config.save_state."""
    config.save_state(KCOJ_REPOLL_FILE, queue)


# ── Keying ────────────────────────────────────────────────────────────────


def make_key(notice) -> str:
    """Queue key for a notice: case_number when present, else ``decedent|date``.

    A just-filed lead may not have a case_number yet (obituary-first discovery),
    so we fall back to ``"<decedent_name>|<date_added or today>"``. Returns ""
    when there is neither a case number nor a decedent name to key on — the caller
    should not enqueue an unkeyable lead (``enqueue_repoll`` no-ops on a falsy key)."""
    case = (getattr(notice, "case_number", "") or "").strip()
    if case:
        return case
    decedent = (getattr(notice, "decedent_name", "") or "").strip()
    if not decedent:
        return ""
    # ``filing_date`` is NOT a NoticeData field (kept first for forward-compat if
    # one is ever added); ``date_added`` IS the real per-lead field. Prefer it over
    # datetime.now() — otherwise the same un-cased lead keys to a DIFFERENT date
    # each run, defeating the attempts-cap / dedup idempotency (G4-WR-02 / G7-WR-04).
    date = (
        (getattr(notice, "filing_date", "") or getattr(notice, "date_added", "") or "").strip()
        or datetime.now().strftime(_DATE_FMT)
    )
    return f"{decedent}|{date}"


# ── Date math ───────────────────────────────────────────────────────────────


def business_days_from(today_str: str, n: int) -> str:
    """Return ``today_str`` + ``n`` business days (skipping Sat/Sun), as YYYY-MM-DD.

    Step day-by-day, counting only weekdays (Mon-Fri). E.g. Mon +4 -> Fri;
    Thu +4 -> the following Wed (Fri, [skip weekend], Mon, Tue, Wed)."""
    cur = datetime.strptime(today_str, _DATE_FMT)
    counted = 0
    while counted < n:
        cur += timedelta(days=1)
        if cur.weekday() < 5:  # Mon=0 .. Fri=4; skip Sat(5)/Sun(6)
            counted += 1
    return cur.strftime(_DATE_FMT)


# ── Queue operations ──────────────────────────────────────────────────────


def enqueue_repoll(queue: dict[str, dict], key: str, *, reason: str = "", today: str | None = None) -> None:
    """Enqueue a 0-row lead for re-search after REPOLL_DELAY_BUSINESS_DAYS.

    No-op on a falsy key (unkeyable lead). If ``key`` is already pending, leave its
    attempts/date untouched (already scheduled) and log at debug — re-enqueuing must
    NEVER reset progress toward the max-attempts cap. Otherwise insert a fresh entry
    with ``attempts=0`` and a business-day-offset ``repoll_after``."""
    if not key:
        return
    if key in queue:
        logger.debug("Re-poll: %s already queued (repoll_after=%s, attempts=%s) — leaving as-is",
                     key, queue[key].get("repoll_after"), queue[key].get("attempts"))
        return
    base = today or datetime.now().strftime(_DATE_FMT)
    repoll_after = business_days_from(base, REPOLL_DELAY_BUSINESS_DAYS)
    queue[key] = {"repoll_after": repoll_after, "attempts": 0, "reason": reason}
    logger.info("Re-poll: enqueued %s (repoll_after=%s, reason=%s)", key, repoll_after, reason or "-")


def due_entries(queue: dict[str, dict], today: str | None = None) -> list[str]:
    """Return keys whose ``repoll_after`` is on/before ``today`` (string YYYY-MM-DD
    compare, same as the seen-cases prune cutoff). Future-dated entries are excluded."""
    cutoff = today or datetime.now().strftime(_DATE_FMT)
    return [k for k, v in queue.items() if v.get("repoll_after", "") <= cutoff]


def bump_or_drop(queue: dict[str, dict], key: str, *, today: str | None = None,
                 max_attempts: int = REPOLL_MAX_ATTEMPTS) -> str:
    """After a still-empty re-search: bump the entry, or drop it once exhausted.

    Increments ``attempts``. If the bumped count reaches ``max_attempts``, remove the
    key and log a warning audit note — a re-poll cannot run forever (threats T-06-01 /
    T-06-02). Otherwise store the new ``attempts`` and a fresh business-day ``repoll_after``.

    Returns ``"dropped"`` (key removed) or ``"bumped"`` (rescheduled). A missing key is
    treated as already-gone -> ``"dropped"``."""
    entry = queue.get(key)
    if entry is None:
        return "dropped"
    attempts = int(entry.get("attempts", 0)) + 1
    if attempts >= max_attempts:
        queue.pop(key, None)
        logger.warning("Re-poll exhausted (%d attempts) — dropping %s [%s]",
                       attempts, key, entry.get("reason", "") or "-")
        return "dropped"
    base = today or datetime.now().strftime(_DATE_FMT)
    entry["attempts"] = attempts
    entry["repoll_after"] = business_days_from(base, REPOLL_DELAY_BUSINESS_DAYS)
    logger.info("Re-poll: bumped %s -> attempt %d, repoll_after=%s",
                key, attempts, entry["repoll_after"])
    return "bumped"
