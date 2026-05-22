"""Find the 'View Names' button / main form to understand dlist.php submission."""
import re

with open("output/jcd_name_recon.html", encoding="utf-8") as f:
    html = f.read()

# Look for View Names / hitcounter / hidden inputs
for kw in ["View Names", "hitcounter", "ViewNames", "onclick", "CheckBoxes"]:
    idx = html.find(kw)
    if idx < 0:
        print(f"  {kw}: not found")
        continue
    # Show 200-char window around first occurrence
    window = html[max(0, idx-100):idx+300]
    window = re.sub(r"\s+", " ", window)
    print(f"=== {kw} (idx {idx}) ===")
    print(f"  {window[:500]}")
    print()
