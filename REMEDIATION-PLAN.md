---
plan: code-review remediation (v2 — whole-repo, blast-radius ordered)
branch: brandon/dm-address-consolidation (already merged to origin/main via PR #14)
repo: github.com/btdavis24/SiftStack
source_reviews:
  - CODE-REVIEW.md            # 40 changed files — 7 Critical, 49 Warning, 44 Info
  - CODE-REVIEW-WHOLE-REPO.md # 23 unchanged src + config + tests — 7 Critical, 54 Warning, 45 Info
unique_criticals: 11          # 7 + 7 − 2 confirmations − 1 refuted (CR-04, Wave 0 live proof)
created: 2026-05-29
updated: 2026-05-29 (folded in 5 new whole-repo criticals + CR-04 regex correction; re-sequenced by blast radius)
method: TDD per fix (failing regression test on the LIVE shape → fix → green), atomic commit each
status_note: This code is ALREADY on main (PR #14). This is fix-forward, not a merge gate. Prioritize by what is actively destructive on each run.
---

# Remediation Plan v2 — SiftStack (fix-forward on `main`)

> **✅ COMPLETE (2026-05-29) — all 11 actionable Criticals fixed + CR-04 refuted.**
> 10 atomic commits on `brandon/dm-address-consolidation`, each test-first; 19/19
> network-free test suites green. Commits: `23c4f0b` (W5-CR-01, W5-CR-02/CR-07),
> `330e592` (W1-CR-01, W1-CR-02), `f70be17` (CR-05), `b26dceb` (CR-06),
> `92cef4a` (W6-CR-01), `cd3180a` (CR-03), `1ef504e` (CR-01), `e70d347` (CR-02),
> `34ead57` (W3-CR-01), `feb3c50` (review/plan docs). Remaining: the Wave 6
> warning sweep + W6-WR-02 XLSX (warnings, not criticals).

Goal: clear all **12 unique Criticals** (and their coupled warnings) found across the two review passes. The code already shipped to `main`, so the framing is **fix-forward, worst-blast-radius first** — not a pre-merge gate.

**Test discipline (applies to every fix):** the suite is green but W8 proved **0 of the original 7 criticals are covered by a test that would fail if the bug were real** (5 fixture-masked, 2 untested). So every fix is test-first against the **live data shape** — not the fixture shape that currently dodges the bug.

## Sequencing principle: blast radius first

```
Wave 0  Verify (recon)        ✅ DONE  CR-04 REFUTED — live LP fetch: regex matched 170/170  ~done
Wave 1  STOP DESTRUCTION               W5-CR-01 data loss · W1-CR-01/02 account-wide        ~1 day
Wave 2  Untrusted-input security       CSV/XLSX inj · Drive escape · reportlab markup        ~0.5 day
Wave 3  Skip-trace safety              CR-03 guard expected_age                              ~3 hr
Wave 4  Correctness blockers           CR-01 title DM · CR-02 equity · W3-CR-01 wholesale    ~2–2.5 days
Wave 5  Test hygiene only              CR-04 refuted → just add a real-HTML regression test  ~1 hr
Wave 6  Warning sweep                  ~20 high-impact warnings, grouped                     ~2 days
```

Rationale for the reorder vs v1: the whole-repo pass found bugs that are **irreversible (data loss) or account-wide (mutate the whole CRM / bill skip-trace on the whole book)** — those now precede the silent-wrong-data correctness bugs, which, while important, only mis-score individual leads. Waves 0 and 1 can start immediately; Wave 4 (design-heavy) can be drafted in parallel.

---

## Wave 0 — Verify before coding (CR-04)

### T0.1 — Confirm the live JCD `db=` value
- **Why:** the W8 audit showed the regex `db=(\d+)` cannot match the real value, and that the test fixtures hand-build `db="P"` records the parser could never have produced. The real value is **alphabetic** (`db=P`/`db=D` per fixtures + the in-file comment), though recon URLs also show empty `db=`. Confirm the actual value in the `p6.php` FORM anchor so the Wave 5 regex is right.
- **Do:** fetch one real `p6.php` HIT-LIST response (`scripts/recon_jcd_deeds.py` or a one-shot), capture the raw HTML to a fixture, record the literal `db=` value.
- **✅ RESULT (2026-05-29): CR-04 REFUTED.** Live LP fetch (`p6.php`, `itype1=LP`, 05/01–05/28/2026): HIT LIST present, **170 LP filings, every anchor `db=0`**, and the production `_INSTNUM_RE` (`db=(\d+)`) matched **170/170** FORM blocks. The 23,162-row deed CSV corroborates (deed anchors also `db=0`). The reviewers were misled by `dlist`/detail-page `<a href>` URLs (`db=` empty — a *different* template, correctly handled by `db=(\d*)`) and fabricated `db="P"` fixtures. **The code is correct as written**; `db=(\d+)` for `p6.php` vs `db=(\d*)` for `dlist` is intentional. No regex change. Residual: the *test* is still unrealistic (W8-WR-08) → see T5.1.
- **Effort:** done (~30 min).

---

## Wave 1 — STOP THE DESTRUCTION (irreversible / account-wide)

These run on the live pipeline and either destroy data or mutate the whole CRM. Highest priority even though some are mechanical.

### T1.1 — Harden `dropbox_watcher.py` (data loss + guard wiring + loop resilience) ⭐ top priority
Fix three findings in one coordinated edit to the watcher loop (`src/dropbox_watcher.py:296-369`):
- **W5-CR-01 (data loss):** `mark_processed(..., delete_after=delete_after)` at `:366` is outside both `if notices:` guards (`:305`, `:312`), so a photo that fails OCR or gets dropped by the fit gate is still deleted — and the cursor (`:168`) already advanced, so it's unrecoverable. **Fix:** track `produced_records`; only `delete_after=True` when a record was written & persisted, else `delete_after=False` + log for manual re-OCR. Decouple cursor advance from "queued."
- **W5-CR-02 / CR-07 (guard bypass):** the watcher runs `batch_skip_trace(notices)` (`:323`) then uploads `skip_trace=True` with **no fit gate and no `guard_all`**. **Fix:** mirror `main.py:2197-2233` order — fit-gate filter → `batch_skip_trace` → `handle_credits_exhausted` → `guard_all` → `apply_contact_fallbacks` — *before* `write_datasift_split_csvs`/upload. Extract `is_tracerfy_eligible` (`main.py:37`) into a shared module (`skip_trace_guard` or new `skip_trace_gate`) so both entry points share the predicate.
- **W5-WR-01 (daemon dies):** wrap the per-group body in try/except so one bad group doesn't kill the watcher; on exception, do **not** delete the source.
- **Tests:** `tests/test_dropbox_watcher.py` (new) — (a) OCR returns `[]` → source NOT deleted; (b) a dead-DM notice → guard suppressed the phone before the CSV write; (c) a non-fit notice → not traced; (d) an exception in one group → loop continues, source retained.
- **Risk:** medium (changes deletion + adds guard). **Effort:** ~0.5 day.

### T1.2 — `datasift_uploader.py` fail-closed (account-wide mutation)
- **W1-CR-01:** on `_filter_by_list` failure, `enrich_records` (`:744`) and `skip_trace_records` (`:898`) `# continue anyway` and act on the **whole account**. **Fix:** fail closed — abort if the filter didn't apply; have `_filter_by_list` return the applied count and assert it's non-zero and not the full-account total before `_select_all_records`.
- **W1-CR-02:** the "Enrich Owners / Swap Owners OFF" protection (`:797-852`) is never verified — on label drift it returns `{}` and clicks Enrich with modal defaults → can overwrite all DM contacts. **Fix:** require positive confirmation both toggles were located and set OFF; abort + screenshot otherwise.
- **W1-WR-02 (coupled):** `_select_all_records` returns `True` on button-presence, not selection count — fold in a count read-back so these aborts are reliable.
- **Tests:** hard to unit-test Playwright; add a logic-level test for the new guard predicates (filter-failed → abort; toggles-not-confirmed → abort) by factoring them into pure helpers.
- **Risk:** medium. **Effort:** ~0.5 day.

---

## Wave 2 — Untrusted-input security (one escaping pass per sink)

Same root cause across sinks: OCR/CourtNet/LLM/scraped/CLI strings reach a sink unescaped.

### T2.1 — CSV/XLSX formula injection (CR-05 + W6-WR-02 + W2-WR-05)
- **Files:** `datasift_formatter.py`, `data_formatter.py`, `datasift_phonebook_formatter.py`, `datasift_sold_properties.py`, `excel_exporter.py` (`:390,397,487,497,576`), `niche_sequential.py` (channel exporters).
- **Fix:** one shared `_csv_safe(v)` (prefix `'` when `v.lstrip()[:1] in ("=","+","-","@","\t","\r")`) for CSV writers and `_safe_cell(v)` for openpyxl cells. Route every data-cell write through it (not headers/numerics).
- **Test:** owner `=cmd|'/c calc'!A1` / Notes `@SUM(...)` written neutralized; in both CSV and the `Sift Upload` XLSX sheet.
- **Risk:** very low. **Effort:** ~2-3 hr.

### T2.2 — Drive query escaping (CR-06 + G9-WR-02 + W8-WR-06)
- **File:** `disposition_flyer.py` (`_find_subfolder`, `_list_images`, `_trash_existing_flyers:401`).
- **Fix:** `_drive_q_escape(v) = v.replace("\\","\\\\").replace("'","\\'")` applied to every value interpolated into a Drive `q=`.
- **Test:** apostrophe address `5103 O'Brien Ave` → query contains escaped `\'`, well-formed.
- **Risk:** very low. **Effort:** ~1 hr.

### T2.3 — reportlab markup injection + render crash (W6-CR-01 + W6-WR-01 + W6-WR-05 + W6-WR-06)
- **File:** `report_generator.py`.
- **Fix:** route every untrusted value through `escapeOnce`/`xml.escape` (chokepoints `_data_table:178` + `_add_signing_chain:545` cover most); wrap `doc.build()` (`:511`) to delete the partial file on failure; use `.get` for `info["score"]` (`:486,573`); type-guard `heir_map_json` items (mirror `case_summary.group_heirs`).
- **Test:** a notice with owner `SMITH & JONES ESTATE` + a `<` in an heir name renders a valid PDF (no `doc.build` crash); a partial Trestle result (no `score`) doesn't crash.
- **Risk:** low. **Effort:** ~3 hr.

---

## Wave 3 — Skip-trace safety

### T3.1 — Identity guard fails open (CR-03)
- **File:** `skip_trace_guard.py:264-280`.
- **Fix:** compute `expected_age = _expected_age_from_dod(notice)` (already defined `:333`) and pass `expected_age=` into the primary `disambiguate(` call (`:272`). When `traced_age is None` and no address overlap, do NOT default `confirmed=True` — require positive corroboration (fail-closed).
- **Test (un-stub the scorer — W8-WR-02/03):** real `disambiguate` with `CandidatePerson(age=80, addresses=["999 Wrong Ave"])` vs a decedent context (`expected_dod`, `known_addresses=["123 Real St"]`) → DM flagged `unconfirmed`, phones not promoted. (The current test stubs `disambiguate → None`, which hides the wiring gap.)
- **Note:** the Dropbox-path guard wiring (CR-07) is handled in T1.1; this is the daily/deep-prospect path's `expected_age` gap.
- **Coupled:** W5-WR-03 / G5-WR-03 — clear unconfirmed flat phones to a side field so no downstream reader can dial them.
- **Risk:** low-medium. **Effort:** ~3 hr.

---

## Wave 4 — Correctness blockers (design + careful tests)

### T4.1 — CR-01: make the title-path DM rule actually fire ⭐ biggest fix
**Files:** `enrichment_pipeline.py` (`:442-647`), `kcoj_case_detail.py` (`apply_parties_to_notice:482-538`), `kentucky_title_classifier.py` (`classify_title_path:228-308`, `_extract_successor_trustee:133-159`, `_is_surviving_owner`), `obituary_enricher.py` (`:2303-2324`, `:2787-2814`).

**Root cause (verified):** CourtNet (Step 3b.5, `enrich_case_parties_sync` `:466`) assigns the executor as DM *before* the title classifier (Step 3f, `classify_title_path` `:638`) sets `title_path`; the classifier never sets a title-derived DM; the obituary step later re-asserts the executor with no title awareness. The title-gate in `apply_parties_to_notice` reads an always-empty `title_path`.

**Why not just reorder:** Step 3c's deed search uses the CourtNet executor name as a fallback search term (`:447-448`, `:493`). Moving CourtNet after 3c/3d/3f regresses that. **So split CourtNet's fetch from its DM assignment** (chosen approach; full-reorder is the lossier alternative).

**Approach (4 coordinated changes):**
1. **Classifier sets the title-derived DM** — in `classify_title_path`, on `successor_trustee` set `decision_maker_name = _extract_successor_trustee(notice)` (relationship `successor_trustee`, source `title_successor_trustee`, confidence medium) when recoverable, else `trustee_unconfirmed="yes"` (fall back to executor per locked decision 3). On `surviving_owner`, add `_surviving_owner_name(notice)` (promote `_is_surviving_owner` to return the alive co-owner — also fixes G1-WR-05's exact-match gap) and set the DM to that survivor.
2. **Split CourtNet (3b.5)** — keep the early network *fetch* (sets `owner_name`=executor for search fallback, `estate_attorney_name`, `courtnet_party_types`, decedent reconcile) but stop finalizing the DM there. Add **Step 3g (after 3f)**: a pure `assign_dm_from_parties(notice)` that reads `title_path` + stored executor (`owner_name`) + party types + any title-derived DM and applies the existing title-gate logic. All inputs are persisted NoticeData fields → no re-fetch.
3. **Obituary Path-0 guard** — skip the executor→DM overwrite when `title_path in ("successor_trustee","surviving_owner") and not trustee_unconfirmed` and a title-derived DM is present (mirror `kcoj_case_detail.py:482-486`).
4. **Fix the inverted comments** at `:447-448` and `:614-619`.

**Tests (end-to-end, not isolated — W8-WR-04):** start from a NoticeData with only `pva_owner_string`/`current_property_holder` set, run classify → assign → `apply_parties_to_notice(EXECUTOR_PARTIES)`, assert final `decision_maker_source` starts `title_` and DM = trustee/survivor for trust/survivorship, executor for standard_probate, executor-fallback for unextractable trustee. Sanity-check against memory fixtures (Sauer/Schrenger/Williams = trust; Hale/Karem = survivorship).
**Risk:** medium-high. **Effort:** ~1–1.5 days.

### T4.2 — CR-02 + G2-WR-02: equity estimator (full fix — decision A) ✅ scope locked
**Files:** `kentucky_equity_estimator.py` (`_record_amount:180-201`, `_net_encumbrances:204-322`, `scan_liens:343-395`, call site `:439`); `jefferson_deeds_scraper.py` (`_fetch_pdetail`, `_parse_money`).
- **CR-02:** remove the `book_page`/`legal_desc`/`doc_type` money fallback from `_record_amount` (path 3) → return 0 (conservative haircut) instead of parsing `"D 12345 678"` as $12.3M.
- **G2-WR-02 (full fix A, chosen):** populate the documented `amounts` map — in `scan_liens`, `_fetch_pdetail` the mortgage/lien records to be netted, `_parse_money` the principal, build `amounts[instnum]`, thread through `estimate_equity → _net_encumbrances(..., amounts=amounts)`. Guard the new network calls with the PVA degrade-don't-crash pattern (timeout → skip record, never abort the sweep); cache by instnum.
- **Test (W8-WR-01):** fixture with realistic `book_page="L 11234 567"` and **no** `amount` → haircut is the placeholder, not 11234; plus an `amounts`-populated case asserting a real mortgage nets its balance.
- **Risk:** CR-02 low; the amounts-map network additions need the error guard. **Effort:** ~0.5–1 day.

### T4.3 — W3-CR-01: wholesale buyer-profit math
- **File:** `deal_analyzer.py:252-265`, call site `:730`.
- **Fix:** charge the buyer side on the same basis as `calculate_flip` (include holding costs); contract at the **wholesale** MAO (`mao.wholesale_mao`) not the flip MAO; rank WHOLESALE on a comparable metric, not the hardcoded `100` (W3-WR-05).
- **Test:** a property where flip ROI > wholesale margin → recommendation is FLIP, not WHOLESALE; buyer-profit parity between paths on identical inputs.
- **Coupled:** W3-WR-01 (phantom-mortgage equity on free-and-clear homes) is the highest-value Wave-6 warning — consider pulling it forward here since it mis-scores the core KY use case.
- **Risk:** low-medium. **Effort:** ~3 hr.

---

## Wave 5 — Test hygiene only (CR-04 refuted)

CR-04 is **not a bug** (Wave 0 live proof: regex matched 170/170 LP filings). **No production change.** The only residual is the unrealistic test that hid the false alarm.

### T5.1 — Lock the real `p6.php` parse behavior with a regression test (W8-WR-08)
- **File:** `tests/test_jcd_*` (new real-HTML case).
- **Do:** capture one real `p6.php` LP FORM block (db=0) as a fixture (sample already on disk: `output/recon_jcd_deeds/02_one_day_*.html`) and feed it through the **UNPATCHED** `_parse_results_table`; assert ≥1 record parses with `db=="0"`. This prevents a future "fix" from breaking the regex on the false premise the reviewers had. Keep the existing dedup tests but stop hand-building `db="P"` records the parser can't produce.
- **Do NOT** change `_INSTNUM_RE` — `db=(\d+)` is correct for `p6.php`.
- **Risk:** none (test-only). **Effort:** ~30 min.

---

## Wave 6 — High-impact warning sweep (grouped; some auto-fixable via `/gsd-code-review-fix`)

Pull-forward candidate: **W3-WR-01** (equity model fabricates an 80%-LTV mortgage on free-and-clear inherited homes — the core KY use case — under-scoring fit). Strongly consider doing this in Wave 4.

- **Inert-feature / coverage:** G4-WR-01 (re-poll drops obituary-first leads), G8-WR-01/02 (comp date + basement), W5-WR-02 (foreclosure filter bare-word excludes drop valid trustee sales — critical domain filter).
- **Idempotency:** G4-WR-02 + G7-WR-04 (`filing_date` doesn't exist → `date_added`).
- **Fail-open / non-defensive int:** G5-WR-02, G6-WR-04, G7-WR-03, G7-WR-05 → shared `_fit_int` that fails closed.
- **Money/name/address parsing:** G2-WR-04 (PVA decimal strip 100×), G1-WR-01/02/03 + W3-WR-07 (the "LAST, FIRST" / city family — consider one shared name-parse + a conservative city matcher), G3-WR-01/02/03.
- **Security tail:** W1-WR-03 (cookie exfil to `*-reisift` substring), W3-WR-08 (entity-research prompt injection), W3-WR-09 (SSRF / `allow_redirects`), W4 LLM provenance/crash + image-size cap, W5-WR-03 (public PII Dropbox links), W7-WR-01 (`.dockerignore`), W7-WR-02 (pin deps).
- **Resilience:** G2-WR-01 (`_login` unguarded), G6-WR-01 (unclosed PVA Session), G4-WR-05 (`page.on("response")` cross-talk → `expect_response`), G5-WR-04 (Tracerfy poll-loop aborts billed batch), W6-WR-03 (`sys.exit` in library), W6-WR-04 (silent hyperlink except).
- **Consistency:** G7-WR-01/02 + G7-IN-03 (shared `resolve_contact` + one `_split_name`), G5-WR-03 (clear unconfirmed phones — pairs with T3.1), W6-IN-05/G9 (migrate `report_generator`/`disposition_flyer` to `brand_pdf`).
- **Test hygiene (W8-WR-09):** move live/paid scripts (`test_captcha_live.py`, `test_e2e_obituary.py`) under `tests/live/` or gate behind `LIVE=1`.

**Effort:** ~2 days.

---

## Decisions
1. **CR-02 equity depth** — ✅ RESOLVED: **Full fix (A)** — drop bad fallback + implement the amounts map.
2. **CR-01 approach** — **split CourtNet fetch/assign** (default; preserves the executor-search-fallback). Open for review at execution.
3. **Execution order** — ✅ RESOLVED: **HOLD** — plan only; no code changes until a wave is kicked off.
4. **NEW — Wave 1 priority** — the data-loss (W5-CR-01) and account-wide (W1-CR-01/02) bugs are now sequenced ahead of the original correctness criticals, since they are destructive on every run. Confirm this ordering or re-prioritize.

## Definition of done (fix-forward on `main`)
- [ ] **Wave 1 destructive bugs fixed first:** Dropbox no longer deletes on failure; uploader fails closed; guard wired into the watcher path
- [ ] All **11 unique Criticals** fixed (6 remaining original + W1-CR-01, W1-CR-02, W3-CR-01, W5-CR-01, W6-CR-01), each with a regression test that fails on the **live shape**
- [x] CR-04 — ✅ REFUTED at Wave 0 (live LP fetch matched 170/170); no fix needed, real-HTML test in T5.1
- [ ] Untrusted-input escaping applied to every sink (CSV, XLSX, Drive `q=`, reportlab)
- [ ] Full suite green incl. the new live-shape + un-stubbed tests
- [ ] Targeted re-review of the touched files shows criticals resolved
- [ ] Wave 6 warnings triaged (fix-now vs tracked-issue), W3-WR-01 decided (Wave 4 vs 6)

_Plan paired with CODE-REVIEW.md + CODE-REVIEW-WHOLE-REPO.md · per-finding detail in `.planning/phases/05-auto-skip-trace-death-identity-guard/partials/` (+ `/whole-repo/`)_
