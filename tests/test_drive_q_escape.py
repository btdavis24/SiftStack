"""Network-free test for the Google Drive ``q=`` escape (CR-06).

Regression context (CODE-REVIEW.md CR-06 / G9-CR-01, W6-WR-02): the disposition
flyer interpolated the CLI-supplied address and derived filename into Drive
queries with a broken single-quote-only escape. An address with an apostrophe
(e.g. O'Brien Ave) broke the query -> prior flyers never trashed (duplicates) or
a crafted value broadened the match to the wrong property's photos. _drive_q_escape
backslash-escapes ``\\`` first, then ``'``.

Run:  python tests/test_drive_q_escape.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from disposition_flyer import _drive_q_escape  # noqa: E402


def test_escapes_apostrophe():
    assert _drive_q_escape("O'Brien") == "O\\'Brien"
    print("PASS: test_escapes_apostrophe")


def test_escapes_backslash_before_quote():
    # Backslash must be escaped FIRST, otherwise the quote-escape's backslash
    # would itself be doubled and corrupt the query.
    assert _drive_q_escape("a\\b'c") == "a\\\\b\\'c"
    print("PASS: test_escapes_backslash_before_quote")


def test_plain_unchanged():
    assert _drive_q_escape("1521 Sale Ave") == "1521 Sale Ave"
    assert _drive_q_escape("") == ""
    assert _drive_q_escape(None) == ""
    print("PASS: test_plain_unchanged")


if __name__ == "__main__":
    test_escapes_apostrophe()
    test_escapes_backslash_before_quote()
    test_plain_unchanged()
    print("\nAll Drive q-escape tests passed.")
