---
review: whole-repo (previously-unreviewed code)
branch: brandon/dm-address-consolidation (= origin/main via PR #14)
repo: github.com/btdavis24/SiftStack (renamed from btdavis24/bdavis)
reviewed: 2026-05-29
depth: deep + standard (8 parallel agents by subsystem)
scope: 23 src modules never covered by CODE-REVIEW.md + config/infra + test-suite audit
findings:
  critical: 7   # 5 new + 2 confirming earlier findings
  warning: 54
  info: 45
  total: 106
status: issues_found
complements: CODE-REVIEW.md (the 40 changed files)
---

# Whole-Repo Code Review — completes coverage of `btdavis24/SiftStack`

This is the **second pass**. [CODE-REVIEW.md](CODE-REVIEW.md) covered the 40 files the `dm-address-consolidation` work changed. This pass covers everything that review skipped: the **23 `src` modules that ship on `main` but were untouched by the branch**, the **config/infra**, and a **test-suite audit**. Together the two passes cover **all 63 `src/*.py` modules**, config, and tests. (`scripts/` — 17 tracked recon one-offs + the untracked `find_*`/`build_*` scripts — remains intentionally out of scope as throwaway tooling.)

8 agents (W1–W8). **7 Critical** (5 new + 2 confirming earlier findings), **54 Warning**, **45 Info**. Two new criticals were independently verified against source during this review.

> **⚠️ 2026-05-29 UPDATE — W8-CR-01 (= CR-04) REFUTED at Wave 0.** A live LP fetch against `p6.php` returned 170 filings, all `db=0`; the production `_INSTNUM_RE` matched **170/170** FORM blocks. W8 correctly caught that the *tests* are unrealistic (monkeypatched parser + fabricated `db="P"`), but the underlying *code* is fine — `db=(\d+)` matches the real `db=0`. So W8-CR-01 downgrades from a code bug to a **test-hygiene** item (W8-WR-08). The other 6 whole-repo criticals stand. See REMEDIATION-PLAN.md T0.1 RESULT.

## Headline: the un-reviewed `main` code is worse than the diff

The previously-unreviewed modules carry a **data-loss bug**, a **fail-open that mutates the entire CRM account**, and a **render-crash that produces no deliverable** — none of which the first pass could see. The test-suite audit (W8) is the capstone: **0 of the 7 original Criticals are covered by a test that would fail if the bug were real** — 5 are fixture-masked, 2 untested. The green suite is structurally blind to exactly these bugs.

| ID | New? | One-line | Verified |
|----|------|----------|----------|
| **W5-CR-01** | NEW | **Data loss:** Dropbox deletes the source photo even when OCR returns nothing / enrichment drops all — un-reshootable courthouse captures gone for good | ✅ confirmed |
| **W1-CR-01** | NEW | **Fail-open, account-wide:** if list-filter fails, enrich + skip-trace `# continue anyway` and act on the **entire DataSift account** (re-tag/skip-trace/overwrite the whole book) | ✅ confirmed |
| **W1-CR-02** | NEW | The "Enrich Owners / Swap Owners OFF" protection is never verified — on label drift it clicks Enrich with modal defaults → can overwrite all DM contacts | (static) |
| **W6-CR-01** | NEW | reportlab markup injection: unescaped `&`/`<`/`>` in a real name (`SMITH & JONES ESTATE`) crashes `doc.build()` → no PDF, partial file left | (static) |
| **W3-CR-01** | NEW | Wholesale buyer-profit math omits buyer holding costs + is fed the flip MAO → inflated `buyer_profit_estimate` drives a wrong go/no-go | (static) |
| **W5-CR-02** | confirms G5-CR-02 | Dropbox watcher runs `batch_skip_trace` with no fit gate + no death/identity guard, uploads `skip_trace=True` | ✅ confirmed |
| **W8-CR-01** | confirms CR-04 | JCD `_INSTNUM_RE` can't match real `db=P`; **every** JCD test monkeypatches the parser, so it's fixture-masked | ✅ confirmed + refined |

> **CR-04 correction (from W8):** the live `db` value is **alphabetic** (`db=P`/`db=D`), not empty. The regex fix in REMEDIATION-PLAN.md must be `db=([A-Za-z0-9]*)`, **not** `db=(\d*)` — `\d*` would still drop every `db=P` record.

---

## Critical Issues (new)

### WR2-CR-01 (W5-CR-01): Dropbox deletes the source photo on zero-record / failed processing — permanent data loss ✅ VERIFIED
**File:** `src/dropbox_watcher.py:366` (delete trigger), cursor pre-advance `:168`
**Issue:** Verified — `mark_processed(dbx, group_items, delete_after=delete_after)` at line 366 sits at the `for (county, notice_type)` loop-body indent, **outside** the `if notices:` (line 305) and inner `if notices:` (line 312) guards. With `delete_after=True` (default), the photo is deleted from Dropbox whenever: (a) `process_photos` returns `[]` (OCR/moire failure — the documented #1 failure mode), (b) the fit gate drops every record, or (c) any swallowed sub-failure. Compounding it, `poll_once` persists the Dropbox cursor at line 168 *before* processing, so a failed file is never re-listed. Net: un-reshootable courthouse terminal photos are silently, permanently lost.
**Fix:** Track `produced_records` and only `mark_processed(..., delete_after=True)` when a record was written & persisted; otherwise `delete_after=False` and log for manual re-OCR. Decouple cursor advance from "queued for processing." Full patch in REVIEW-w5.md.

### WR2-CR-02 (W1-CR-01): Filter failure falls through to act on ALL account records (enrich + skip trace) ✅ VERIFIED
**File:** `src/datasift_uploader.py:744-755` (enrich), `:898-907` (skip trace)
**Issue:** Both flows call `_filter_by_list()`, log a warning on failure, then **proceed anyway** to `_select_all_records()` → Enrich / Skip Trace. `_filter_by_list` swallows selector-drift / popup-interception / missing-list and returns `False`; the grid then shows the **full account**, and "Select all X records" escalates to everything. The enrich path literally comments `# Continue anyway — may enrich whatever is showing` (line 748). Consequence: skip-trace bills + re-tags the entire book; enrich (with W1-CR-02) can overwrite owners account-wide.
**Fix:** Fail closed — abort if the filter didn't apply; verify the on-screen selected count is non-zero and not the full-account total before acting. Apply to both call sites. See REVIEW-w1.md.

### WR2-CR-03 (W1-CR-02): "Enrich/Swap Owners OFF" protection never verified — can overwrite DM contacts
**File:** `src/datasift_uploader.py:797-852`
**Issue:** The protective toggles are set by a `page.evaluate` that matches `.react-toggle` siblings by label text. On label drift it matches zero toggles, returns `{}`, logs it, and clicks "Enrich" with whatever the modal defaults to. CLAUDE.md says these toggles being OFF is the *only* thing protecting the PR/DM contact mapping — if DataSift defaults either ON, enrich overwrites the decision-maker fields the probate pipeline computed. An empty/partial toggle result is treated as success.
**Fix:** Require positive confirmation that `Enrich Owners`/`Swap Owners` were located and set OFF; abort otherwise. Snippet in REVIEW-w1.md.

### WR2-CR-04 (W6-CR-01): Unescaped names crash reportlab `doc.build()` → no PDF deliverable
**File:** `src/report_generator.py` (representative: `:178-180`, `:235`, `:250-268`, `:350-354`, `:448`, `:545`, `:567-579`)
**Issue:** reportlab `Paragraph` parses mini-XML. Owner/decedent/heir/relationship/address strings — from OCR, LLM, obituary scraping, Tracerfy — are interpolated raw. A literal `&`/`<`/`>` in a real name (`SMITH & JONES ESTATE`, an OCR'd `AT&T`) raises `ValueError` inside `doc.build()` (line 511, unhandled), so **no PDF is produced** and a partial/zero-byte file is left. Attacker-influenceable (scraped obit/LLM names) → also a markup-injection vector.
**Fix:** Route every untrusted value through `escapeOnce`/`xml.escape` (two chokepoints — `_data_table` and `_add_signing_chain` — fix most of it), and wrap `doc.build()` to delete the partial file on failure (W6-WR-05). See REVIEW-w6.md.

### WR2-CR-05 (W3-CR-01): Wholesale buyer-profit math is inconsistent → wrong go/no-go
**File:** `src/deal_analyzer.py:252-265` (and call site `:730`)
**Issue:** `calculate_wholesale` (a) omits the end-buyer's holding costs that `calculate_flip` charges, so the two exit strategies aren't comparable, and (b) is passed the **flip MAO** as the contract price, double-counting the spread. The inflated `buyer_profit_estimate` gates the WHOLESALE recommendation (`_make_recommendation:412` requires `> $20k`), and W3-WR-05 compounds it (wholesale is ranked on a hardcoded score of `100`, always beating flip/hold). Net: the analyzer is biased to recommend wholesale on bad numbers.
**Fix:** Charge the buyer side on the same basis as the flip (incl. holding) and contract at the **wholesale** MAO; rank wholesale on a comparable metric, not `100`. See REVIEW-w3.md.

### Confirmations (same bug as earlier findings — fix once)
- **W5-CR-02 = G5-CR-02 / CR-07:** `dropbox_watcher.py:319-348` runs `batch_skip_trace` with no fit gate and no `guard_all`, then uploads `skip_trace=True`. The watcher path bypasses both Phase-4 and Phase-5 safety layers; nothing upstream compensates. (Verified.)
- **W8-CR-01 = CR-04:** `_INSTNUM_RE = ...db=(\d+)` at `jefferson_deeds_scraper.py:102` can't match real `db=P`; both JCD tests monkeypatch `_parse_results_table` and hand-build `db="P"` fixtures the regex couldn't produce. Fix to `db=([A-Za-z0-9]*)` and add a real-HTML test.

---

## Warnings (54) — grouped by area

### DataSift uploader / Playwright (W1)
- **W1-WR-01** `:684-696` — `_select_all_records` fallback blind-toggles every checkbox → deselects rows, returns `True` anyway. *Fix: click only the header checkbox; verify "N selected".*
- **W1-WR-02** `:751,:903,:1252` — enrich/skip-trace/export proceed with no selection-count verification (SiftMap path does verify — mirror it).
- **W1-WR-03** `:1465-1509` — export-download fetches a page-supplied URL with all session cookies, guarded only by substring `"reisift" in url` → cookie exfil to `evil-reisift.com`. *Fix: parse host, allow-list `*.reisift.io`.*
- **W1-WR-04** `:2463-2490` — SiftMap `min_sale_price` applied only via URL param, never verified (CLAUDE.md notes SPA ignores it) → tags $0 deed transfers as Sold.
- **W1-WR-05** `:1877` — `download_path` may be `None` passed into validation (currently masked by a `success` guard).
- **W1-WR-06** `:156-236,:507-511` — wizard steps swallow failures and `continue`; a 60s confirm **timeout is treated as success** → enrich/skip-trace chained against a list never created.
- **W1-WR-07** `:976-987` — skip-trace submit matched by broad text list `.first` → can click the modal title / menu item. *Fix: scope to `[role=dialog]`, verify "Sent!".*

### CRM data / lead mgmt (W2)
- **W2-WR-01** `lead_manager` reads `"Tax Delinquent Value"` but exports use the typo header `"Tax Deliquent Value"` → tax-delinquency signal silently dropped from qualification.
- **W2-WR-02** `niche_sequential.py:177` — `export_sms_list` `name.split()[0]` IndexErrors on whitespace-only owner.
- **W2-WR-03/04** Price pillar defines `PRICE_HOT_PCT`/`PRICE_WARM_PCT` it never uses (scores on equity %); routing contradicts the documented "2+ Cold → drip" rule.
- **W2-WR-05** CSV/formula injection in the 3 channel exporters (same class as G7-CR-01).
- **W2-WR-06** `login()` timeout path can falsely return success.

### Deal analysis / enrichment (W3)
- **W3-WR-01** `property_enricher.py:72-114,284-296` — equity model hard-codes 80% LTV and treats last *sold* price as loan basis → fabricates a phantom mortgage on free-and-clear probate homes (the core KY use case), under-stating equity → mis-scored fit. *Fix: skip when likely free-and-clear; prefer the deed lien chain; flag as model output.*
- **W3-WR-02/03** `:159-214,:268-314` — unvalidated negative `--purchase-price` → negative holding cost / sign-flipped cash-on-cash silently inflates returns. *Fix: clamp `max(0, …)`.*
- **W3-WR-04** `:356-372` — "Total Cost of Money" compares 30yr/20yr lifetime interest (conv/seller) against a 12-mo hard-money carry → conventional looks catastrophically worse for a flip. *Fix: same horizon for all.*
- **W3-WR-05** `:403-424` — WHOLESALE ranked on a hardcoded `100` → always beats flip/hold (compounds W3-CR-01).
- **W3-WR-06** `:167-177` — `_estimate_monthly_rent` unweighted mean of 3 heuristics, no bound, silent `1200` fallback → meaningless rent into cap-rate/CoC.
- **W3-WR-07** `property_lookup.py:264-298` — `_format_name_for_search` strips the comma then assumes last token = surname → "SMITH, JOHN A" → search "A SMITH JOHN" → wrong/empty assessor match → wrong-house mail. (Same name-parsing family as G1-WR-01.)
- **W3-WR-08** `entity_researcher.py:189-259` — untrusted web snippets concatenated into an LLM prompt with no isolation (prompt injection → attacker-controlled skip-trace target); model `confidence` accepted as free string. *Fix: delimit untrusted data block; validate `confidence` against the allowed set.*
- **W3-WR-09** `property_lookup.py`/`property_enricher.py` — external URLs built from scraped `parcel_id`/names with no validation and `allow_redirects` on → latent SSRF. *Fix: validate parcel pattern; `allow_redirects=False` + host re-check.*

### OCR / LLM ingestion (W4)
- **W4-WR (8 total)** — headline: `pdf_importer.py:196` `validate_row` calls `.strip()` on un-type-checked LLM fields → a non-string `parcel_id`/`address` `AttributeError`-crashes the **entire** PDF import; `llm_client.py:80,107` blindly indexes `response.content[0].text` → breaks on empty/truncated/non-text blocks; LLM output from OCR'd text is trusted as ground truth with no provenance flag (`photo_importer.py:215`, `llm_parser.py:229`) → a hallucinated address/owner flows into paid skip-trace + DataSift; unclosed `PdfDocument` handle on render exception; no `Image.MAX_IMAGE_PIXELS` cap on Dropbox-sourced images (decompression-bomb DoS). Full list in REVIEW-w4.md.

### Dropbox / filter / entry (W5)
- **W5-WR-01** `:298-316` — `process_photos`/`run_enrichment_pipeline`/`write_csv` unwrapped in the daemon loop → one bad photo kills the watcher process silently. *Fix: per-group try/except; don't delete source on failure.*
- **W5-WR-02** `foreclosure_filter.py:54-64` — bare-word EXCLUDE substrings `"divorce"`/`"dissolution"` match boilerplate in valid entity-borrower trustee sales → silently dropped (EXCLUDE runs before INCLUDE). *Fix: anchor to the title line / use phrase-specific excludes.* **(Critical domain filter — CLAUDE.md flags foreclosure filtering as the highest-stakes correctness rule.)**
- **W5-WR-03** `dropbox_uploader.py:46-53` — share links created `RequestedVisibility.public` for PII-bearing CSVs/PDFs (names, DOD, heirs, skip-traced phones) → anyone with the URL gets the data. *Fix: `team_only`/password+expiry.*
- **W5-WR-04** `:217,:291-294` — same-basename photos (`IMG_0001.jpg`) from different folders collide in the shared temp dir → one silently overwritten, both deleted. *Fix: hash-prefix the local name.*
- **W5-WR-05** `:93-114` — `check_storage_usage` early-returns for team accounts → the deployment account gets no storage logging / no full-up warning.

### Reporting / export (W6)
- **W6-WR-01** `report_generator.py:486,:573` — phone-tier block reads `info["score"]` after only checking `info["tier"]` → `KeyError` crashes the PDF on a partial Trestle result.
- **W6-WR-02** `excel_exporter.py:390,397,487,497,576` — untrusted strings written as XLSX cells → Excel formula injection; the `Sift Upload` sheet is re-exported to CSV (widens blast radius). Same class as G7-CR-01.
- **W6-WR-03** `excel_exporter.py:591-592` — `export_review_workbook` calls `sys.exit(1)` from library code → tears down any importer.
- **W6-WR-04** `:413-414,:514-515` — `except Exception: pass` silently drops obituary-hyperlink failures (and stores untrusted `javascript:`/`file:` URLs).
- **W6-WR-05** `:511` — no try/finally around `doc.build()` → partial PDF left, propagates uncaught (pairs with W6-CR-01).
- **W6-WR-06** `:532-535,:558` — `_add_signing_chain` doesn't type-guard `heir_map_json` items → `AttributeError` on valid-but-non-dict JSON (`case_summary.group_heirs` guards correctly — mirror it).

### Config / infra (W7) — no secrets leaked (good)
- **W7-WR-01** No `.dockerignore` → `apify push` uploads the whole build context; `COPY .actor/ ./.actor/` would bake a dev-placed `.actor/input.json` (real creds) into a persistent layer. *Fix: add `.dockerignore`.*
- **W7-WR-02** Every `requirements.txt` dep is unbounded `>=` → image/PDF/network packages (`Pillow`, `pillow-heif`, `pdfminer.six`, `dropbox`) can jump to a breaking/compromised major on any cloud rebuild. *Fix: pin upper bounds / lockfile.*
- **W7-WR-03** Unvalidated `since_date` free-text input silently mis-scopes the scrape window.
- **W7-WR-04** Mutable base tag `:3.12` + `buildTag: "latest"` → non-reproducible builds.

### Test suite (W8) — see the coverage table at top
- **W8-WR-01** equity `book_page`-as-dollars path structurally unreachable (`book_page=""` + test-only `amount` in every fixture).
- **W8-WR-02/03** guard identity test stubs `disambiguate → None`; production never passes `expected_age` (real wiring gap the stub hides).
- **W8-WR-04** title-path DM tested only in isolation with hand-set `decision_maker_name`; no classifier→DM→apply chain test.
- **W8-WR-05/06/07** CSV injection, Drive apostrophe escaping, Dropbox guard wiring — untested.
- **W8-WR-08** JCD dedup tests assert on `db="P"` records the real parser would have dropped.
- **W8-WR-09** live/paid integration scripts (`test_captcha_live.py`, `test_e2e_obituary.py`) under `tests/` with no `@pytest.mark.live`/segregation → risk of accidental paid/headed run in CI.

---

## Info (45) — compact
**W1:** dead `_raw_text` var; duplicated records-URL constant (3 copies); 5× copy-pasted browser boilerplate (`create_browser` exists); fixed `wait_for_timeout` sleeps mask failures; screenshots with PII written to CWD.
**W2:** 7 items — preset/sequence constants verified vs CLAUDE.md (positive); minor naming/dead-constant notes.
**W3:** `ppsf_range` positional-index dependency; wholetail tier cap unlabeled; `window_count≥8`/roof-on-condo over-estimates rehab; broad excepts hide programming errors; `_extract_last_sold` int-parse fragility; undocumented magic numbers; brittle substring styling.
**W4:** 7 items — provenance/shape-validation gaps, resource cleanup, image-size cap (see REVIEW-w4.md).
**W5:** dead `poll_once(delete_after=)` param; `foreclosure_filter` dereferences `raw_text.lower()` before the None-check; latent path-traversal from Dropbox `entry.name`; `_parse_folder_path` `.title()` mangles `McCracken`/`DeKalb`.
**W6:** phone-list aliasing on shared ref; `obituary_experiment.py` is a CLI harness shipped in `src/` (move to `scripts/`); metrics denominator mismatch; unguarded fixture keys; **`report_generator.py` deviates from the LOCKED Brand PDF Standard** (own palette, never imports `brand_pdf`).
**W7:** 5 items — pin base image digest, mark editor-hidden secrets, schema validation hardening.
**W8:** no hardcoded creds (positive); strong models to copy (`test_wholesale_fit`, `test_deceased_detection`, `test_title_classifier`); brittle source-grep test; thin/no coverage for `captcha_solver`, `photo_importer` OCR chain, `apply_parties_to_notice`, `_parse_results_table`, the LP address regexes.

---

## Coverage statement
- **All 63 `src/*.py` modules are now reviewed** across the two passes (40 in CODE-REVIEW.md + 23 here). Config/infra and the test suite are reviewed here.
- **Excluded:** `scripts/` (17 tracked recon + untracked `find_*`/`build_*` one-offs) — throwaway tooling, not a deliverable, per CLAUDE.md.
- **Caveats unchanged from CODE-REVIEW.md:** static-only (nothing run), one agent per large file, warnings/info are agent-reported (the 2 new criticals marked ✅ were verified by me).

## Combined repo-wide picture (both passes)
- **~12 unique Criticals** (7 + 7 − 2 confirmations). New-this-pass: data loss, account-wide fail-open, DM-contact overwrite, PDF render crash, wrong wholesale recommendation.
- Cross-cutting themes from CODE-REVIEW.md all reinforced here, plus two new ones: **(a) fail-open automation that acts on the wrong/whole dataset** (W1-CR-01/02, W5-CR-01); **(b) untrusted strings into render/markup sinks** (W6-CR-01 PDF, W6-WR-02/W2-WR-05 XLSX/CSV — the same family as G7-CR-01).
- **The remediation plan needs 5 new criticals added** (W1-CR-01, W1-CR-02, W3-CR-01, W5-CR-01, W6-CR-01) and the CR-04 regex corrected to `db=([A-Za-z0-9]*)`.

_Per-subsystem detail: `.planning/phases/05-auto-skip-trace-death-identity-guard/partials/whole-repo/REVIEW-w1..w8.md`_
_Reviewer: Claude (gsd-code-review orchestrator) · 2026-05-29_
