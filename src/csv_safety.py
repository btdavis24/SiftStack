"""Defensive helpers against CSV / spreadsheet formula injection (CR-05).

Untrusted strings — OCR'd owner/decedent names, CourtNet party strings, scraped
buyer names, Tracerfy phones/emails, obituary + source URLs in Notes — flow into
CSVs that the operator opens in Excel/Sheets before uploading to DataSift. A cell
value beginning with ``=``, ``+``, ``-``, ``@`` (or a leading tab/CR) is then
interpreted as a live formula (e.g. ``=HYPERLINK(...)`` exfiltration or
``=cmd|'/c calc'!A1``). Prefixing such a value with a single quote neutralises it:
the apostrophe is not displayed and the cell is forced to text.

See CODE-REVIEW.md CR-05 (G7-CR-01) and CODE-REVIEW-WHOLE-REPO.md W6-WR-02.
"""
import csv

# Leading characters that a spreadsheet treats as the start of a formula.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value):
    """Neutralise a single cell value if it would be parsed as a formula.

    Non-strings (ints, floats, None) and empty strings pass through unchanged.
    A string whose first non-whitespace character is a formula trigger gets a
    leading single quote so the spreadsheet renders it as literal text.
    """
    if isinstance(value, str) and value:
        stripped = value.lstrip()
        if stripped and stripped[0] in _FORMULA_PREFIXES:
            return "'" + value
    return value


class SafeDictWriter(csv.DictWriter):
    """``csv.DictWriter`` that runs every cell through :func:`csv_safe`.

    Drop-in replacement — swap ``csv.DictWriter(...)`` for ``SafeDictWriter(...)``
    and every ``writerow`` / ``writerows`` value is sanitised at write time, so
    no caller has to remember to escape individual fields.
    """

    def writerow(self, rowdict):
        return super().writerow({k: csv_safe(v) for k, v in rowdict.items()})

    def writerows(self, rowdicts):
        return super().writerows(
            {k: csv_safe(v) for k, v in row.items()} for row in rowdicts
        )
