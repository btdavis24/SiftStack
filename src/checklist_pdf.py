"""Property Checklist PDF — salesperson-owned SOP.

Renders a one-page PDF in Rednour brand style with the Before Contract list
on the left and the After Contract list on the right. A copy goes into each
property's Google Drive folder so the team can view and edit it, but the
salesperson owns it and is responsible for keeping it current.

Source of truth for the checklist content: docs/checklists/sales_checklists.md.
Update both when items change.

Run:
    python src/checklist_pdf.py
    python src/checklist_pdf.py --output some/path.pdf
"""
from __future__ import annotations

import argparse
from pathlib import Path

from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

import brand_pdf as brand
import config


BEFORE_ITEMS: list[tuple[str, str]] = [
    ("Photos", "Full set — exterior plus every interior room."),
    ("Photos Uploaded to Drive", "Into the property's Google Drive folder."),
    ("Property Analysis", "Comps, ARV, rehab estimate, and MAO worked up so the offer is defensible."),
]

AFTER_ITEMS: list[tuple[str, str]] = [
    ("Lock Box on Property", "Place a lock box so buyers and inspectors have controlled access."),
    ("Signed Contract Saved to Drive", "Save the executed PSA to the property's Drive folder."),
    ("Title Opened", "Send the contract to the title company and confirm search is ordered."),
    ("Earnest Money Deposited", "Deliver earnest money to the title company per the contract."),
    ("Dispo Flyer Generated", "Run the disposition flyer and place the PDF in the property folder."),
    ("Buyers List Blast", "Send the flyer to the cash buyer list."),
    ("Showings Coordinated", "Schedule buyer walkthroughs through the lock box."),
    ("Assignment / Buyer Contract Signed", "Lock the end buyer with an assignment or buyer PSA."),
    ("Closing Scheduled", "Confirm closing date with title company and both parties."),
    ("Closed / Funded", "Wire received, deed recorded."),
    ("DataSift Record Updated", "Tag the record Sold so the cleanup sequence fires automatically."),
]


def _checkbox(size: float = 11) -> Table:
    box = Table([[""]], colWidths=[size], rowHeights=[size])
    box.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.8, brand.DARK),
        ("BACKGROUND", (0, 0), (-1, -1), brand.WHITE),
    ]))
    return box


def _item_row(title: str, desc: str, col_w: float) -> Table:
    body = Table(
        [[Paragraph(title, brand.ITEM_TITLE)],
         [Paragraph(desc, brand.ITEM_DESC)]],
        colWidths=[col_w - 22],
    )
    body.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (0, 0), 0),
        ("BOTTOMPADDING", (0, 0), (0, 0), 1),
        ("TOPPADDING", (0, 1), (0, 1), 1),
        ("BOTTOMPADDING", (0, 1), (0, 1), 0),
    ]))

    row = Table(
        [[_checkbox(), body]],
        colWidths=[18, col_w - 18],
    )
    row.setStyle(TableStyle([
        ("VALIGN", (0, 0), (0, 0), "TOP"),
        ("VALIGN", (1, 0), (1, 0), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, brand.RULE),
    ]))
    return row


def _column(header_text: str, items: list[tuple[str, str]], col_w: float) -> Table:
    rows: list[list] = [[brand.section_label(header_text, width=col_w)]]
    rows.append([Spacer(1, 6)])
    for title, desc in items:
        rows.append([_item_row(title, desc, col_w)])

    t = Table(rows, colWidths=[col_w])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t


def build_checklist_pdf(output_path: Path) -> Path:
    doc = brand.make_doc(output_path, title="Property Checklist")
    paint = brand.page_painter(
        title="Property Checklist",
        tagline="Company Standard",
        total_pages=1,
    )

    flow: list = []

    flow.append(brand.status_bar("Status", "Sales SOP · Salesperson Owned"))
    flow.append(brand.status_bar(
        "Scope", "Every Property · Before & After Contract",
        value_color=brand.RED,
    ))
    flow.append(Spacer(1, 12))

    flow.append(Paragraph("Property Checklist", brand.TITLE))
    flow.append(Spacer(1, 2))
    flow.append(Paragraph(
        "LIVES IN EACH PROPERTY'S DRIVE FOLDER  ·  TEAM CAN EDIT, SALES OWNS IT",
        brand.SUBTITLE,
    ))
    flow.append(Spacer(1, 8))
    flow.append(brand.hrule())
    flow.append(Spacer(1, 10))

    gap = 22
    col_w = (brand.CONTENT_W - gap) / 2
    left = _column("Before Contract", BEFORE_ITEMS, col_w)
    right = _column("After Contract", AFTER_ITEMS, col_w)

    cols = Table([[left, right]], colWidths=[col_w, col_w])
    cols.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (0, 0), 0),
        ("RIGHTPADDING", (0, 0), (0, 0), gap / 2),
        ("LEFTPADDING", (1, 0), (1, 0), gap / 2),
        ("RIGHTPADDING", (1, 0), (1, 0), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    flow.append(cols)
    flow.append(Spacer(1, 10))

    flow.append(Paragraph(
        "Sales owns this list and is responsible for keeping it current and "
        "knowing where each deal stands. A copy lives in each property's "
        "Google Drive folder so the whole team can view and edit it. Items "
        "with named owners (title, dispo) may be executed by other team "
        "members, but sales tracks completion.",
        brand.DISCLAIMER,
    ))

    doc.build(flow, onFirstPage=paint, onLaterPages=paint)
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render the Rednour Property Checklist PDF.",
    )
    parser.add_argument(
        "--output", type=Path,
        default=config.OUTPUT_DIR / "deliverables" / "Property_Checklist.pdf",
        help="Output path for the rendered PDF.",
    )
    args = parser.parse_args()
    out = build_checklist_pdf(args.output)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
