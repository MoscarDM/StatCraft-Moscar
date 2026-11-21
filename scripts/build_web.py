#!/usr/bin/env python3
"""Bundle the Qt-free StatCraft engines for the browser (Pyodide).

Starting from the modules the web adapter imports, follow every ``statcraft`` import
(including imports inside functions) and zip only that closure plus ``sc_web.py``.

    python scripts/build_web.py            # writes web/engine/engine.zip and web/engine/manifest.json
"""
import ast
import hashlib
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "statcraft"
OUT = ROOT / "web" / "engine"
ENTRY = ["model", "analyses", "histograms", "boxplot_graphs", "scatter", "run_chart", "imr_engine", "pareto_engine"]
FORBIDDEN = ("PySide6", "shiboken6", "matplotlib", "openpyxl", "docx", "pptx", "pypdf")


def imported_modules(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 1:
            if node.module:
                yield node.module.split(".")[0]
            else:  # "from . import x, y"
                for alias in node.names:
                    yield alias.name
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and (node.module or "").startswith("statcraft"):
            parts = node.module.split(".")
            if len(parts) > 1:
                yield parts[1]
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("statcraft."):
                    yield alias.name.split(".")[1]


def forbidden_imports(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module]
        for n in names:
            if n.split(".")[0] in FORBIDDEN:
                found.add(n.split(".")[0])
    return found


def closure():
    seen, todo = set(), list(ENTRY)
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        path = PKG / (name + ".py")
        if (PKG / name).is_dir():  # sub-package: ship it whole (its internal imports stay inside it)
            seen.add(name)
            continue
        if not path.exists():
            raise SystemExit("missing module statcraft/%s.py (imported by the web bundle)" % name)
        seen.add(name)
        todo.extend(m for m in imported_modules(path) if m not in seen)
    return sorted(seen)


def main():
    modules = closure()
    problems = {m: sorted(forbidden_imports(PKG / (m + ".py"))) for m in modules if (PKG / (m + ".py")).exists()}
    problems = {m: p for m, p in problems.items() if p}
    # Only a problem when imported at module level in a way that would run; report all so it is visible.
    OUT.mkdir(parents=True, exist_ok=True)
    zip_path = OUT / "engine.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.write(PKG / "__init__.py", "statcraft/__init__.py")
        for m in modules:
            if (PKG / m).is_dir():
                for f in sorted((PKG / m).rglob("*.py")):
                    z.write(f, "statcraft/" + f.relative_to(PKG).as_posix())
            else:
                z.write(PKG / (m + ".py"), "statcraft/%s.py" % m)
        z.write(ROOT / "web" / "py" / "sc_web.py", "sc_web.py")
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()[:12]
    version = (PKG / "__init__.py").read_text(encoding="utf-8").split('"')[1]
    (OUT / "manifest.json").write_text(
        json.dumps({"statcraft": version, "build": digest, "modules": modules}, indent=2), encoding="utf-8"
    )
    print("modules (%d): %s" % (len(modules), ", ".join(modules)))
    print("wrote %s (%d KB), build %s" % (zip_path.relative_to(ROOT), zip_path.stat().st_size // 1024, digest))
    if problems:
        print("note: GUI-library imports found (must be lazy/unused in the web path): %s" % problems)
    return 0


if __name__ == "__main__":
    sys.exit(main())
