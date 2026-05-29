"""Network-free tests for CSV / spreadsheet formula-injection defenses (CR-05).

Regression context (CODE-REVIEW.md CR-05 / G7-CR-01): every CSV writer emitted
untrusted strings (OCR'd names, CourtNet party strings, scraped buyer names,
Tracerfy phones/emails, Notes URLs) verbatim, so a value beginning with
=, +, -, @ executed as a formula when the operator opened the CSV. All writers
now use csv_safety.SafeDictWriter, which routes every cell through csv_safe.

Run:  python tests/test_csv_safety.py
"""
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from csv_safety import csv_safe, SafeDictWriter  # noqa: E402


def test_csv_safe_neutralizes_formula_triggers():
    assert csv_safe("=cmd|'/c calc'!A1") == "'=cmd|'/c calc'!A1"
    assert csv_safe("+15025551212").startswith("'+")
    assert csv_safe("-2+3").startswith("'-")
    assert csv_safe("@SUM(A1)").startswith("'@")
    assert csv_safe("\t=evil").startswith("'")  # leading whitespace, then a trigger
    print("PASS: test_csv_safe_neutralizes_formula_triggers")


def test_csv_safe_passes_normal_values():
    assert csv_safe("123 Main St") == "123 Main St"
    assert csv_safe("Smith, John") == "Smith, John"
    assert csv_safe("O'Brien") == "O'Brien"
    assert csv_safe("") == ""
    assert csv_safe(None) is None
    assert csv_safe(12345) == 12345
    assert csv_safe(3.14) == 3.14
    print("PASS: test_csv_safe_passes_normal_values")


def test_safe_dict_writer_sanitizes_rows():
    buf = io.StringIO()
    w = SafeDictWriter(buf, fieldnames=["name", "note"])
    w.writeheader()
    w.writerow({"name": '=HYPERLINK("http://evil")', "note": "ok"})
    w.writerows([{"name": "+danger", "note": "@x"}])
    out = buf.getvalue()
    assert "'=HYPERLINK" in out, out
    assert "'+danger" in out, out
    assert "'@x" in out, out
    assert ",ok" in out, "normal cell must be untouched"
    print("PASS: test_safe_dict_writer_sanitizes_rows")


if __name__ == "__main__":
    test_csv_safe_neutralizes_formula_triggers()
    test_csv_safe_passes_normal_values()
    test_safe_dict_writer_sanitizes_rows()
    print("\nAll csv_safety tests passed.")
