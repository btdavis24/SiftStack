"""Phase 2f — title-path-aware decision-maker assignment (2c integration).

Proves that ``kcoj_case_detail.apply_parties_to_notice`` honors
``notice.title_path`` (set by Step 3f / kentucky_title_classifier) when it
decides whether the CourtNet executor becomes the decision-maker:

  * successor_trustee / surviving_owner → the title-derived DM is KEPT; the
    executor is captured into owner_name only (locked decision 1).
  * out_of_estate / no_property        → NO DM is named (flagged for drop).
  * standard_probate                   → executor becomes the DM (current
                                          behavior; relationship == "executor").
  * trustee_unconfirmed                → falls back to executor as DM
                                          (locked decision 3, Smith-Charles).

Standalone script per .planning/codebase/TESTING.md (no pytest):
``python tests/test_title_path_dm.py`` exits 0 when all assertions pass.

Fixtures use the REAL executor party-type code ``"EE"`` (from
``_EXECUTOR_PARTY_TYPES`` in src/kcoj_case_detail.py) so the executor branch
genuinely fires — a placeholder/wrong code would make ``_classify_party``
return "other", silently skip the executor branch, and make the
executor-as-DM test pass vacuously.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from notice_parser import NoticeData
from kcoj_case_detail import apply_parties_to_notice

# A real executor party-type code so _classify_party() returns "executor".
EXECUTOR_PARTIES = [{"partyname": "DOE, JANE", "partytype": "EE"}]
# Title-cased form apply_parties_to_notice writes for "DOE, JANE".
EXECUTOR_TITLE = "Doe, Jane"


def test_successor_trustee_keeps_title_dm():
    """successor_trustee: the title-derived DM is preserved, not overwritten."""
    n = NoticeData(
        notice_type="probate", county="Jefferson", state="KY",
        case_number="26-P-TEST1",
        title_path="successor_trustee",
        decision_maker_name="TRUSTEE NAME",  # as the classifier would leave it
    )
    apply_parties_to_notice(n, EXECUTOR_PARTIES)
    assert n.decision_maker_name == "TRUSTEE NAME", (
        f"DM overwritten by executor: {n.decision_maker_name!r}"
    )
    assert n.owner_name == EXECUTOR_TITLE, (
        f"executor not captured to owner_name: {n.owner_name!r}"
    )
    print("PASS: test_successor_trustee_keeps_title_dm")


def test_surviving_owner_keeps_title_dm():
    """surviving_owner: the surviving co-owner stays DM; executor -> owner_name."""
    n = NoticeData(
        notice_type="probate", county="Jefferson", state="KY",
        case_number="26-P-TEST2",
        title_path="surviving_owner",
        decision_maker_name="SURVIVING SPOUSE",
    )
    apply_parties_to_notice(n, EXECUTOR_PARTIES)
    assert n.decision_maker_name == "SURVIVING SPOUSE", (
        f"DM overwritten by executor: {n.decision_maker_name!r}"
    )
    assert n.owner_name == EXECUTOR_TITLE, (
        f"executor not captured to owner_name: {n.owner_name!r}"
    )
    print("PASS: test_surviving_owner_keeps_title_dm")


def test_out_of_estate_skips_dm():
    """out_of_estate: no executor-as-DM (flagged for drop)."""
    n = NoticeData(
        notice_type="probate", county="Jefferson", state="KY",
        case_number="26-P-TEST3",
        title_path="out_of_estate",
        decision_maker_name="",
    )
    apply_parties_to_notice(n, EXECUTOR_PARTIES)
    assert n.decision_maker_name == "", (
        f"DM should stay empty for out_of_estate: {n.decision_maker_name!r}"
    )
    print("PASS: test_out_of_estate_skips_dm")


def test_no_property_skips_dm():
    """no_property: no executor-as-DM (flagged for drop)."""
    n = NoticeData(
        notice_type="probate", county="Jefferson", state="KY",
        case_number="26-P-TEST4",
        title_path="no_property",
        decision_maker_name="",
    )
    apply_parties_to_notice(n, EXECUTOR_PARTIES)
    assert n.decision_maker_name == "", (
        f"DM should stay empty for no_property: {n.decision_maker_name!r}"
    )
    print("PASS: test_no_property_skips_dm")


def test_standard_probate_uses_executor():
    """standard_probate: executor becomes the DM (current behavior preserved).

    Uses the REAL "EE" executor party code so the executor branch actually
    fires — asserting both decision_maker_name AND relationship proves this is
    not a vacuous pass.
    """
    n = NoticeData(
        notice_type="probate", county="Jefferson", state="KY",
        case_number="26-P-TEST5",
        title_path="standard_probate",
        decision_maker_name="",
    )
    apply_parties_to_notice(n, EXECUTOR_PARTIES)
    assert n.decision_maker_name == EXECUTOR_TITLE, (
        f"executor not set as DM: {n.decision_maker_name!r}"
    )
    assert n.decision_maker_relationship == "executor", (
        f"DM relationship not 'executor': {n.decision_maker_relationship!r}"
    )
    assert n.owner_name == EXECUTOR_TITLE, (
        f"executor not captured to owner_name: {n.owner_name!r}"
    )
    print("PASS: test_standard_probate_uses_executor")


def test_trustee_unconfirmed_falls_back():
    """trustee_unconfirmed: trust detected but no recoverable trustee → the
    executor becomes the DM (locked decision 3, Smith-Charles)."""
    n = NoticeData(
        notice_type="probate", county="Jefferson", state="KY",
        case_number="26-P-TEST6",
        title_path="successor_trustee",
        trustee_unconfirmed="yes",
        decision_maker_name="",
    )
    apply_parties_to_notice(n, EXECUTOR_PARTIES)
    assert n.decision_maker_name == EXECUTOR_TITLE, (
        f"executor should be DM fallback when trustee_unconfirmed: "
        f"{n.decision_maker_name!r}"
    )
    assert n.decision_maker_relationship == "executor", (
        f"DM relationship not 'executor': {n.decision_maker_relationship!r}"
    )
    print("PASS: test_trustee_unconfirmed_falls_back")


if __name__ == "__main__":
    test_successor_trustee_keeps_title_dm()
    test_surviving_owner_keeps_title_dm()
    test_out_of_estate_skips_dm()
    test_no_property_skips_dm()
    test_standard_probate_uses_executor()
    test_trustee_unconfirmed_falls_back()
    print("\nAll title-path DM-assignment tests passed.")
