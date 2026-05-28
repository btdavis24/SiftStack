"""Network-free tests for surname-first ("Last, First") name parsing in the
two split helpers that feed Tracerfy and the DataSift CSV.

Regression context — the 2026-05-28 Apify run:

  PR #7 fixed the CourtNet asyncio bridge, which finally populated executor
  names on probate records. CourtNet returns parties surname-first
  ("Pack, Sherri Renee"). Both name splitters assumed "First [Middle] Last"
  order and split on whitespace, so:

    tracerfy._split_name("Pack, Sherri Renee")        -> ("Pack,", "Renee")
    datasift._clean_and_split_name("Pack, Sherri ...") -> ("Pack,", "Sherri Renee")

  Tracerfy then searched for a person named "Renee Pack," / "Sherri Renee
  Pack," and returned 0/4 matched, 0 phones. Every probate DM shipped with
  blank phones and a comma stuck on the first name.

The fix teaches both helpers the comma form: text before the first comma is
the surname, the first token after it is the given name. Natural-order names
(from obituary / heir paths) keep working via the existing branch, and the
tracerfy helper now also skips a trailing generational suffix.

Run:  python tests/test_comma_name_split.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from tracerfy_skip_tracer import _split_name as tf_split  # noqa: E402
from datasift_formatter import (  # noqa: E402
    _clean_and_split_name as ds_split,
)


# ── Tracerfy _split_name: the four 2026-05-28 records ─────────────────────
def test_tf_pack_comma_format():
    assert tf_split("Pack, Sherri Renee") == ("Sherri", "Pack")
    print("PASS: test_tf_pack_comma_format")


def test_tf_davis_comma_with_suffix():
    """'Davis, Henry Lee Ii' — surname Davis, first Henry (suffix ignored)."""
    assert tf_split("Davis, Henry Lee Ii") == ("Henry", "Davis")
    print("PASS: test_tf_davis_comma_with_suffix")


def test_tf_montoya_single_given():
    assert tf_split("Montoya, Karla") == ("Karla", "Montoya")
    print("PASS: test_tf_montoya_single_given")


def test_tf_gonzalez_single_given():
    assert tf_split("Gonzalez, Noemi") == ("Noemi", "Gonzalez")
    print("PASS: test_tf_gonzalez_single_given")


# ── Tracerfy _split_name: natural order still works ───────────────────────
def test_tf_natural_two_token():
    assert tf_split("Sherri Pack") == ("Sherri", "Pack")
    print("PASS: test_tf_natural_two_token")


def test_tf_natural_three_token():
    assert tf_split("John Paul Smith") == ("John", "Smith")
    print("PASS: test_tf_natural_three_token")


def test_tf_natural_suffix_skipped():
    """Closes the deferred suffix bug: 'John Paul Smith Jr' must not return
    ('John', 'Jr')."""
    assert tf_split("John Paul Smith Jr") == ("John", "Smith")
    assert tf_split("Floyd Baker III") == ("Floyd", "Baker")
    print("PASS: test_tf_natural_suffix_skipped")


def test_tf_single_token_unparseable():
    assert tf_split("Jones") == ("", "")
    print("PASS: test_tf_single_token_unparseable")


def test_tf_blank_unparseable():
    assert tf_split("") == ("", "")
    assert tf_split("   ") == ("", "")
    print("PASS: test_tf_blank_unparseable")


def test_tf_degenerate_comma_only():
    """'Pack,' with no given name falls through to natural order -> unparseable."""
    assert tf_split("Pack,") == ("", "")
    print("PASS: test_tf_degenerate_comma_only")


# ── DataSift _clean_and_split_name: the four 2026-05-28 records ────────────
def test_ds_pack_comma_format():
    assert ds_split("Pack, Sherri Renee") == ("Sherri", "Pack")
    print("PASS: test_ds_pack_comma_format")


def test_ds_davis_comma_with_suffix():
    assert ds_split("Davis, Henry Lee Ii") == ("Henry", "Davis")
    print("PASS: test_ds_davis_comma_with_suffix")


def test_ds_montoya_single_given():
    assert ds_split("Montoya, Karla") == ("Karla", "Montoya")
    print("PASS: test_ds_montoya_single_given")


def test_ds_gonzalez_single_given():
    assert ds_split("Gonzalez, Noemi") == ("Noemi", "Gonzalez")
    print("PASS: test_ds_gonzalez_single_given")


def test_ds_decedent_allcaps_comma():
    """Decedent names arrive ALL CAPS surname-first too."""
    assert ds_split("PACK, GLENN RICHARD") == ("GLENN", "PACK")
    print("PASS: test_ds_decedent_allcaps_comma")


# ── DataSift: natural-order + entity behavior unchanged ───────────────────
def test_ds_natural_middle_initial_stripped():
    """Existing behavior preserved: 'Eric J. Yopp' -> ('Eric', 'Yopp')."""
    assert ds_split("Eric J. Yopp") == ("Eric", "Yopp")
    print("PASS: test_ds_natural_middle_initial_stripped")


def test_ds_joint_owner_still_splits():
    """Existing joint-owner handling preserved for non-comma input."""
    assert ds_split("John & Jane Smith") == ("John", "Smith")
    print("PASS: test_ds_joint_owner_still_splits")


def test_ds_entity_returns_empty():
    """Entity check runs before the comma branch — business names stay out of
    the person fields even if comma-formatted."""
    assert ds_split("Flex Holdings LLC") == ("", "")
    assert ds_split("Smith, John Trust") == ("", "")
    print("PASS: test_ds_entity_returns_empty")


def test_ds_blank_returns_empty():
    assert ds_split("") == ("", "")
    print("PASS: test_ds_blank_returns_empty")


def test_ds_degenerate_comma_only():
    """'Pack,' with no given name falls through to natural order."""
    assert ds_split("Pack,") == ("Pack", "")
    print("PASS: test_ds_degenerate_comma_only")


if __name__ == "__main__":
    # Tracerfy
    test_tf_pack_comma_format()
    test_tf_davis_comma_with_suffix()
    test_tf_montoya_single_given()
    test_tf_gonzalez_single_given()
    test_tf_natural_two_token()
    test_tf_natural_three_token()
    test_tf_natural_suffix_skipped()
    test_tf_single_token_unparseable()
    test_tf_blank_unparseable()
    test_tf_degenerate_comma_only()
    # DataSift
    test_ds_pack_comma_format()
    test_ds_davis_comma_with_suffix()
    test_ds_montoya_single_given()
    test_ds_gonzalez_single_given()
    test_ds_decedent_allcaps_comma()
    test_ds_natural_middle_initial_stripped()
    test_ds_joint_owner_still_splits()
    test_ds_entity_returns_empty()
    test_ds_blank_returns_empty()
    test_ds_degenerate_comma_only()
    print("\nALL PASS: comma_name_split")
