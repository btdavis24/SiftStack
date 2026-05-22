"""Debug: why doesn't _search_names_unique regex extract rows?"""
import sys, re
sys.path.insert(0, "src")
from jefferson_deeds_scraper import _search_names_unique  # noqa: F401

# Read saved HTML instead of re-querying
with open("output/jcd_name_recon.html", encoding="utf-8") as f:
    html = f.read()

# The regex we used
row_re = re.compile(
    r"VALUE='([^']+)'[^<]*(?:</[^>]+>[^<]*)*?<b>([^<]+)</b></span></td>"
    r"\s*<td[^>]*>\s*<span[^>]*>\s*<b>(\d+)</b>",
    re.IGNORECASE,
)
matches = list(row_re.finditer(html))
print(f"Main regex matched: {len(matches)}")
for m in matches[:5]:
    print(f"  {m.group(2).strip()!r:<40} count={m.group(3)}")

# Fallback regex
fb = re.findall(
    r"VALUE='[^:']+:\d+:[A-Z]+:[A-Z]+:\d+:([^:']+):'",
    html, re.IGNORECASE,
)
print(f"\nFallback matched: {len(fb)}")
for display in fb[:5]:
    print(f"  {display.strip()!r}")

# Raw: how many VALUE= attrs are there?
print(f"\nTotal VALUE=' occurrences: {html.count(chr(86)+chr(65)+chr(76)+chr(85)+chr(69)+chr(61)+chr(39))}")

# Show a representative VALUE attr with its immediate context
v_idx = html.find("VALUE='")
print(f"\nFirst VALUE attr + 400 chars context:")
print(repr(html[v_idx:v_idx+400]))
