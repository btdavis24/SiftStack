"""Test step 2: POST to dlist.php to get deed records for a specific name."""
import urllib.request, urllib.parse, re

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Colon-delimited checkbox value format (from step 1):
#   <NORMALIZED>:<nametype>:<searchtype>:<itypes>:<group>:<DISPLAY>:
# Try with 'SMITH JOHN' display -> 'SMITHJOHN' normalized
test_value = "SMITHJOHN:2:PA:ALL:0:SMITH JOHN:"

data = urllib.parse.urlencode({
    "InstDetail[paname][]": test_value,
    "search": "View Names",
}).encode()
req = urllib.request.Request(
    "https://search.jeffersondeeds.com/dlist.php",
    data=data, method="POST",
    headers={"User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded",
             "Referer": "https://search.jeffersondeeds.com/p3.php"},
)
with urllib.request.urlopen(req, timeout=30) as r:
    html = r.read().decode("utf-8", errors="replace")

print(f"Response: {len(html)} bytes")
forms = len(re.findall(r"<FORM ACTION=pdetail", html, re.IGNORECASE))
print(f"  pdetail forms: {forms}")
print(f"  HIT LIST: {'HIT LIST' in html}")
print(f"  NO HITS:  {'NO HITS FOUND' in html}")
with open("output/jcd_dlist_response.html", "w", encoding="utf-8") as f:
    f.write(html)

# Show top of response (strip tags, show first 2000 chars)
text = re.sub(r"<[^>]+>", " ", html)
text = re.sub(r"\s+", " ", text).strip()
print()
print("--- response text (first 1500) ---")
print(text[:1500])
