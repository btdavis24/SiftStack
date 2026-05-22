"""Inspect dlist.php form from saved JCD name-recon HTML."""
import re

with open("output/jcd_name_recon.html", encoding="utf-8") as f:
    html = f.read()

# Case-insensitive, allow unquoted attributes
forms = re.findall(
    r"<\s*FORM\b[^>]*\bACTION\s*=\s*[\"']?dlist\.php[\"']?[^>]*>.*?</\s*FORM\s*>",
    html, re.IGNORECASE | re.DOTALL,
)
print(f"Found {len(forms)} dlist.php forms")

if forms:
    first = re.sub(r"\s+", " ", forms[0])
    print("--- first form (first 2000 chars) ---")
    print(first[:2000])
    print()

# Extract each form's hidden inputs + find what row's checkbox + name it contains
# Looking for a structure like: <form>...<input type=hidden ...>...<input type=checkbox ...>...
for i, form in enumerate(forms[:3]):
    print(f"\n=== Form {i+1} ===")
    for m in re.finditer(r"<input\b[^>]*>", form, re.IGNORECASE):
        s = m.group(0)
        s = re.sub(r"\s+", " ", s)
        print(f"  {s[:300]}")
