"""Standalone test for Jefferson County Deeds scraper — no Playwright dependency.

Run from project root with the venv python to test the full document-fetch
address extraction path (requires pypdfium2 + pytesseract).

    .venv/Scripts/python.exe test_jcd.py
"""
import base64
import re
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

JCD_BASE_URL = "https://search.jeffersondeeds.com"
JCD_SEARCH_URL = f"{JCD_BASE_URL}/p6.php"
JCD_DETAIL_URL = f"{JCD_BASE_URL}/pdetail.php"
JCD_COUNTY_NUM = "20"
LP_INSTRUMENT_CODE = "LP"
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"

FORM_RE = re.compile(r"<FORM ACTION=pdetail\.php.*?</[Ff][Oo][Rr][Mm]>", re.DOTALL | re.IGNORECASE)
VIEW_IMG_RE = re.compile(r"viewimg\.php\?img=([A-Za-z0-9+/=]+)&type=pdf", re.IGNORECASE)
INSTNUM_RE = re.compile(r"instnum=(\d+)&year=(\d+)&db=(\d+)", re.IGNORECASE)
PARTY_RE = re.compile(r'<div class="textContainer_Truncate">(.*?)</div>', re.DOTALL | re.IGNORECASE)
DETILS_RE = re.compile(r'<td[^>]+id=detils[^>]*>(.*?)</td>', re.DOTALL | re.IGNORECASE)
DATE_RE = re.compile(r'<td width=7%[^>]*>\s*<span[^>]*>(\d{2}/\d{2}/\d{4})</span>', re.IGNORECASE)
BOOK_RE = re.compile(r'<td width=6%[^>]*>\s*<span[^>]*>(L\s+\d+\s+\d+)</span>', re.IGNORECASE)
CASE_RE = re.compile(r"^(\d{1,3}[A-Z]{2}\d+)\s+", re.IGNORECASE)
MB_RE = re.compile(r"^([\w\s.]+?)\s+(?:WS|ES|NS|SS|NWC|SWC|NEC|SEC|NW|SW|NE|SE)\b", re.IGNORECASE)
ADDR_LABELED_RE = re.compile(
    r"(?:located\s+at|property\s+address|premises\s+(?:at|known\s+as)|"
    r"commonly\s+known\s+as|street\s+address)[:\s]+(\d{2,5}\s+[^\n,;]{5,60})",
    re.IGNORECASE,
)
ADDR_NUMBER_RE = re.compile(
    r"\b(\d{2,5})\s+"
    r"((?:[NSEW]\.\s+)?[A-Z][A-Za-z]{1,20}(?:\s+[A-Z][A-Za-z]{1,20}){0,3}\s+"
    r"(?:St|Street|Ave|Avenue|Blvd|Boulevard|Dr|Drive|Rd|Road|Ln|Lane|"
    r"Ct|Court|Way|Pl|Place|Pkwy|Parkway|Cir|Circle|Ter|Terrace|Hwy|Highway)\.?)",
    re.IGNORECASE,
)


def _strip(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def _post(url, params):
    data = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("User-Agent", _UA)
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def _get_bytes(url):
    req = urllib.request.Request(url)
    req.add_header("User-Agent", _UA)
    req.add_header("Referer", f"{JCD_BASE_URL}/p6.php")
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def last_n_biz(n):
    today = datetime.now().date()
    cur = today
    cnt = 0
    while cnt < n:
        cur -= timedelta(days=1)
        if cur.weekday() < 5:
            cnt += 1
    return cur.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")


def normalize_name(raw):
    parts = raw.strip().split()
    if len(parts) >= 2:
        return f"{parts[1].title()} {parts[0].title()}"
    return raw.title()


def parse_street(legal_desc):
    m = MB_RE.match(legal_desc)
    return m.group(1).strip().title() if m else ""


def extract_address_from_text(text):
    m = ADDR_LABELED_RE.search(text)
    if m:
        return m.group(1).strip()
    m = ADDR_NUMBER_RE.search(text)
    if m:
        return f"{m.group(1)} {m.group(2).strip()}"
    return ""


def fetch_address_from_document(view_img):
    """Fetch filed PDF and OCR for street address. Returns "" if unavailable."""
    url = f"{JCD_BASE_URL}/viewimg.php?img={view_img}&type=pdf"
    try:
        pdf_bytes = _get_bytes(url)
    except Exception as e:
        return f"[fetch error: {e}]"

    try:
        import pypdfium2 as pdfium
    except ImportError:
        return "[pypdfium2 not installed — run from venv]"

    try:
        doc = pdfium.PdfDocument(pdf_bytes)
        num_pages = len(doc)
        page_order = ([1] if num_pages >= 2 else []) + list(range(min(num_pages, 4)))
        page_order = list(dict.fromkeys(page_order))  # deduplicate, preserve order

        for page_idx in page_order:
            page = doc[page_idx]
            try:
                text = page.get_textpage().get_text_range().strip()
            except Exception:
                text = ""
            if not text:
                try:
                    import pytesseract
                    bitmap = page.render(scale=3.0)
                    pil_image = bitmap.to_pil()
                    text = pytesseract.image_to_string(pil_image, config="--psm 3")
                except ImportError:
                    return "[pytesseract not installed]"
                except Exception as e:
                    continue
            addr = extract_address_from_text(text)
            if addr:
                return addr
        return "(address not found in document)"
    except Exception as e:
        return f"[pdf parse error: {e}]"


start, end = last_n_biz(3)
print(f"Date range: {start} -> {end}")
bdate = datetime.strptime(start, "%Y-%m-%d").strftime("%m/%d/%Y")
edate = datetime.strptime(end, "%Y-%m-%d").strftime("%m/%d/%Y")

print(f"POSTing to {JCD_SEARCH_URL} ...")
html = _post(JCD_SEARCH_URL, {
    "cnum": "CNUM", "searchtype": "ITYPE",
    "itype1": LP_INSTRUMENT_CODE, "itype2": "", "itype3": "",
    "bDate": bdate, "eDate": edate, "search": "Execute Search",
})

assert "HIT LIST" in html, "Unexpected response — no HIT LIST"

view_imgs = VIEW_IMG_RE.findall(html)
forms = list(FORM_RE.finditer(html))
print(f"Found {len(forms)} records, {len(view_imgs)} VIEW links")

records = []
for idx, fm in enumerate(forms):
    fh = fm.group(0)
    m = INSTNUM_RE.search(fh)
    if not m:
        continue
    instnum, year, db = m.group(1), m.group(2), m.group(3)
    detail_url = f"{JCD_DETAIL_URL}?instnum={instnum}&year={year}&db={db}&cnum={JCD_COUNTY_NUM}"
    view_img = view_imgs[idx] if idx < len(view_imgs) else ""

    divs = PARTY_RE.findall(fh)
    grantor = ""
    if divs:
        lines = [_strip(ln) for ln in re.split(r"<br\s*/?>", divs[0], flags=re.IGNORECASE) if _strip(ln)]
        grantor = lines[0] if lines else ""

    dm = DETILS_RE.search(fh)
    legal_raw = _strip(dm.group(1)) if dm else ""
    cn = CASE_RE.match(legal_raw)
    case_num = cn.group(1) if cn else ""
    legal_desc = legal_raw[cn.end():].strip() if cn else legal_raw

    date_m = DATE_RE.search(fh)
    date_filed = date_m.group(1) if date_m else ""
    try:
        date_iso = datetime.strptime(date_filed, "%m/%d/%Y").strftime("%Y-%m-%d")
    except ValueError:
        date_iso = date_filed

    book_m = BOOK_RE.search(fh)
    book_page = book_m.group(1) if book_m else ""

    # Decode VIEW img to show TIFF path
    tif_path = ""
    if view_img:
        try:
            tif_path = base64.b64decode(view_img + "==").decode("utf-8", errors="replace")
        except Exception:
            pass

    records.append({
        "owner": normalize_name(grantor),
        "street_from_legal": parse_street(legal_desc),
        "city": "Louisville",
        "state": "KY",
        "legal": legal_desc,
        "case": case_num,
        "date": date_iso,
        "book": book_page,
        "url": detail_url,
        "view_img": view_img,
        "tif_path": tif_path,
    })

print(f"\n=== {len(records)} LIS PENDENS filings | Jefferson County, KY | {start} to {end} ===\n")

# Test document fetch on first record only (slow — 1 PDF per record)
FETCH_FIRST_ONLY = True
for i, r in enumerate(records, 1):
    doc_address = ""
    if r["view_img"] and (not FETCH_FIRST_ONLY or i == 1):
        print(f"  [fetching document for record {i}...]")
        doc_address = fetch_address_from_document(r["view_img"])

    address = doc_address if doc_address and not doc_address.startswith("[") else r["street_from_legal"]

    print(f"[{i}] {r['owner']}")
    print(f"     Case:    {r['case']}")
    print(f"     Filed:   {r['date']}  |  Book: {r['book']}")
    print(f"     Address: {address or '(none found)'}")
    if doc_address:
        print(f"     DocAddr: {doc_address}")
    print(f"     Legal:   {r['legal']}")
    print(f"     TIF:     {r['tif_path']}")
    print(f"     URL:     {r['url']}")
    print()

print(f"PASS — {len(records)} records scraped successfully.")
