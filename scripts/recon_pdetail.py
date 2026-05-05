"""Fetch a sample pdetail.php page to see how dollar amounts are rendered."""
import urllib.request, re

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# From our dlist.php response: a real URL with instrument number + year + cnum
url = "https://search.jeffersondeeds.com/pdetail.php?instnum=200610120994&year=2006&db=&cnum=20"
req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://search.jeffersondeeds.com/dlist.php"})
with urllib.request.urlopen(req, timeout=30) as r:
    html = r.read().decode("utf-8", errors="replace")

with open("output/jcd_pdetail_sample.html", "w", encoding="utf-8") as f:
    f.write(html)

print(f"Response size: {len(html)}")
text = re.sub(r"<[^>]+>", " ", html)
text = re.sub(r"\s+", " ", text).strip()
print()
print("--- first 3000 chars (text) ---")
print(text[:3000])
