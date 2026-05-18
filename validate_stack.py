"""V12 — AST validation pass. py_compile every .py file."""
import py_compile
from pathlib import Path

ROOT = Path(__file__).resolve().parent

failures = []
checked = 0
skipped = 0

for pyfile in ROOT.rglob("*.py"):
    if any(part in {"__pycache__", ".git", "build", "dist", "releases"}
           for part in pyfile.parts):
        skipped += 1
        continue
    # Skip NUL-byte files (forensic artifacts if any)
    try:
        if "\x00" in pyfile.read_bytes()[:64].decode("utf-8", errors="ignore"):
            skipped += 1
            continue
    except Exception:
        skipped += 1
        continue
    try:
        py_compile.compile(str(pyfile), doraise=True)
        checked += 1
    except py_compile.PyCompileError as e:
        failures.append((str(pyfile.relative_to(ROOT)),
                          str(e).splitlines()[-1][:240]))
    except Exception as e:
        failures.append((str(pyfile.relative_to(ROOT)), str(e)[:240]))

print(f"checked={checked} skipped={skipped} failures={len(failures)}")
if failures:
    print("[VALIDATION FAILURES]")
    for f, msg in failures:
        print(f"  {f}  ::  {msg}")
else:
    print("[VALIDATION CLEAN]")
