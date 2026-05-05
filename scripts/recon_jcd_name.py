"""Recon script for Jefferson County Deeds name-search flow."""
import urllib.request, urllib.parse, re, sys

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
OUT = "output/jcd_name_recon.html"

params = {
    "cnum": ".CNUM.",
    "nametype": "2",
    "searchtype": "PA",
    "param1": "SMITH",
    "bdate": "", "edate": "",
    "itypes[]": "ALL",
    "group": "0",
    "stype": "name",
    "search": "Execute Search",
}
url = "https://search.jeffersondeeds.com/p3.php?" + urllib.parse.urlencode(params)
req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://search.jeffersondeeds.com/name.php"})
with urllib.request.urlopen(req, timeout=60) as r:
    html = r.read().decode("utf-8", errors="replace")

with open(OUT, "w", encoding="utf-8") as f:
    f.write(html)
print(f"Saved {len(html)} bytes to {OUT}")

# First <FORM ACTION=dlist.php ...> block
m = re.search(r"(<FORM ACTION=dlist\.php.*?</form>)", html, re.IGNORECASE | re.DOTALL)
if m:
    body = re.sub(r"\s+", " ", m.group(1))
    print("--- first dlist.php form ---")
    print(body[:2500])
else:
    print("No dlist.php form found")

# Count rows + extract a sample of names + counts
rows = re.findall(
    r"<form[^>]*dlist\.php[^>]*>.*?<td[^>]*>([^<]+)</td>\s*<td[^>]*>(\d+)</td>",
    html, re.IGNORECASE | re.DOTALL,
)
print(f"\nTotal unique-name rows: {len(rows)}")
for name, count in rows[:10]:
    print(f"  {name.strip():<60} count={count}")
