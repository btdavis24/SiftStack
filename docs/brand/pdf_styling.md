# Rednour PDF Brand — Company Standard

This is the **locked visual standard** for every PDF deliverable the business produces — lender flyers, disposition flyers, internal SOPs, salesperson checklists, market reports, buyer packets. It was set with the *5510 Bruns Dr* and *6307 Highway 329* lender review flyers and is now the company look-and-feel.

**Do not deviate** from this without explicit approval. Consistency across deliverables is the brand.

---

## Source of Truth

- **Code:** [src/brand_pdf.py](../../src/brand_pdf.py) — reusable styling primitives. Import this in every new deliverable.
- **Reference rendering:** [src/checklist_pdf.py](../../src/checklist_pdf.py) — a minimal example of using `brand_pdf`.
- **Existing rendering:** [src/disposition_flyer.py](../../src/disposition_flyer.py) — predates the lender-flyer redesign; will be migrated to `brand_pdf` in a future pass.

A new deliverable should *never* introduce its own colors, fonts, header bands, or footer layouts. Add them to `brand_pdf` so the brand stays consistent.

---

## Palette

| Token       | Hex       | Usage                                          |
|-------------|-----------|------------------------------------------------|
| `CREAM`     | `#FBF7EE` | Page background. Every page is cream, not white. |
| `INK`       | `#0F0F0F` | Header band background, money-row dark boxes.    |
| `DARK`      | `#1A1A1A` | Primary body text and headings.                |
| `RED`       | `#C8102E` | Brand accent. Header rule, vertical accent bars, money row, red-bold inline emphasis. |
| `RED_TINT`  | `#FDEEF1` | Light tint behind the value cell in red-highlighted table rows. |
| `MUTED`     | `#6B6B6B` | Smallcaps labels, descriptions, disclaimers.   |
| `RULE`      | `#D8D2C7` | Thin horizontal dividers, item-row underlines. |
| `SOFT_BG`   | `#F4EFE3` | Light stat-box / spec-row background.          |
| `WHITE`     | `#FFFFFF` | Text on dark backgrounds, checkbox interior.   |

---

## Typography

reportlab built-ins only (no custom font files yet):

| Style            | Font           | Size | Use                                     |
|------------------|----------------|------|-----------------------------------------|
| `TITLE`          | Times-Bold     | 34pt | Big serif page title.                   |
| `SECTION_HEADER` | Helvetica-Bold | 10pt | Block heading next to red vertical bar. |
| `ITEM_TITLE`     | Helvetica-Bold | 11pt | Checklist item label, list item label.  |
| `ITEM_DESC`      | Helvetica      | 9pt  | Description under an item title.        |
| `BODY`           | Helvetica      | 10pt | General body paragraphs.                |
| `SUBTITLE`       | Helvetica      | 10pt | Smallcaps tagline under TITLE (muted).  |
| `SMALLCAPS`      | Helvetica      | 8pt  | Header band right-aligned lines, footer. |
| `DISCLAIMER`     | Helvetica-Oblique | 7.5pt | Bottom footnote / fine print.        |

The lender flyers were designed in Playfair Display + Inter. We approximate with Times-Bold + Helvetica because they ship with reportlab. If we ever want the exact match, register `Playfair Display` and `Inter` TTFs and remap `TITLE` / `BODY` in `brand_pdf.py` — no other file needs to change.

---

## Page Geometry

- **Page size:** US Letter (8.5" × 11").
- **Margins:** 0.45" on every side. `MARGIN = 0.45 * inch`.
- **Header band:** 0.65" tall, full-width black, anchored to the top edge (paints over the cream background).
- **Footer area:** 0.45" tall, cream, with a thin gray rule above and the company line / page number below.
- **Content area:** the region between header band + 18pt of breathing room and the footer + 28pt of breathing room (`make_doc` wires these as `topMargin` / `bottomMargin`).

---

## Header Band

Painted via `brand.page_painter(title, tagline, eyebrow, total_pages)` on the canvas (not as a flowable).

**Layout:**

- Black band (`INK`) from the top edge down 0.65".
- **Logo** at left margin, vertically centered, 30pt tall. `assets/rednour_logo.png`. Falls back to text "REDNOUR" in red if the file is missing.
- **Right-aligned 3-line stack** ending at the right margin:
  1. `INVESTMENT  OPPORTUNITY` — white, Helvetica 7.5pt.
  2. `CONFIDENTIAL  ·  <TAGLINE>` — white, Helvetica 7.5pt.
  3. `<EYEBROW>  ·  <TITLE>` — **red**, Helvetica-Bold 7.5pt.
- **Red 2pt horizontal rule** spanning the content width, 4pt below the band.

**Tagline conventions:**

| Deliverable                      | Tagline             | Title (line 3)              |
|----------------------------------|---------------------|-----------------------------|
| Lender flyer                     | `LENDER REVIEW`     | property address            |
| Salesperson checklist            | `COMPANY STANDARD`  | `PROPERTY CHECKLIST`        |
| Disposition flyer (future)       | `BUYER PACKET`      | property address            |
| Internal SOP                     | `INTERNAL`          | SOP name                    |
| Market report                    | `MARKET INTEL`      | county / submarket          |

`EYEBROW` is almost always `REI`.

---

## Footer

Painted on the canvas at the bottom of every page:

- Thin gray rule (`RULE`, 0.5pt) spanning the content width, 18pt above the bottom margin.
- Left: `<COMPANY_NAME upper>  ·  SHEPHERDSVILLE, KY` — Helvetica 7.5pt, muted.
- Right: `PAGE NN / TT` — Helvetica-Bold 7.5pt, dark. The painter takes `total_pages`; the page number comes from the canvas.

---

## Status Bars

`brand.status_bar(label, value, value_color=WHITE)` — black bar with a 4pt red accent on the left.

- `label` shown left-aligned, white smallcaps.
- `value` shown right-aligned, bold. Default white. Pass `value_color=brand.RED` for the second of a stacked pair (matches the lender-flyer pattern: status white, action red).
- Height fixed at 22pt.

Use stacked status bars under the title for: doc status, scope, recipient class.

---

## Section Labels

`brand.section_label(text, width=...)` — a short red vertical bar (3pt × 14pt) followed by uppercased text in `SECTION_HEADER` style. Use as a block heading inside the content area:

- `INVESTMENT THESIS`
- `BEFORE CONTRACT`
- `CAPITAL MATH · 60–90 DAY HOLD`
- `WHY THIS WORKS`

Sits inline within a column or full-width — pass `width` to constrain.

---

## Building a New Deliverable

```python
from pathlib import Path

from reportlab.platypus import Paragraph, Spacer

import brand_pdf as brand


def build_my_deliverable(output: Path) -> Path:
    doc = brand.make_doc(output, title="My Deliverable")
    paint = brand.page_painter(
        title="My Deliverable",
        tagline="LENDER REVIEW",   # or COMPANY STANDARD / BUYER PACKET / etc.
        total_pages=1,
    )

    flow = []
    flow.append(brand.status_bar("Status", "Under Contract"))
    flow.append(brand.status_bar(
        "Action", "Purchase or Assign",
        value_color=brand.RED,
    ))
    flow.append(Spacer(1, 14))

    flow.append(Paragraph("My Deliverable", brand.TITLE))
    flow.append(Spacer(1, 8))
    flow.append(brand.hrule())
    flow.append(Spacer(1, 12))

    flow.append(brand.section_label("Some Block"))
    flow.append(Spacer(1, 6))
    flow.append(Paragraph("Body text here.", brand.BODY))

    doc.build(flow, onFirstPage=paint, onLaterPages=paint)
    return output
```

---

## Reference Deliverables

| File                                                        | Brand-aligned? |
|-------------------------------------------------------------|----------------|
| `output/deliverables/Property_Checklist.pdf`                | ✅ uses `brand_pdf` |
| External: *5510 Bruns Dr Flyer.pdf* (lender review)         | ✅ design source — produced externally |
| External: *6307 Highway 329 Crestwood Flyer.pdf* (lender)   | ✅ design source — produced externally |
| `src/disposition_flyer.py` output                            | ❌ predates this standard; migrate in a future pass |

---

## Migration Plan (TBD)

The pre-existing `disposition_flyer.py` uses its own palette and layout. Migrating it to `brand_pdf` means:
1. Replace inline color constants with `brand.RED` / `brand.DARK` / `brand.MUTED` / etc.
2. Replace the in-flow header block with `brand.page_painter` on the canvas.
3. Move the CTA footer onto the canvas so it persists across multi-page outputs.

Not urgent — the existing flyer still serves buyers — but worth scheduling so every deliverable shares the same chrome.
