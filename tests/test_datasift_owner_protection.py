"""Network-free tests for the DataSift enrich owner-protection guard (W1-CR-02).

Regression context (CODE-REVIEW-WHOLE-REPO.md W1-CR-02): enrich_records set the
"Enrich Owners" / "Swap Owners" toggles via in-page JS but never verified the JS
actually located and turned them OFF. On label drift the JS returns {} and the
old code clicked "Enrich" with the modal defaults — risking an account-wide
overwrite of the PR/DM contact mapping. ``_owner_protection_confirmed`` is the
pure, fail-closed gate that now blocks the Enrich click unless both toggles are
confirmed OFF.

Run:  python tests/test_datasift_owner_protection.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from datasift_uploader import _owner_protection_confirmed  # noqa: E402


def test_both_off_confirmed():
    ok, _ = _owner_protection_confirmed(
        {"Enrich Owners": "already OFF", "Swap Owners": "turned OFF"}
    )
    assert ok is True
    print("PASS: test_both_off_confirmed")


def test_empty_result_aborts():
    """Label drift -> JS returns {} -> must FAIL CLOSED (the core W1-CR-02 case)."""
    ok, reason = _owner_protection_confirmed({})
    assert ok is False
    assert "Enrich Owners" in reason and "Swap Owners" in reason
    print("PASS: test_empty_result_aborts")


def test_owner_toggle_on_aborts():
    ok, reason = _owner_protection_confirmed(
        {"Enrich Owners": "turned ON", "Swap Owners": "already OFF"}
    )
    assert ok is False
    assert "Enrich Owners" in reason
    print("PASS: test_owner_toggle_on_aborts")


def test_one_toggle_missing_aborts():
    # Only Enrich Owners located; Swap Owners never found -> abort.
    ok, reason = _owner_protection_confirmed({"Enrich Owners": "already OFF"})
    assert ok is False
    assert "Swap Owners" in reason
    print("PASS: test_one_toggle_missing_aborts")


def test_none_input_aborts():
    ok, _ = _owner_protection_confirmed(None)
    assert ok is False
    print("PASS: test_none_input_aborts")


if __name__ == "__main__":
    test_both_off_confirmed()
    test_empty_result_aborts()
    test_owner_toggle_on_aborts()
    test_one_toggle_missing_aborts()
    test_none_input_aborts()
    print("\nAll DataSift owner-protection tests passed.")
