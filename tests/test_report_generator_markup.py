"""Network-free tests that the deep-prospect PDF survives untrusted markup
characters in scraped/LLM data (W6-CR-01 + W6-WR-06).

Regression context (CODE-REVIEW-WHOLE-REPO.md W6-CR-01): owner/decedent/heir
names and addresses (from OCR, CourtNet, obituary scraping, Tracerfy) were
interpolated raw into reportlab Paragraph markup. A literal &, <, or > in a real
name ("SMITH & JONES ESTATE") raised ValueError inside doc.build() and produced
NO PDF. Values are now XML-escaped at the source, and a malformed heir_map_json
no longer crashes the signing-chain renderer.

Run:  python tests/test_report_generator_markup.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from report_generator import _esc, generate_record_pdf  # noqa: E402
from notice_parser import NoticeData  # noqa: E402


def test_esc_escapes_markup_chars():
    assert _esc("SMITH & JONES ESTATE") == "SMITH &amp; JONES ESTATE"
    assert _esc("<script>") == "&lt;script&gt;"
    assert _esc(None) == ""
    assert _esc("a &amp; b") == "a &amp; b"  # escapeOnce must not double-escape
    print("PASS: test_esc_escapes_markup_chars")


def test_pdf_builds_with_ampersand_names():
    """A real '&' / '<' in owner/decedent/DM/heir fields must NOT crash doc.build()."""
    n = NoticeData()
    n.address = "123 Smith & Co <Lane>"
    n.city, n.state, n.zip = "Louisville", "KY", "40204"
    n.county, n.notice_type = "Jefferson", "probate"
    n.owner_name = "SMITH & JONES ESTATE"
    n.owner_deceased = "yes"
    n.decedent_name = "John <Q> Smith & Sons"
    n.decision_maker_name = "Jane & Bob O'Brien"
    n.decision_maker_street = "9 A&B Ave"
    n.decision_maker_city, n.decision_maker_state, n.decision_maker_zip = "Louisville", "KY", "40204"
    n.dm_confidence = "high"
    n.dm_confidence_reason = "deed shows Smith & Co <trust>"
    n.signing_chain_count = "2"
    n.heir_map_json = json.dumps([
        {"name": "Heir & One", "relationship": "son", "status": "living",
         "signing_authority": True, "street": "1 A&B St", "city": "X",
         "state": "KY", "zip": "40204"},
        {"name": "Heir <Two>", "relationship": "daughter", "status": "deceased"},
    ])
    with tempfile.TemporaryDirectory() as d:
        out = generate_record_pdf(n, output_dir=Path(d))
        assert out.exists() and out.stat().st_size > 0, "PDF must be produced (build did not crash)"
    print("PASS: test_pdf_builds_with_ampersand_names")


def test_pdf_survives_malformed_heir_map():
    """heir_map_json that is a dict or list-of-strings must not crash the build (W6-WR-06)."""
    for bad in (json.dumps({"not": "a list"}), json.dumps(["just", "strings"])):
        n = NoticeData()
        n.address, n.city, n.state, n.zip = "1 Main St", "Louisville", "KY", "40204"
        n.county, n.notice_type = "Jefferson", "probate"
        n.owner_name = n.decedent_name = "X"
        n.owner_deceased = "yes"
        n.signing_chain_count = "1"
        n.heir_map_json = bad
        with tempfile.TemporaryDirectory() as d:
            out = generate_record_pdf(n, output_dir=Path(d))
            assert out.exists() and out.stat().st_size > 0
    print("PASS: test_pdf_survives_malformed_heir_map")


if __name__ == "__main__":
    test_esc_escapes_markup_chars()
    test_pdf_builds_with_ampersand_names()
    test_pdf_survives_malformed_heir_map()
    print("\nAll report_generator markup-safety tests passed.")
