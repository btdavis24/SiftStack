"""Extract executeSearch() JS from the CourtNet search page."""
import re, os
d = "output/findacase_recon/"
files = sorted(f for f in os.listdir(d) if "04_after_captcha.html" in f)
with open(d + files[-1], encoding="utf-8") as f:
    html = f.read()

# executeSearch function
m = re.search(r"function\s+executeSearch\s*\([^)]*\)\s*\{", html)
if m:
    start = m.start()
    i = m.end()
    depth = 1
    while i < len(html) and depth > 0:
        c = html[i]
        if c == "{": depth += 1
        elif c == "}": depth -= 1
        i += 1
    print("=== executeSearch ===")
    print(html[start:i])
    print()

# Also find where the submit button's click is bound
for pattern in [
    r"\$\(.{0,80}searchFormCase.{0,80}\)\.submit\(",
    r"submit-case-search",
]:
    for m in re.finditer(pattern, html):
        window = html[max(0, m.start()-50):m.end()+600]
        window = re.sub(r"\s+", " ", window)
        print(f"[match] {window[:700]}")
        print()
