"""Phase 2f — title-path-aware decision-maker assignment (CR-01, end-to-end).

The CourtNet executor is the wrong DM ~26% of the time because TITLE bypasses or
sits outside probate. This pins the locked rule across the REAL two-step flow:

  kcoj_case_detail.apply_parties_to_notice       -> sets a PROVISIONAL executor-DM
  kentucky_title_classifier.classify_title_path  -> CORRECTS it:
    * successor_trustee   -> DM := successor trustee (executor -> owner_name only)
    * surviving_owner     -> DM := surviving co-owner
    * out_of_estate / no_property -> DM cleared (no one to sell; Phase 4 drops it)
    * standard_probate    -> DM stays the executor
    * trustee_unconfirmed -> trust detected but no recoverable trustee -> executor

Previously the classifier never set a DM and apply_parties read an always-empty
title_path, so EVERY trust/survivorship lead silently shipped the executor as DM
(CODE-REVIEW.md CR-01, W8-WR-04). These tests chain BOTH steps — the integration
the prior isolated tests missed.

Run:  python tests/test_title_path_dm.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from notice_parser import NoticeData
from kcoj_case_detail import apply_parties_to_notice
from kentucky_title_classifier import classify_title_path

# Real executor party-type code "EE" so _classify_party() returns "executor".
EXECUTOR_PARTIES = [{"partyname": "DOE, JANE", "partytype": "EE"}]
EXECUTOR_TITLE = "Doe, Jane"   # title-cased form apply_parties writes


def _probate(**kw) -> NoticeData:
    return NoticeData(notice_type="probate", county="Jefferson", state="KY", **kw)


def _enrich(n: NoticeData) -> None:
    """Run the real two-step flow: CourtNet parties, then the title classifier."""
    apply_parties_to_notice(n, EXECUTOR_PARTIES)
    # apply_parties sets the PROVISIONAL executor-DM + captures owner_name.
    assert n.owner_name == EXECUTOR_TITLE, n.owner_name
    assert n.decision_maker_name == EXECUTOR_TITLE, n.decision_maker_name
    classify_title_path(n)


def test_successor_trustee_sets_trustee_dm():
    n = _probate(case_number="26-P-T1", address="1 Trust Way",
                 decedent_name="SMITH, JOHN",
                 pva_owner_string="SMITH FAMILY REVOCABLE TRUST",
                 current_property_holder="JANE SMITH",
                 current_holder_relationship="trust")
    _enrich(n)
    assert n.title_path == "successor_trustee", n.title_path
    assert n.decision_maker_name == "JANE SMITH", n.decision_maker_name
    assert n.decision_maker_source == "title_successor_trustee", n.decision_maker_source
    assert n.owner_name == EXECUTOR_TITLE, "executor must stay in owner_name"
    print("PASS: test_successor_trustee_sets_trustee_dm")


def test_surviving_owner_sets_survivor_dm():
    n = _probate(case_number="26-P-T2", address="1 Joint St",
                 decedent_name="DOE, JOHN",
                 current_property_holder="JOHN DOE & JANE DOE")
    _enrich(n)
    assert n.title_path == "surviving_owner", n.title_path
    assert n.decision_maker_name == "JANE DOE", n.decision_maker_name
    assert n.decision_maker_source == "title_surviving_owner", n.decision_maker_source
    assert n.owner_name == EXECUTOR_TITLE
    print("PASS: test_surviving_owner_sets_survivor_dm")


def test_out_of_estate_clears_dm():
    n = _probate(case_number="26-P-T3", address="100 Sold St",
                 current_holder_relationship="heir_recent")
    _enrich(n)
    assert n.title_path == "out_of_estate", n.title_path
    assert n.decision_maker_name == "", f"DM not cleared: {n.decision_maker_name!r}"
    print("PASS: test_out_of_estate_clears_dm")


def test_no_property_clears_dm():
    n = _probate(case_number="26-P-T4")  # no address/holder/relationship
    _enrich(n)
    assert n.title_path == "no_property", n.title_path
    assert n.decision_maker_name == "", f"DM not cleared: {n.decision_maker_name!r}"
    print("PASS: test_no_property_clears_dm")


def test_standard_probate_keeps_executor_dm():
    n = _probate(case_number="26-P-T5", address="1 Main St", decedent_name="ROE, RICHARD")
    _enrich(n)
    assert n.title_path == "standard_probate", n.title_path
    assert n.decision_maker_name == EXECUTOR_TITLE, n.decision_maker_name
    assert n.decision_maker_relationship == "executor", n.decision_maker_relationship
    print("PASS: test_standard_probate_keeps_executor_dm")


def test_trustee_unconfirmed_keeps_executor_dm():
    # Trust detected, but no recoverable trustee -> fall back to executor (locked decision 3).
    n = _probate(case_number="26-P-T6", address="1 Trust Way",
                 decedent_name="SMITH, JOHN", pva_owner_string="SMITH TRUST")
    _enrich(n)
    assert n.title_path == "successor_trustee", n.title_path
    assert n.trustee_unconfirmed == "yes", n.trustee_unconfirmed
    assert n.decision_maker_name == EXECUTOR_TITLE, (
        f"executor must be the fallback DM: {n.decision_maker_name!r}")
    print("PASS: test_trustee_unconfirmed_keeps_executor_dm")


if __name__ == "__main__":
    test_successor_trustee_sets_trustee_dm()
    test_surviving_owner_sets_survivor_dm()
    test_out_of_estate_clears_dm()
    test_no_property_clears_dm()
    test_standard_probate_keeps_executor_dm()
    test_trustee_unconfirmed_keeps_executor_dm()
    print("\nAll title-path DM-assignment tests passed.")
