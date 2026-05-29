---
review: pre-merge full-branch
branch: brandon/dm-address-consolidation
target: main
merge_base: cf596cbca556a468c9699114a4863cbf313716e0
reviewed: 2026-05-29
depth: deep (9 parallel gsd-code-reviewer agents, by subsystem)
files_reviewed: 40
findings:
  critical: 7
  warning: 49
  info: 44
  total: 100
verdict: DO_NOT_MERGE_AS_IS
status: issues_found
---

# Pre-Merge Code Review — `brandon/dm-address-consolidation` → `main`

**Reviewed:** 2026-05-29 · **Depth:** deep · **Scope:** all 40 changed `src/*.py` files (13,513 insertions vs `main` merge-base `cf596cb`)
**Method:** 9 `gsd-code-reviewer` agents in parallel, one per subsystem. Per-subsystem detail lives in `.planning/phases/05-auto-skip-trace-death-identity-guard/partials/REVIEW-g1..g9.md`.

> **⚠️ 2026-05-29 UPDATE — CR-04 REFUTED at Wave 0.** A live LP fetch against `p6.php` returned 170 filings, every anchor `db=0`, and the production `_INSTNUM_RE` (`db=(\d+)`) matched **170/170** FORM blocks. CR-04 ("regex drops every LP record") is a **false positive** — the reviewers reasoned from `dlist`/detail-page URLs (`db=` empty) and fabricated `db="P"` fixtures, not the real `p6.php` HIT-LIST anchor. The code is correct as written. **Unique criticals: 12 → 11.** Only the unrealistic *test* is a (low-priority) follow-up. See REMEDIATION-PLAN.md T0.1 RESULT.

## Verdict: do not merge as-is

This branch is the KY probate + lis-pendens correctness/coverage milestone — and the review found that **several of its headline correctness levers do not actually work in the live pipeline**, while the test suite is green. These are *silent-wrong-data* bugs, not crashes: they push confidently-wrong decision-makers, equity figures, comps, and contacts into DataSift, the dialer, and mailers. There is also one security-class issue (CSV formula injection) reachable from untrusted OCR/CourtNet/skip-trace input.

**7 Critical** findings (4 independently verified against source during this review), **49 Warnings**, **44 Info**. The four merge-blockers I'd gate on first:

| ID | One-line | Verified |
|----|----------|----------|
| **G6-CR-01** | Title-path DM rule is dead — trust/survivorship probate leads get the *executor* as DM (the ~26%-wrong-DM failure this milestone exists to fix) | ✅ confirmed |
| **G2-CR-01** | Equity estimator parses a deed book/page (`"D 12345 678"`) as a `$12.3M` lien → wildly negative equity → poisons Phase-4 fit scoring | ✅ confirmed (call site) |
| **G5-CR-01** | Death/identity guard fails **open** — never passes `expected_age`, so a wrong same-name person's phone is CONFIRMED and dialed | ✅ confirmed |
| **G3-CR-01** | Lis-pendens/bulk-deed `instnum` regex requires a numeric `db=`, but live JCD URLs use empty `db=` → may silently drop **every** record | ⚠ needs 1 live-HTML check |

Plus three more Criticals: **G7-CR-01** (CSV formula injection in all 5 exporters), **G9-CR-01** (Drive query injection / apostrophe-address breakage → wrong-property photos), **G5-CR-02** (Dropbox-watcher path bypasses the guard entirely — pre-existing file, not in this diff).

### Cross-cutting themes (read these before the line items)

1. **Green tests mask the production paths.** Three of the worst bugs are invisible because fixtures avoid the real code path: equity tests set `book_page=""` + a test-only `amount` (G2-CR-01); the JCD dedup test monkeypatches `_parse_results_table`, so `_INSTNUM_RE` has no realistic-HTML coverage (G3-CR-01); the guard's age-demotion is never exercised (G5-CR-01). **Every Critical fix needs a regression test that exercises the live shape.**
2. **Fail-open where it must fail-closed.** The identity guard (G5-CR-01), the secondary fit gate (G5-WR-02), and the surviving-owner death check (G1-WR-05) all admit wrong/dead data. Suppression and credit-protection layers must fail closed.
3. **Untrusted strings flow unescaped into sinks.** OCR/CourtNet/skip-trace/CLI text → CSV cells (G7-CR-01), Drive `q=` queries (G9-CR-01), reportlab markup (G9-WR-05). Centralize escaping per sink.
4. **Name/address parsing is the core competency and the most duplicated/divergent code.** "LAST, FIRST" handling differs across 5+ modules (G1-WR-01, G2-WR-05, G5-IN-04, G7-IN-03); surname *substring* matching mis-attributes title (G3-WR-03); city *substring* matching false-positives on dictionary words (G1-WR-03).
5. **`filing_date` does not exist on `NoticeData`.** The re-poll queue keys on it in two places (G4-WR-02, G7-WR-04), so non-case keys always stamp today's date — breaking cross-run idempotency and the attempts cap.
6. **A whole feature is inert, not just buggy.** Beyond G2-CR-01, the `amounts` map is documented but never populated (G2-WR-02), so even ordinary open mortgages net $0 → mortgaged homes report ~90%-capped equity. The equity/lien sweep does not do its job live.
7. **`--no-skip-trace` / fit-gate guarantees don't hold on every ingestion path** (G5-CR-02 Dropbox path).

---

## Critical Issues

### CR-01 (G6-CR-01): Title-path-dependent DM rule is bypassed — trust/survivorship leads get the executor as DM ✅ VERIFIED
**Files:** `src/enrichment_pipeline.py:442-481` (Step 3b.5 CourtNet) vs `:614-638` (Step 3f title classifier); `src/kcoj_case_detail.py:482-538`; `src/kentucky_title_classifier.py:228-308`; `src/obituary_enricher.py:2787-2814`
**Issue:** Three facts combine to make the locked CLAUDE.md rule a no-op:
1. **Ordering inverts the dependency** — CourtNet (`enrich_case_parties_sync`, line 466) runs ~170 lines *before* the title classifier (`classify_title_path`, line 638) that sets `title_path`. So `apply_parties_to_notice` always reads `title_path == ""` → unconditionally writes the executor to `decision_maker_name` with `dm_confidence="high"`. (Verified: 3b.5 at L442/466, 3f at L614/638.)
2. **No code sets a title-derived DM** — `classify_title_path` sets `title_path`/flags but **never** `decision_maker_name` (verified: zero matches in the file). `_extract_successor_trustee`'s return value is only used to set a flag; `_is_surviving_owner` returns a bool and never surfaces the survivor's name.
3. **Obituary step re-asserts the executor** with zero title awareness (no `title_path` reference anywhere in `obituary_enricher.py`).

**Net effect:** every `successor_trustee` (Sauer, Schrenger, Williams, Atlas, Mudd, Long, Guss…) and `surviving_owner` (Hale, Karem, Koch, Layton…) lead gets the personal-estate executor as the mailed/dialed DM — the exact failure this milestone was built to eliminate, shipping green.
**Fix:** (a) have `classify_title_path` assign the title-derived DM (trustee / surviving co-owner) when recoverable; (b) reorder so Step 3f runs **before** Step 3b.5 (the classifier only needs 3c deed-chain + 3d PVA, both available pre-CourtNet); (c) guard the obituary Path-0 executor→DM write when `title_path in (successor_trustee, surviving_owner)`. Add a regression test asserting a trust-owner + CourtNet-executor notice ends with `decision_maker_source` starting `title_`. Full patch in REVIEW-g6.md.

### CR-02 (G2-CR-01): Deed book/page parsed as a dollar lien amount → catastrophic negative equity in production ✅ VERIFIED
**File:** `src/kentucky_equity_estimator.py:180-201` (`_record_amount`), call site `:439`
**Issue:** `_record_amount` resolves a lien's dollar figure as: (1) `amounts` map, else (2) test-only `.amount` attr, else (3) parse `rec.book_page`/`legal_desc`/`doc_type` as money. In production (1) and (2) are never populated — **verified** that `estimate_equity` calls `_net_encumbrances(notice, records, assessed)` at line 439 with **no `amounts` argument** (signature default `amounts=None` at L204-208), and `DeedRecord` from `_parse_deed_list` carries no amount. So every live record hits path (3): a judgment/lis_pendens/tax_cert `book_page` like `"D 12345 678"` → `_parse_money` → `12345678` → a **$12.3M haircut**. A $40K home → equity ≈ −$12.3M / −30,000%, un-clamped by design, straight into `equity_percent` and Phase-4 fit scoring. Green only because every fixture uses `book_page=""` + a test-only `amount`.
**Fix:** Drop the book_page/legal_desc money fallback (return 0 → conservative unknown-lien haircut) AND implement the documented `amounts` map by threading `_fetch_pdetail` amounts through `scan_liens → estimate_equity → _net_encumbrances`. Add a test with `book_page="D 12345 678"` and no `amount`. See REVIEW-g2.md. **(Tightly coupled to G2-WR-02 below — fix together or the feature stays inert.)**

### CR-03 (G5-CR-01): Identity guard never passes `expected_age` → wrong same-name phones confirmed & promoted ✅ VERIFIED
**File:** `src/skip_trace_guard.py:264-280`
**Issue:** The "Armstrong wrong-Barry" guard relies on `kentucky_name_resolver.disambiguate`'s age-mismatch demotion, which fires **only** when `expected_age is not None`. The primary call at `skip_trace_guard.py:272` passes `expected_dod` and `known_addresses` but **not** `expected_age` (verified: `expected_age` appears only at L294 in the no-resolver fallback). With the DM name as both query and sole candidate, `score_match` ≈ 0.85–0.95, no age penalty, `min_score=0.6` clears → `confirmed=True`. The wrong person's phones promote to DM #1 and get dialed — the documented core purpose of Pass 2, defeated.
**Fix:** Compute `expected_age = _expected_age_from_dod(notice)` (already defined, L333) and pass it (plus a candidate DOD when known) into the primary `disambiguate` call. Additionally require positive corroboration (address overlap OR age match) before `confirmed=True` when `traced_age is None`. See REVIEW-g5.md.

### CR-04 (G3-CR-01): `_INSTNUM_RE` requires numeric `db=`, but live JCD HTML uses empty `db=` → risks silently dropping every LP/deed record ⚠ NEEDS LIVE-HTML CHECK
**File:** `src/jefferson_deeds_scraper.py:102`, consumed `:138-141`, `:784-787`
**Issue:** `_INSTNUM_RE = re.compile(r"instnum=(\d+)&year=(\d+)&db=(\d+)")` — the `db=(\d+)` demands ≥1 digit. Two independent evidence lines show `db` is normally **empty** on this site: (a) every live-captured detail URL in the repo's recon scripts shows `&db=&cnum=20` (e.g. `scripts/build_thompson_hale_record.py:119`); (b) this file's own dlist parsers use `db=(\d*)` and `m.group(3) or ""` (L1232, L1278-1283) — the author already knows `db` can be empty. On no-match the record is skipped silently (`if not m: continue`). If `p6.php`'s FORM anchor shares the empty-`db` shape, the **entire lis-pendens daily feed + bulk deed scrape return zero records** — total silent under-coverage. The dedup test stubs out `_parse_results_table`, so this regex has no realistic coverage.
**Fix:** `db=(\d*)` + normalize to `""` + a `logger.debug` on skipped FORM blocks. **Before merge: capture one real `p6.php` HIT-LIST response and confirm the actual `db=` value in the FORM anchor.** If it genuinely carries digits there, this drops to a nit; given all other evidence it's a blocker. See REVIEW-g3.md.

### CR-05 (G7-CR-01): CSV formula injection in all exported CSVs (Excel/Sheets formula-execution class)
**Files:** `src/datasift_formatter.py:870-883` (+`:926-937`, `:961-967`); `src/data_formatter.py:216-314`; `src/datasift_phonebook_formatter.py:150-153`; `src/datasift_sold_properties.py:445-449`
**Issue:** Every writer emits field values verbatim. Owner/decedent/DM names (OCR + CourtNet), phones/emails (Tracerfy), buyer names/addresses (DataSift DOM), and Notes (obituary/source URLs) are all untrusted. A value starting with `=`, `+`, `-`, `@`, or tab/CR becomes a live formula when the operator opens the CSV — and the documented workflow is exactly "download CSV → open → upload to DataSift." Payloads like `=HYPERLINK(...)` or `=cmd|'/c calc'!A1` execute on the operator's machine / exfiltrate cells.
**Fix:** Add a `_csv_safe()` guard (prefix a `'` when `value.lstrip()[:1]` is a trigger) and route every `writerow`/`writerows` cell through it in all five writers. Snippet in REVIEW-g7.md.

### CR-06 (G9-CR-01): Google Drive query injection / apostrophe-address breakage in disposition flyer
**File:** `src/disposition_flyer.py:304-335` (`_find_subfolder`/`_list_images`), `:394-413` (`_trash_existing_flyers`, esp. `:401`)
**Issue:** The CLI-supplied `address` (and the filename derived from it) is interpolated into Drive `q=` expressions. `_trash_existing_flyers` attempts escaping at L401 but does it wrong (`filename.replace("'", r"\'")` only, no backslash escape, and it's the *only* place that tries). Drive treats `'` as the string delimiter; an `O'Brien Ave` address silently fails to trash prior flyers (duplicates accumulate — the exact thing the function prevents) or, with crafted operators, broadens the match → **another property's photos on a buyer-facing flyer** (and the flyer hides the street by design, so a human can't catch it).
**Fix:** One shared `_drive_q_escape(v)` (escape `\` then `'`) applied to every value interpolated into a `q=`. See REVIEW-g9.md.

### CR-07 (G5-CR-02): Dropbox-watcher skip-trace path runs no guard and no fit gate before DataSift upload ⚠ PRE-EXISTING FILE (not in this diff)
**File:** `src/dropbox_watcher.py:319-348`
**Issue:** This ingestion path runs `batch_skip_trace(notices)` (L323, traces **every** notice — no fit gate) then `upload_*(..., skip_trace=True)` (L343/347) with **no `guard_all`/`guard_traced_contacts`** between. The Apify path (`main.py:557-573`) and deep-prospect path (`deep_prospector.py:210-216`) both guard correctly; this one doesn't. Probate photo imports (decedent + executor) are the records most likely to carry a dead spouse's / wrong-same-name number, dialed live. **Verified `dropbox_watcher.py` is unchanged vs `main`** — so this is not a regression from this branch, but the *new* guard/fit-gate was never wired into this pre-existing path, leaving the branch's "guard suppresses on all paths / fit-gated" invariant false.
**Fix:** Mirror `main.py`'s order — fit-gate → trace → `handle_credits_exhausted` → `guard_all` → `apply_contact_fallbacks` — *before* writing the CSV. Extract `is_tracerfy_eligible` into a shared module. See REVIEW-g5.md.

---

## Warnings (49) — grouped by subsystem

### Name resolution / title / parser (G1)
- **G1-WR-01** `kentucky_name_resolver.py:319` — `generate_variants` uses `tokens[0]` as the first name; for "LAST, FIRST" court names that's the *surname*, so maiden/prior/fuzzy variants become `"{maiden} {SURNAME}"` — corrupts the flagship Jackson→Greathouse maiden search and risks wrong-owner PVA attach. *Fix: honor the comma when deriving first/surname.*
- **G1-WR-02** `kentucky_name_resolver.py:276-279` — `_non_anglo_variants` dual-surname rule fires on *any* 3-token name, so "Barry Lee Davis" emits "LEE BARRY" as a PVA query → wrong-owner attach risk. *Fix: gate on a real non-anglo/maiden signal; corroborate before auto-attach.*
- **G1-WR-03** `notice_parser.py:206-242` — `KNOWN_CITIES` now contains dictionary words ("Prospect", "Plantation", "Cambridge"); the substring fallback matcher latches them as the city. *Fix: word-boundary/token match co-occurring with state/zip.*
- **G1-WR-04** `kentucky_title_classifier.py:261-272` — `out_of_estate` can fire on an *unresolved* holder (`"" != "self"`) when `heir_transferred_to` is set, dropping a valid lead's executor DM. *Fix: require `relationship not in ("self","")` or a post-death transfer-date check.*
- **G1-WR-05** `kentucky_title_classifier.py:199` — surviving-owner check uses exact full-string equality vs obituary `preceded_in_death`, so a predeceased co-owner is treated as alive → a **dead** person can be named DM. *Fix: surname + given-token overlap match; fail safe to standard_probate.*

### PVA lookup / equity (G2)
- **G2-WR-01** `kentucky_pva_lookup.py:149-154` (& `:124-129`) — `_login`/`_evict_session` POSTs are unguarded; a transient PVA timeout crashes the whole enrichment batch (every other call degrades). *Fix: wrap in `try/except requests.RequestException` → return False/skip.*
- **G2-WR-02** `kentucky_equity_estimator.py:184-186` vs `:343-395`,`:439` — the `amounts` map is documented but **never populated**, so even open mortgages net $0 → mortgaged homes report ~90%-capped equity. The estimator's core value is silently inert. *Fix: populate amounts from `_fetch_pdetail` (pairs with CR-02).*
- **G2-WR-03** `kentucky_pva_lookup.py:535-554` — `_apply_to_notice` mailing-address regex; on a non-matching format the whole blob lands in `address` and city/zip are left empty (record dropped at validation). *Fix: tolerant parse + always default city/state.*
- **G2-WR-04** `kentucky_pva_lookup.py:509-516` — `_parse_money` strips the decimal point too (`"$399,990.00"` → `39999000`, 100×). Diverges from the deeds scraper's correct parser. *Fix: keep `.`, `int(float(...))`.*
- **G2-WR-05** `kentucky_name_resolver.py:99-105` — `score_match` only checks for a comma in the *first* whitespace token, so "SMITH , JOHN" (OCR space) inverts surname detection → 0 score, missed/wrong parcel. *Fix: detect comma anywhere.*
- **G2-WR-06** `kentucky_pva_lookup.py:234-250` — `_parse_listing_page` trusts a fixed 5-column positional order with no header validation; a PVA layout shift silently swaps owner/parcel/address. *Fix: map columns by header text.*

### Deeds scraper (G3)
- **G3-WR-01** `jefferson_deeds_scraper.py:1713-1721` — `_choose_active_mortgage` treats *any* later-year xref as a release, so an assignment/modification (MERS, loan-mod) wrongly zeroes an open mortgage → overstates equity on distressed-with-lien cases. *Fix: only treat xref as release if the referenced record is itself a RELEASE doc.*
- **G3-WR-02** `jefferson_deeds_scraper.py:131-135` — positional VIEW-image↔FORM pairing misaligns when any filing lacks a scanned image (a documented JCD hole) → a **neighbor's** street/parcel stamped onto a lis-pendens record. *Fix: extract the VIEW image from each form's own DOM window.*
- **G3-WR-03** `jefferson_deeds_scraper.py:1556,1574-1575,1634,1677,1847-1848` — bare surname *substring* match (`LEE in ASHLEE`, `COX in WILCOX`) mis-attributes holder/transfer/parcel across unrelated parties. *Fix: tokenized word-boundary match.*
- **G3-WR-04** `jefferson_deeds_scraper.py:1487-1491` — `_clean_holder_name` generic half-split fires on any even-token string whose halves match (e.g. `SMITH JOHN SMITH JOHN`), dropping a co-owner. *Fix: require a TRUST/entity marker before collapsing.*

### KCOJ probate / re-poll / heirs (G4)
- **G4-WR-01** `scraper.py:727-741` + `kcoj_case_detail.py:660-666` + `kcoj_repoll_queue.py:68-82` — re-poll drain silently drops every obituary-first (non-case-number) lead: the drain re-searches via `enrich_case_parties`, which filters on a non-empty `case_number`, so those entries never get searched, burn the attempts cap, and drop — the freshest leads COVER-01 exists to save. *Fix: route non-case keys to the obituary re-check, or stop enqueuing them.*
- **G4-WR-02** `kcoj_repoll_queue.py:81` — `make_key` reads non-existent `filing_date` → non-case keys always stamp `datetime.now()` → idempotency/attempt-cap defeated across runs. *Fix: use `date_added`.* (Same root as G7-WR-04.)
- **G4-WR-03** `kcoj_case_detail.py:551` — DEC-row decedent backfill is gated on `decedent_name` being empty, but the scraper always fills it, so the authoritative CourtNet DEC name never reconciles a mis-parsed docket name (which then feeds the heir waterfall). *Fix: overwrite-or-warn on mismatch.*
- **G4-WR-04** `kcoj_scraper.py:97-98,218` (& `scraper.py:728`) — case-anchor regex `\d{2}-[A-Z]{1,3}-\d{4,7}` over-matches; a spurious anchor inside a real case's title splits the block and truncates the decedent name. *Fix: constrain year+class; share one constant.*
- **G4-WR-05** `kcoj_case_detail.py:413-441` — `search_case` uses a free-floating `page.on("response")` with no request/case correlation; under slow CourtNet AJAX it can capture another case's party graph → cross-assigned DM. *Fix: `page.expect_response` scoped to the click.*
- **G4-WR-06** `kcoj_case_detail.py:156-166` — `parse_party_sections` fallback path lower-cases only the first key letter; if `result-info` casing differs, every party → "other", no DM assigned, no warning. *Fix: normalize all keys to lowercase in both paths + log fallback use.*

### Fit gate / skip-trace / guard / phones (G5)
- **G5-WR-01** `phone_validator.py:440-450` — a mid-batch Trestle 403 makes `score_record_phones` `return results` with a nondeterministic scored subset; siblings `raise`. *Fix: treat 403 as fatal-for-run consistently (raise) or mark `auth_failed`.*
- **G5-WR-02** `main.py:507-515` — `_passes_fit_gate` fails **open** (`return True`) on an `int()` parse error; only masked today by the fail-closed `is_tracerfy_eligible` ANDed before it. *Fix: fail closed.*
- **G5-WR-03** `skip_trace_guard.py:302-312` + `tracerfy_skip_tracer.py:495-502` — an `unconfirmed` DM keeps its already-promoted flat phones; any reader not checking `decision_maker_status` (CSV/PDF/DataSift) will dial them. *Fix: clear flat phones to a side field on unconfirmed, or gate every emitter on status.*
- **G5-WR-04** `tracerfy_skip_tracer.py:357-364` — the poll-loop `raise_for_status()` is unwrapped; one transient 5xx abandons an already-billed batch (`matched=0`, cost unset). *Fix: per-iteration try/continue; set cost on abandonment.*
- **G5-WR-05** `phone_validator.py:128-135,320,451` — `assign_tier` assumes int scores; a float/string `activity_score` (e.g. `80.5`) → no bucket → "Unknown" drops a dialable number (or `TypeError`). *Fix: coerce `int(round(float(score)))` defensively.*
- **G5-WR-06** `tracerfy_skip_tracer.py:441` — `_maybe_fill_dm_address` reads `rec.get("mail_zip")` but the trace never returns that key → DM gets new street/city with a stale ZIP. *Fix: confirm the real response key; only upgrade address with a corroborating ZIP.*

### Enrichment orchestration / obituary (G6)
- **G6-WR-01** `obituary_enricher.py:1343-1367` — `_lookup_dm_address_ky` opens a `requests.Session()` never closed → fd/socket leak in the long-lived Actor, later HTTP calls fail intermittently. *Fix: `with requests.Session()`.*
- **G6-WR-02** `deep_prospector.py:50-51,202-208` — `_run_level_1` caches skip-trace seams into *module globals* and never restores; a test fake (or earlier call) leaks across batches in one process. *Fix: resolve seams into locals each call; never write back.*
- **G6-WR-03** `obituary_enricher.py:1394-1418` — the KY DM-address branch ignores `tracerfy_tier1`, so the opt-in highest-hit-rate paid lookup is dead for the target market. *Fix: mirror the TN Tier-0 block in the KY branch.*
- **G6-WR-04** `main.py:2197-2200` — daily Tracerfy fit-gate parses `int(n.wholesale_fit_score or 0)` with no try/except despite a "fails closed, never crashes" comment; reachable on CSV-reimport/skipped-gate paths. *Fix: reuse the defensive helper.* (Same family as G7-WR-03, G5-WR-02.)

### Entry / formatters / config (G7)
- **G7-WR-01** `datasift_formatter.py:175-184,388-407` — living-owner contact resolved from a DM/tax/entity fallback is paired with the *owner/property* address → mail to person A at person B's address. *Fix: pull the matching address from the same fallback source.*
- **G7-WR-02** `datasift_phonebook_formatter.py:69-80` vs `datasift_formatter.py:372-415` — the two formatters use different deceased-contact guards, so the two CSVs uploaded for one record can assign conflicting contacts (incl. mailing a decedent). *Fix: one shared `resolve_contact()`.*
- **G7-WR-03** `slack_notifier.py:237-240` — `int(n.wholesale_fit_score)` in `build_summary` is non-defensive; a `"40.0"`/`"n/a"` round-trip `ValueError`s and kills the run summary. *Fix: defensive `_fit_int`.*
- **G7-WR-04** `main.py:585-589,2257-2262` via `kcoj_repoll_queue.py:81` — re-poll bridge keys on non-existent `filing_date` → unstable keys, double-tracked leads. *Fix: `date_added` (or add a real `filing_date` field).* (Same as G4-WR-02.)
- **G7-WR-05** `main.py:238` — `int(actor_input.get("start_page"))` runs before the pipeline `try`; a non-numeric Actor input crashes the run with no `Actor.fail`/Slack notice. *Fix: parse defensively + clamp.*
- **G7-WR-06** `datasift_sold_properties.py:161-174` — `month_range` `strptime` has no error handling; a malformed `--start`/`--end` dies mid-generator. *Fix: validate `^\d{4}-\d{2}$` with a clear message.*

### Comp analyzer / market (G8)
- **G8-WR-01** `comp_analyzer.py:434-446` — `_normalize_sold_date` treats any all-digit string as epoch-ms, so `"2024"` → `1970-01-01` and the comp is silently dropped → skews ARV. *Fix: gate the epoch branch on magnitude (`>= 1e11`); handle bare year.*
- **G8-WR-02** `comp_analyzer.py:484-506,846-858` — `/search`-fallback comps (the common KY path) never split basement out of `ag_sqft`, so above-grade `$/sqft` values below-grade area at 100% of the AG rate instead of 40% → systematic ARV bias. *Fix: don't pre-fill `ag_sqft` with the total; only apply the BG delta when the comp's split is known.*
- **G8-WR-03** `market_analyzer.py:236-237,96-97,120-206` — Competition (10%) and DOM (10%) score off never-populated fields → 20% of the composite is a flat 50.0. *Fix: populate the fields or drop+renormalize the weights.*
- **G8-WR-04** `market_analyzer.py:164-175` — `median_value` is computed as a running **mean** (mislabeled), inflating a right-skewed distribution and penalizing the ZIP. *Fix: rename to mean, or collect + `statistics.median`.*
- **G8-WR-05** `market_analyzer.py:178-187` — equity uses `(running+new)/2`, which exponentially over-weights the last row read → order-dependent. *Fix: sum + count, divide once.*

### PDF / Drive / Playwright (G9)
- **G9-WR-01** `disposition_flyer.py:203-217` — an address with no leading house number → `_house_number` returns `""` → matches the first number-less PVA row → wrong property's beds/baths/owner on the flyer (street is hidden, so invisible). *Fix: treat empty house number as no-match → manual entry.*
- **G9-WR-02** `disposition_flyer.py:401` — `_trash_existing_flyers` escapes the quote wrong (no backslash escape) and is the only place that tries; an apostrophe filename breaks `name='{...}'` and the failure is swallowed → flyers accumulate. *Fix: shared `_drive_q_escape`.* (Pairs with CR-06.)
- **G9-WR-03** `disposition_flyer.py:416-439` — `upload_pdf` builds a 2nd/3rd Drive service (re-decoding the key) and doesn't validate an empty `folder_id` → confusing 4xx. *Fix: pass the built `service` in; validate `folder_id`.*
- **G9-WR-04** `disposition_flyer.py:385-391` — hero `_download_image`/`_folder_link` are unwrapped; one bad image nukes the whole Drive-asset result (loses photo AND link) via the caller's broad except. *Fix: wrap the hero download → degrade to "no hero, keep link".*
- **G9-WR-05** `disposition_flyer.py:732-737` — `data.photos_link` (Drive webViewLink) is interpolated raw into reportlab markup; an unescaped `&` breaks `doc.build` *after* all PVA/Drive work. *Fix: `quoteattr`/escape; wrap `doc.build`.*
- **G9-WR-06** `scraper.py:297` — `can_advance = next_btn and not await ... if next_btn else False` is correct only by luck and treats `disabled=""` (present-but-empty, standard HTML) as enabled. *Fix: presence-of-attribute is the disable signal.*
- **G9-WR-07** `extract_market_finder.py:497-515,571` — `totalPages` from a loose `/of (\d+)/` over `document.body` can stop a page early (silent row loss) or hit the 50-page cap. *Fix: scope the regex to the pagination container; prefer the `from-to of total` triple.*

---

## Info (44) — compact

**G1:** IN-01 dead inner branch `_is_surviving_owner` (`kentucky_title_classifier.py:191-202`); IN-02 `_extract_successor_trustee` regex case-sensitive/greedy (`:154`); IN-03 `score_match` multi-word-surname-before-comma (`kentucky_name_resolver.py:102`); IN-04 `_clean_name.title()` mangles McDonald/O'Brien (`notice_parser.py:1240`).
**G2:** IN-01 PVA `disambiguate` called without `expected_dod`/`expected_age` (`:965-968`); IN-02 `_evict_session` ignores POST result (`:121-129`); IN-03 dead `had_mortgage_records` sub-expr (`equity:457-464`); IN-04 inconsistent None-safety on `current_holder_relationship` (`:821-822`); IN-05 brittle session-id substring/regex — use BeautifulSoup (`:103-118`).
**G3:** IN-01 reads undeclared dynamic attr `decedent_also_known_as` (`:1775`); IN-02 dead `_get` helper (`:75-79`); IN-03 hardcoded 30yr/6% amortization, no confidence flag (`:1020-1021`); IN-04 greedy `_MB_RE` street capture (`:206-209`).
**G4:** IN-01 `_EXECUTOR_PARTY_TYPES` includes unverified codes (`:81`); IN-02 implicit `|`-delimited party-type invariant (`:190-200`); IN-03 `_split_concatenated_jcd_parties` can merge two heirs (`heir_identifier.py:258-313`); IN-04 heir people-search uses only property address for disambiguation (`:469`); IN-05 `candidates.index(notice)` O(n) (`:710`).
**G5:** IN-01/02 `wholesale_fit` bare-attr access vs `getattr` inconsistency (`:99-105`); IN-03 `DM_PHONE_FIELDS` duplicated across 3 modules (drift risk); IN-04 `_split_name` "Last, First" misparses "John Smith, Jr" (`tracerfy:124-129`); IN-05 `handle_credits_exhausted` re-poll count can over-report (`:497-512`).
**G6:** IN-01 `ADDRESS_EXTRACT_PROMPT` hardcodes "Tennessee" — biases KY DM extraction (`obituary:865-889`); IN-02 `_lookup_dm_address_tracerfy` hardcodes `state:"TN"` (`:1252-1267`); IN-03 Knox-tax returns hardcoded `city:"Knoxville"` can overwrite real DM city (`:892-924`); IN-04 inverted step-ordering comments mask CR-01 (`enrichment_pipeline.py:614-624`).
**G7:** IN-01 redundant file write in Actor re-poll bridge (`main.py:590-591`); IN-02 `kcoj_repoll_queue` absent from final state-save block (`:772-780`); IN-03 three divergent `_split_name` impls; IN-04 keep `fit_drop_reason` Counter when fixing WR-03; IN-05 `_format_date` returns raw input on parse failure.
**G8:** IN-01 CLAUDE.md comp-adjustment numbers now stale vs code ($10K not $5K/$7.5K; KY sqft 55) — pick one source of truth; IN-02 `_derive_reno_premium` upper-median bias (`:821-822`); IN-03 garage backfill gated on `needs_yb` (`:586-592`); IN-04 `_street_name` unit-prefix edge (`jefferson_buyer_prospector.py:155-164`); IN-05 CSV errors swallowed at debug (`market_analyzer.py:203`, `buyer_prospector.py:132`); IN-06 deed-cache timestamp differs from run artifacts (`:693-708`).
**G9:** IN-01 three Drive-service builders, mixed scopes, key decoded 2-3×; IN-02 `_format_money` renders `$-5,000` for negative strings (`:501-503`); IN-03 `upload_csv`/`upload_summary` omit `supportsAllDrives` (Shared-Drive 404 risk, `drive_uploader.py:112,174`); IN-04 docstring says "infinite scroll" but code paginates; IN-05 `_select_state` map-fallback hardcodes Tennessee (`:308-314`); IN-06 `captcha_solver` `networkidle` wait has no explicit timeout (`:139`).

---

## Confirmed-correct (explicitly checked, per review briefs)
- DOD sanity check **preserved** through the obituary refactor (full-page `obituary_enricher.py:2434`, snippet `:2486`; fails open on unparseable dates; no off-by-one). *(G6)*
- "Don't overwrite court-named executor" probate preset preserved. *(G6)*
- DM-address consolidation (commit `464686a`) is correctly relocated post-fit-gate and never clobbers a verified address. *(G6)*
- The title-path DM **gating logic in `apply_parties_to_notice` is itself correct** — it's defeated only by step ordering + missing DM assignment (CR-01), not by a logic error. *(G4 & G6)*
- KCOJ sync/async Apify bridge is sound and re-raises worker exceptions. *(G4)*
- Tracerfy/Trestle secret handling is sound (env-sourced, never logged); no injection/unsafe-deserialization in the skip-trace layer. *(G5)*
- Dedup-state persistence (named KVS) and source-gated credential checks in `actor_main` are well-built. *(G7)*
- No mutable-default-argument bugs in the reviewed files. *(G6)*

---

## Recommended path to merge
1. **Fix the 4 verified blockers** (CR-01, CR-02 + G2-WR-02 together, CR-03, CR-05) and **confirm CR-04 against one live `p6.php` capture**.
2. **Fix CR-06/CR-07** (untrusted-input escaping — small, high-leverage) and **wire the guard into the Dropbox path (CR-07/G5-CR-02)**.
3. **Add regression tests that exercise the production shapes** the current suite skips (realistic `book_page`; real-HTML `_INSTNUM_RE`; guard age-demotion; trust-owner → `title_` DM source).
4. Triage the "inert feature" + idempotency warnings (G2-WR-02, G4-WR-01/02, G7-WR-04, G8-WR-02) — these silently under-deliver the milestone.
5. Sweep the fail-open / non-defensive-`int()` family (G5-WR-02, G6-WR-04, G7-WR-03, G7-WR-05) and the duplicated name/`_split_name`/`DM_PHONE_FIELDS` logic in one consistency pass.

Run `/gsd-code-review-fix` to auto-apply fixes from the partials, or address CR-01..CR-07 by hand first (they need design decisions, not mechanical edits).

---

_Consolidated from 9 parallel `gsd-code-reviewer` agents · partials in `.planning/phases/05-auto-skip-trace-death-identity-guard/partials/`_
_Reviewer: Claude (gsd-code-review orchestrator) · Depth: deep · 2026-05-29_
