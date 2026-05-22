"""Extract the full JS logic (CheckBoxes, CountBox, Details) from JCD response."""
import re

with open("output/jcd_name_recon.html", encoding="utf-8") as f:
    html = f.read()

# Grab a large window around the script block
idx = html.find("function CheckBoxes")
if idx < 0:
    print("CheckBoxes function not found")
    raise SystemExit
# 3KB window
js = html[idx : idx + 3000]
print(js)
print()
print("=== hitcounter hidden input ===")
m = re.search(r'<input[^>]*id=[\"\']?hitcounter[\"\']?[^>]*>', html, re.I)
if m:
    print(m.group(0))
print()
# Also look for `<FORM` tag containing name='mainform' or similar
print("=== All form tags in first 10000 chars ===")
for m in re.finditer(r"<FORM[^>]*>", html[:10000], re.I):
    print(m.group(0))
