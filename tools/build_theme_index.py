#!/usr/bin/env python3
"""Builds themes/index.json (what ThemeForge's "Browse community themes" downloads) from themes/*.json.

    python3 tools/build_theme_index.py           rebuild the index
    python3 tools/build_theme_index.py --check   fail if a theme is invalid or the index is out of date (CI)
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
THEMES = ROOT / "themes"
INDEX = THEMES / "index.json"
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
ROLES = ("background", "surface", "foreground", "muted", "accent", "accent2")


def problems(path, t):
    out = []
    for key in ("name", "author", "palette"):
        if not t.get(key):
            out.append(f"missing “{key}”")
    p = t.get("palette") or {}
    for r in ROLES:
        if not HEX.match(str(p.get(r, ""))):
            out.append(f"palette.{r} must be a #rrggbb color")
    ansi = p.get("ansi", [])
    if len(ansi) != 16 or not all(HEX.match(str(c)) for c in ansi):
        out.append("palette.ansi must be 16 #rrggbb colors")
    grad = p.get("gradient", [])
    if not 1 <= len(grad) <= 8 or not all(HEX.match(str(c)) for c in grad):
        out.append("palette.gradient must be 1-8 #rrggbb colors")
    if len(t.get("description", "")) > 140:
        out.append("description should be 140 characters or fewer")
    return [f"{path.name}: {msg}" for msg in out]


def build():
    themes, errors = [], []
    for f in sorted(THEMES.glob("*.json")):
        if f.name == "index.json":
            continue
        try:
            t = json.loads(f.read_text())
        except json.JSONDecodeError as e:
            errors.append(f"{f.name}: not valid JSON ({e})")
            continue
        errors += problems(f, t)
        p = dict(t.get("palette") or {})
        p["name"] = t.get("name", f.stem)
        themes.append({"name": t.get("name", f.stem), "author": t.get("author", ""),
                       "description": t.get("description", ""), "file": f.name, "palette": p})
    names = [t["name"] for t in themes]
    errors += [f"two themes are called “{n}”" for n in sorted({n for n in names if names.count(n) > 1})]
    return {"version": 1, "themes": sorted(themes, key=lambda t: t["name"].lower())}, errors


def main():
    index, errors = build()
    text = json.dumps(index, indent=1, ensure_ascii=False) + "\n"
    if errors:
        print("\n".join(errors), file=sys.stderr)
        sys.exit(1)
    if "--check" in sys.argv:
        if not INDEX.exists() or INDEX.read_text() != text:
            print("themes/index.json is out of date - run: python3 tools/build_theme_index.py", file=sys.stderr)
            sys.exit(1)
        print(f"{len(index['themes'])} community themes OK")
        return
    INDEX.write_text(text)
    print(f"Wrote {INDEX.relative_to(ROOT)} with {len(index['themes'])} themes")


if __name__ == "__main__":
    main()
