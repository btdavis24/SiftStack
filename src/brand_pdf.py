"""Rednour brand PDF styling primitives.

Locked design system used by every company deliverable — lender flyers,
disposition flyers, internal SOPs, checklists, market reports.

Visual spec: docs/brand/pdf_styling.md.

A new deliverable should:
    1. import brand_pdf as brand
    2. doc = brand.make_doc(out_path, "Title For Header")
    3. painter = brand.page_painter("Title For Header", "TAGLINE")
    4. build a `flow` list using brand.status_bar / brand.section_label /
       brand.hrule / brand.SECTION_HEADER / brand.TITLE / brand.BODY etc.
    5. doc.build(flow, onFirstPage=painter, onLaterPages=painter)

Do NOT introduce new fonts, colors, or band layouts in deliverable files —
add them here so the brand stays consistent.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

import config


# ── Palette ───────────────────────────────────────────────────────────
CREAM = colors.HexColor("#FBF7EE")
INK = colors.HexColor("#0F0F0F")
DARK = colors.HexColor("#1A1A1A")
RED = colors.HexColor("#C8102E")
RED_TINT = colors.HexColor("#FDEEF1")
MUTED = colors.HexColor("#6B6B6B")
RULE = colors.HexColor("#D8D2C7")
SOFT_BG = colors.HexColor("#F4EFE3")
WHITE = colors.white


# ── Page geometry ─────────────────────────────────────────────────────
PAGE_W, PAGE_H = letter
MARGIN = 0.45 * inch
CONTENT_W = PAGE_W - 2 * MARGIN

HEADER_H = 0.65 * inch
FOOTER_H = 0.45 * inch


# ── Type system ───────────────────────────────────────────────────────
def _style(name: str, **kw) -> ParagraphStyle:
    base = dict(fontName="Helvetica", fontSize=10, textColor=DARK, leading=12)
    base.update(kw)
    return ParagraphStyle(name, **base)


SMALLCAPS = _style(
    "smallcaps", fontName="Helvetica", fontSize=8, textColor=MUTED,
    alignment=TA_LEFT, leading=10,
)
TITLE = _style(
    "title", fontName="Times-Bold", fontSize=34, textColor=DARK,
    alignment=TA_LEFT, leading=38,
)
SUBTITLE = _style(
    "subtitle", fontName="Helvetica", fontSize=10, textColor=MUTED,
    alignment=TA_LEFT, leading=14,
)
SECTION_HEADER = _style(
    "section_header", fontName="Helvetica-Bold", fontSize=10, textColor=DARK,
    alignment=TA_LEFT, leading=12,
)
BODY = _style(
    "body", fontName="Helvetica", fontSize=10, textColor=DARK, leading=14,
)
ITEM_TITLE = _style(
    "item_title", fontName="Helvetica-Bold", fontSize=11, textColor=DARK,
    alignment=TA_LEFT, leading=14,
)
ITEM_DESC = _style(
    "item_desc", fontName="Helvetica", fontSize=9, textColor=MUTED,
    alignment=TA_LEFT, leading=12,
)
DISCLAIMER = _style(
    "disclaimer", fontName="Helvetica-Oblique", fontSize=7.5, textColor=MUTED,
    alignment=TA_LEFT, leading=10,
)


# ── Canvas-level painters (header band, footer, cream bg) ─────────────
def _draw_logo(c: Canvas, x: float, y_center: float, h: float = 30) -> None:
    path: Path = config.COMPANY_LOGO_PATH
    if path.exists():
        try:
            img = ImageReader(str(path))
            iw, ih = img.getSize()
            w = h * (iw / ih)
            c.drawImage(
                img, x, y_center - h / 2, width=w, height=h,
                mask="auto", preserveAspectRatio=True,
            )
            return
        except Exception:
            pass
    c.setFont("Helvetica-Bold", 14)
    c.setFillColor(RED)
    c.drawString(x, y_center - 5, "REDNOUR")


def page_painter(
    title: str,
    tagline: str = "COMPANY STANDARD",
    eyebrow: str = "REI",
    total_pages: int = 1,
) -> Callable[[Canvas, object], None]:
    """Return an onPage callback that paints the cream background,
    black header band with logo + 3-line right-aligned text, red 2pt rule,
    and the bottom footer line.

    title    — line 3 of the header (red), shown after the eyebrow.
    tagline  — line 2 (white, smallcaps). Examples: "LENDER REVIEW",
               "COMPANY STANDARD", "BUYER PACKET".
    eyebrow  — prefix on line 1 (white, smallcaps). Almost always "REI".
    total_pages — used to render "PAGE NN / TT" in the footer.
    """

    def _paint(c: Canvas, _doc) -> None:
        c.setFillColor(CREAM)
        c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)

        band_y = PAGE_H - HEADER_H
        c.setFillColor(INK)
        c.rect(0, band_y, PAGE_W, HEADER_H, fill=1, stroke=0)

        _draw_logo(c, MARGIN, band_y + HEADER_H / 2, h=30)

        right_x = PAGE_W - MARGIN
        line_y = band_y + HEADER_H - 16
        c.setFont("Helvetica", 7.5)
        c.setFillColor(WHITE)
        c.drawRightString(right_x, line_y, "INVESTMENT  OPPORTUNITY")
        c.drawRightString(right_x, line_y - 10, f"CONFIDENTIAL  ·  {tagline.upper()}")
        c.setFont("Helvetica-Bold", 7.5)
        c.setFillColor(RED)
        c.drawRightString(
            right_x, line_y - 20,
            f"{eyebrow.upper()}  ·  {title.upper()}",
        )

        c.setStrokeColor(RED)
        c.setLineWidth(2)
        rule_y = band_y - 4
        c.line(MARGIN, rule_y, PAGE_W - MARGIN, rule_y)

        foot_y = FOOTER_H
        c.setStrokeColor(RULE)
        c.setLineWidth(0.5)
        c.line(MARGIN, foot_y + 18, PAGE_W - MARGIN, foot_y + 18)

        c.setFont("Helvetica", 7.5)
        c.setFillColor(MUTED)
        c.drawString(
            MARGIN, foot_y + 2,
            f"{config.COMPANY_NAME.upper()}  ·  SHEPHERDSVILLE, KY",
        )
        c.setFont("Helvetica-Bold", 7.5)
        c.setFillColor(DARK)
        page_no = c.getPageNumber()
        c.drawRightString(
            PAGE_W - MARGIN, foot_y + 2,
            f"PAGE {page_no:02d} / {total_pages:02d}",
        )

    return _paint


# ── Flowable helpers ──────────────────────────────────────────────────
def status_bar(label: str, value: str, value_color=None) -> Table:
    """Black bar with red vertical accent on left, label on left side,
    value on right side. Use under the title to convey doc status.
    """
    if value_color is None:
        value_color = WHITE
    label_s = _style(
        "stat_lbl", fontName="Helvetica", fontSize=8.5, textColor=WHITE,
        alignment=TA_LEFT,
    )
    value_s = _style(
        "stat_val", fontName="Helvetica-Bold", fontSize=10.5,
        textColor=value_color, alignment=TA_RIGHT,
    )

    accent = Table([[""]], colWidths=[4], rowHeights=[22])
    accent.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), RED),
    ]))

    body = Table(
        [[Paragraph(label.upper(), label_s),
          Paragraph(value.upper(), value_s)]],
        colWidths=[CONTENT_W * 0.3 - 4, CONTENT_W * 0.7],
        rowHeights=[22],
    )
    body.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), INK),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (0, 0), 14),
        ("RIGHTPADDING", (-1, 0), (-1, 0), 14),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))

    outer = Table([[accent, body]], colWidths=[4, CONTENT_W - 4])
    outer.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return outer


def section_label(text: str, width: float | None = None) -> Table:
    """Section header text preceded by a short red vertical bar.
    Examples: 'INVESTMENT THESIS', 'BEFORE CONTRACT', 'CAPITAL MATH'.
    """
    if width is None:
        width = CONTENT_W
    accent = Table([[""]], colWidths=[3], rowHeights=[14])
    accent.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), RED),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    label = Paragraph(text.upper(), SECTION_HEADER)
    outer = Table([[accent, label]], colWidths=[8, width - 8])
    outer.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (0, 0), 0),
        ("RIGHTPADDING", (0, 0), (0, 0), 5),
        ("LEFTPADDING", (1, 0), (1, 0), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return outer


def hrule(color=None, thickness: float = 0.5, width: float | None = None) -> Table:
    if color is None:
        color = RULE
    if width is None:
        width = CONTENT_W
    t = Table([[""]], colWidths=[width], rowHeights=[thickness])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), color),
    ]))
    return t


def make_doc(
    output_path: Path,
    title: str,
    top_extra: float = 18,
    bottom_extra: float = 28,
) -> SimpleDocTemplate:
    """Build a SimpleDocTemplate sized to clear the brand header and footer.

    top_extra / bottom_extra are added on top of HEADER_H / FOOTER_H to give
    breathing room between the painted band and the first/last flowable.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    return SimpleDocTemplate(
        str(output_path), pagesize=letter,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=HEADER_H + top_extra,
        bottomMargin=FOOTER_H + bottom_extra,
        title=f"{title} — {config.COMPANY_NAME}",
        author=config.COMPANY_NAME,
    )
