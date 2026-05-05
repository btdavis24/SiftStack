"""Inspect dlist.php response — is it deeds list or another intermediate?"""
import re

with open("output/jcd_dlist_live.html", encoding="utf-8") as f:
    html = f.read()

text = re.sub(r"<[^>]+>", " ", html)
text = re.sub(r"\s+", " ", text).strip()
print("--- first 2000 chars of text ---")
print(text[:2000])
print()
print("=== Forms ===")
for m in re.finditer(r"<FORM[^>]*>", html, re.I):
    print(f"  {m.group(0)[:200]}")
print()
print("=== Links (.php) ===")
links = re.findall(r'href=[\"\']?([^\s\"\'>]+\.php[^\s\"\'>]*)', html, re.I)
for link in list(set(links))[:20]:
    print(f"  {link}")
print()
# Look for checkboxes (another selection step?)
cbs = re.findall(r'<input[^>]*type=[\"\']?checkbox[\"\']?[^>]*>', html, re.I)
print(f"Checkboxes: {len(cbs)}")
for cb in cbs[:3]:
    print(f"  {cb}")
