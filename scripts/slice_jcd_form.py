"""Fast slice: find first <FORM ACTION=dlist.php, emit a ~3KB window."""
import re

with open("output/jcd_name_recon.html", encoding="utf-8") as f:
    html = f.read()

# Simple substring search — O(n) not O(n^2) like DOTALL regex
needle = "ACTION=dlist.php"
idx = html.find(needle)
if idx < 0:
    needle = "action=dlist.php"
    idx = html.find(needle)
if idx < 0:
    needle = "ACTION=\"dlist.php"
    idx = html.find(needle)
if idx < 0:
    print("no needle found"); raise SystemExit

start = html.rfind("<", 0, idx)
# Find closing </FORM> within next 3000 chars
end_idx = html.lower().find("</form>", start)
if end_idx < 0 or end_idx - start > 8000:
    end_idx = start + 3000
form_html = html[start:end_idx+7]

# Compact whitespace
form_html = re.sub(r"\s+", " ", form_html)
with open("output/jcd_dlist_form_sample.txt", "w", encoding="utf-8") as f:
    f.write(form_html)
print("saved", len(form_html), "chars")

# Also count total dlist forms by substring count (fast)
total = html.count(needle)
print("total dlist forms:", total)
