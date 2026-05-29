"""Format NoticeData records into DataSift Phonebook CSV format.

Matches the column layout from templates/datasift_phonebook_template.xlsx.
Uploads phone numbers sourced from Tracerfy skip trace into DataSift's
phonebook so records skipped by DataSift's own skip trace provider still
get dialable numbers in the CRM.

Only records with at least one phone number are included.
"""

import csv
import logging
from datetime import datetime
from pathlib import Path

from csv_safety import SafeDictWriter
from notice_parser import NoticeData

logger = logging.getLogger(__name__)

# Column headers — must match the DataSift phonebook template exactly.
_HEADERS = [
    "Business Name",
    "First Name", "Last Name",
    "Mailing address", "Mailing city", "Mailing state", "Mailing zip",
    "Property address", "Property city", "Property state", "Property zip",
]
for _i in range(1, 11):
    _HEADERS += [f"Phone {_i}", f"Phone Type {_i}", f"Phone Status {_i}", f"Phone Tags {_i}"]

# Tracerfy phone fields in priority order, with their DataSift type label.
_PHONE_FIELDS: list[tuple[str, str]] = [
    ("primary_phone", "Mobile"),
    ("mobile_1",      "Mobile"),
    ("mobile_2",      "Mobile"),
    ("mobile_3",      "Mobile"),
    ("mobile_4",      "Mobile"),
    ("mobile_5",      "Mobile"),
    ("landline_1",    "Landline"),
    ("landline_2",    "Landline"),
    ("landline_3",    "Landline"),
]


def _split_name(full_name: str) -> tuple[str, str]:
    """Split 'First [Middle] Last' into (first, last). Last token becomes last name."""
    parts = full_name.strip().rsplit(" ", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return parts[0], ""


def _collect_phones(notice: NoticeData) -> list[tuple[str, str]]:
    """Return list of (number, type) for all non-empty Tracerfy phone fields."""
    phones = []
    for field, phone_type in _PHONE_FIELDS:
        number = getattr(notice, field, "").strip()
        if number:
            phones.append((number, phone_type))
    return phones


def _build_row(notice: NoticeData, phone_tag: str) -> dict | None:
    """Build one CSV row dict. Returns None if the record has no phones."""
    phones = _collect_phones(notice)
    if not phones:
        return None

    # Use DM name + address for deceased records, owner otherwise.
    if notice.owner_deceased == "yes" and notice.decision_maker_name:
        contact_name = notice.decision_maker_name
        mail_street = notice.decision_maker_street
        mail_city   = notice.decision_maker_city
        mail_state  = notice.decision_maker_state
        mail_zip    = notice.decision_maker_zip
    else:
        contact_name = notice.owner_name
        mail_street = notice.owner_street
        mail_city   = notice.owner_city
        mail_state  = notice.owner_state
        mail_zip    = notice.owner_zip

    first, last = _split_name(contact_name)

    row: dict = {
        "Business Name": "",
        "First Name":    first,
        "Last Name":     last,
        "Mailing address": mail_street,
        "Mailing city":    mail_city,
        "Mailing state":   mail_state,
        "Mailing zip":     mail_zip,
        "Property address": notice.address,
        "Property city":    notice.city,
        "Property state":   notice.state,
        "Property zip":     notice.zip,
    }

    # Fill up to 10 phone slots; leave extras blank.
    for slot in range(1, 11):
        if slot <= len(phones):
            number, ptype = phones[slot - 1]
            row[f"Phone {slot}"]        = number
            row[f"Phone Type {slot}"]   = ptype
            row[f"Phone Status {slot}"] = "Active"
            row[f"Phone Tags {slot}"]   = phone_tag
        else:
            row[f"Phone {slot}"]        = ""
            row[f"Phone Type {slot}"]   = ""
            row[f"Phone Status {slot}"] = ""
            row[f"Phone Tags {slot}"]   = ""

    return row


def write_phonebook_csv(
    notices: list[NoticeData],
    output_dir: Path | None = None,
    phone_tag: str = "",
) -> Path:
    """Write a DataSift Phonebook CSV for all notices that have phone data.

    Args:
        notices:    Enriched NoticeData list (phones populated by Tracerfy).
        output_dir: Directory to write the CSV. Defaults to output/.
        phone_tag:  Tag string written to every Phone Tags column, e.g.
                    'tracerfy_2026-04'. Defaults to 'tracerfy_YYYY-MM'.

    Returns:
        Path to the written CSV file.
    """
    if output_dir is None:
        from config import OUTPUT_DIR
        output_dir = OUTPUT_DIR

    if not phone_tag:
        phone_tag = f"tracerfy_{datetime.now().strftime('%Y-%m')}"

    rows = []
    skipped = 0
    for notice in notices:
        row = _build_row(notice, phone_tag)
        if row:
            rows.append(row)
        else:
            skipped += 1

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    path = output_dir / f"datasift_phonebook_{timestamp}.csv"

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = SafeDictWriter(f, fieldnames=_HEADERS)
        writer.writeheader()
        writer.writerows(rows)

    logger.info(
        "Phonebook CSV: %d records written, %d skipped (no phones) → %s",
        len(rows), skipped, path,
    )
    return path
