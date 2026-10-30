"""Turn `themeforge --selftest report.json` results into GitHub Actions annotations.

    python tools/selftest_report.py selftest-source.json selftest-frozen.json ...

Every check becomes a one-line notice (failures become errors), so results can be read from the
run's summary page without downloading anything. Exits 1 if any report is missing or has a failed
required check.
"""
import json
import sys
from pathlib import Path


def esc(text):
    return str(text).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def main(paths):
    bad = False
    for p in paths:
        path = Path(p)
        if not path.exists():
            print(f"::error title={path.name}::report missing (the self-test crashed before writing it)")
            bad = True
            continue
        r = json.loads(path.read_text(encoding="utf-8"))
        head = f"{path.stem}: ThemeForge {r['version']} frozen={r['frozen']} qt={r['qt_platform']}"
        lines = []
        for c in r["checks"]:
            mark = "ok" if c["ok"] else ("FAIL" if c["required"] else "warn")
            lines.append(f"[{mark}] {c['name']}: {c['detail']}")
            if c["required"] and not c["ok"]:
                print(f"::error title={esc(path.stem)} - {esc(c['name'])}::{esc(c['detail'])}")
        print(f"::notice title={esc(head)}::{esc(chr(10).join(lines))}")
        print(head)
        print("\n".join(lines))
        bad = bad or bool(r["failed"])
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
