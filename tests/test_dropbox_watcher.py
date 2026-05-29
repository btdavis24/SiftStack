"""Network-free tests for the Dropbox watcher's skip-trace SAFETY wiring.

Regression context (CODE-REVIEW-WHOLE-REPO.md W5-CR-01 / W5-CR-02): the watcher
used to (a) run ``batch_skip_trace`` on EVERY record with no fit gate and no
death/identity guard before uploading ``skip_trace=True`` to DataSift, and
(b) delete the source photo even when OCR/enrichment produced zero records
(silent, permanent loss of un-reshootable courthouse captures). These tests pin
the fix:

  - ``_run_skip_trace_guarded`` only traces wholesale-fit records and ALWAYS
    runs ``guard_all`` between the trace and any upload.
  - ``_process_group`` returns False (=> the caller must NOT delete the source)
    when photo OCR yields nothing.

Run:  python tests/test_dropbox_watcher.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import dropbox_watcher  # noqa: E402
import tracerfy_skip_tracer  # noqa: E402
import skip_trace_guard  # noqa: E402
from notice_parser import NoticeData  # noqa: E402


def _notice(**kw) -> NoticeData:
    n = NoticeData()
    for k, v in kw.items():
        setattr(n, k, v)
    return n


def test_skip_trace_guarded_fit_gates_and_runs_guard():
    """Only fit records reach Tracerfy, and guard_all runs on the traced set
    (between trace and any upload) — W5-CR-02."""
    traced, guarded, fellback = {}, {}, {}
    saved = (
        dropbox_watcher.config.TRACERFY_API_KEY,
        getattr(dropbox_watcher.config, "SKIP_TRACE_MIN_FIT", 40),
        tracerfy_skip_tracer.batch_skip_trace,
        skip_trace_guard.guard_all,
        skip_trace_guard.apply_contact_fallbacks,
        skip_trace_guard.handle_credits_exhausted,
    )
    try:
        dropbox_watcher.config.TRACERFY_API_KEY = "test-key"
        dropbox_watcher.config.SKIP_TRACE_MIN_FIT = 50

        def _fake_bst(ns):
            traced["notices"] = list(ns)
            return {"matched": 0, "submitted": len(ns), "phones_found": 0}

        def _fake_guard(ns):
            guarded["notices"] = list(ns)
            return {"records": len(ns), "suppressed_phones": 0,
                    "suppressed_emails": 0, "unconfirmed": 0}

        def _fake_fallbacks(ns):
            fellback["notices"] = list(ns)
            return {"records": len(ns)}

        tracerfy_skip_tracer.batch_skip_trace = _fake_bst
        skip_trace_guard.guard_all = _fake_guard
        skip_trace_guard.apply_contact_fallbacks = _fake_fallbacks
        skip_trace_guard.handle_credits_exhausted = lambda ns, st: {"queued": 0}

        fit = _notice(notice_type="probate", owner_deceased="yes",
                      decision_maker_name="JANE DOE", wholesale_fit_score="80")
        nonfit = _notice(notice_type="probate", owner_deceased="yes",
                         decision_maker_name="JOHN ROE", wholesale_fit_score="10")

        dropbox_watcher._run_skip_trace_guarded([fit, nonfit])

        assert traced.get("notices") == [fit], "only the fit notice should be traced"
        assert guarded.get("notices") == [fit], "guard_all must run on the traced set"
        assert fellback.get("notices") == [fit], "fallbacks run after the guard"
        print("PASS: test_skip_trace_guarded_fit_gates_and_runs_guard")
    finally:
        (dropbox_watcher.config.TRACERFY_API_KEY,
         dropbox_watcher.config.SKIP_TRACE_MIN_FIT,
         tracerfy_skip_tracer.batch_skip_trace,
         skip_trace_guard.guard_all,
         skip_trace_guard.apply_contact_fallbacks,
         skip_trace_guard.handle_credits_exhausted) = saved


def test_skip_trace_guarded_noop_without_key():
    """No Tracerfy key -> never calls batch_skip_trace (no accidental paid trace)."""
    saved_key = dropbox_watcher.config.TRACERFY_API_KEY
    saved_bst = tracerfy_skip_tracer.batch_skip_trace
    called = {"v": False}
    try:
        dropbox_watcher.config.TRACERFY_API_KEY = ""

        def _boom(ns):
            called["v"] = True
            return {}

        tracerfy_skip_tracer.batch_skip_trace = _boom
        dropbox_watcher._run_skip_trace_guarded(
            [_notice(notice_type="probate", owner_deceased="yes",
                     decision_maker_name="X", wholesale_fit_score="90")]
        )
        assert called["v"] is False, "must not trace when TRACERFY_API_KEY is unset"
        print("PASS: test_skip_trace_guarded_noop_without_key")
    finally:
        dropbox_watcher.config.TRACERFY_API_KEY = saved_key
        tracerfy_skip_tracer.batch_skip_trace = saved_bst


def test_process_group_returns_false_on_empty_ocr():
    """No records from OCR -> _process_group returns False so the caller keeps
    the source photo instead of deleting it (W5-CR-01 data-loss guard)."""
    import photo_importer
    saved_pp = photo_importer.process_photos
    try:
        photo_importer.process_photos = lambda **kw: []   # OCR produced nothing
        result = dropbox_watcher._process_group("Jefferson", "probate", _DummyPath())
        assert result is False, "empty OCR must return False (do not delete source)"
        print("PASS: test_process_group_returns_false_on_empty_ocr")
    finally:
        photo_importer.process_photos = saved_pp


class _DummyPath:
    """Minimal stand-in for group_dir — never touched when OCR returns []."""
    name = "dummy"


if __name__ == "__main__":
    test_skip_trace_guarded_fit_gates_and_runs_guard()
    test_skip_trace_guarded_noop_without_key()
    test_process_group_returns_false_on_empty_ocr()
    print("\nAll dropbox_watcher guard/data-loss tests passed.")
