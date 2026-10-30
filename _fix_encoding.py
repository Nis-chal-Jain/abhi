from pathlib import Path

files = (
    list(Path(".").glob("*.py"))
    + list(Path("static").glob("*"))
    + [Path("README.md"), Path("start.bat"), Path("requirements.txt")]
)
repl = {
    "\u2026": "...",
    "\u2013": "-",
    "\u2014": "-",
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u00b7": " | ",
    "\ufffd": "-",
    "\u00a0": " ",
}
for p in files:
    if not p.is_file() or p.name.startswith("_fix"):
        continue
    text = p.read_bytes().decode("cp1252", errors="replace")
    for a, b in repl.items():
        text = text.replace(a, b)
    p.write_text(text, encoding="utf-8", newline="\n")
    p.read_bytes().decode("utf-8")
    print("fixed", p)
print("DONE")
