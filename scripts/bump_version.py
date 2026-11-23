"""Atomically align all StatCraft version metadata files (and optional Pages fallbacks)."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def parse_semver(version: str) -> tuple[int, int, int]:
    """Validate and parse X.Y.Z semantic version string."""
    match = SEMVER_RE.fullmatch(version.strip())
    if not match:
        raise ValueError(f"Expected X.Y.Z version string, got: {version!r}")
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def read_versions(repo_root: Path = REPO_ROOT) -> dict[str, str]:
    """Read current versions from all 6 metadata files for verification."""
    results: dict[str, str] = {}

    init_text = (repo_root / "statcraft" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', init_text, re.MULTILINE)
    results["statcraft/__init__.py"] = m.group(1) if m else "MISSING"

    pyproj_text = (repo_root / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*["\']([^"\']+)["\']', pyproj_text, re.MULTILINE)
    results["pyproject.toml"] = m.group(1) if m else "MISSING"

    for rel in ("app_version.txt", "installer_version.txt"):
        txt = (repo_root / rel).read_text(encoding="utf-8")
        mf = re.search(r"filevers=\((\d+),\s*(\d+),\s*(\d+),\s*(\d+)\)", txt)
        ms = re.search(r"StringStruct\('FileVersion',\s*'([^']+)'\)", txt)
        if mf and ms and ms.group(1) == f"{mf.group(1)}.{mf.group(2)}.{mf.group(3)}.{mf.group(4)}":
            results[rel] = ms.group(1)
        else:
            results[rel] = "MISMATCH"

    for rel in ("app_manifest.xml", "installer_manifest.xml"):
        txt = (repo_root / rel).read_text(encoding="utf-8")
        m = re.search(r'<assemblyIdentity[\s\S]*?version="([^"]+)"', txt)
        results[rel] = m.group(1) if m else "MISSING"

    return results


def _replace_required(text: str, pattern: str, repl: str, label: str, flags: int = 0) -> str:
    new_text, count = re.subn(pattern, repl, text, flags=flags)
    if count == 0:
        raise RuntimeError(f"Could not find expected pattern in {label}: {pattern}")
    return new_text


def _update_version_rc(path: Path, ver3: str, ver4: str, tuple4: str) -> None:
    text = path.read_text(encoding="utf-8")
    text = _replace_required(text, r"filevers=\(\d+,\s*\d+,\s*\d+,\s*\d+\)", f"filevers=({tuple4})", path.name)
    text = _replace_required(text, r"prodvers=\(\d+,\s*\d+,\s*\d+,\s*\d+\)", f"prodvers=({tuple4})", path.name)
    text = _replace_required(
        text,
        r"StringStruct\('FileVersion',\s*'[^']+'\)",
        f"StringStruct('FileVersion', '{ver4}')",
        path.name,
    )
    text = _replace_required(
        text,
        r"StringStruct\('ProductVersion',\s*'[^']+'\)",
        f"StringStruct('ProductVersion', '{ver4}')",
        path.name,
    )
    path.write_text(text, encoding="utf-8")


def _update_manifest(path: Path, ver4: str) -> None:
    text = path.read_text(encoding="utf-8")
    text = _replace_required(
        text,
        r'(<assemblyIdentity[\s\S]*?version=")[^"]+(")',
        rf"\g<1>{ver4}\g<2>",
        path.name,
    )
    path.write_text(text, encoding="utf-8")


def _update_pages_html(path: Path, ver3: str) -> bool:
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    updated = text
    for span_id in ("nav-version", "hero-badge-tag", "release-card-tag"):
        updated = re.sub(
            rf'(id="{span_id}"[^>]*>)v\d+\.\d+\.\d+(<)',
            rf"\g<1>v{ver3}\g<2>",
            updated,
        )
    updated = re.sub(
        r'(id="release-card-title"[^>]*>)StatCraft v\d+\.\d+\.\d+(<)',
        rf"\g<1>StatCraft v{ver3}\g<2>",
        updated,
    )
    updated = re.sub(
        r'(let currentVersion\s*=\s*")v\d+\.\d+\.\d+(")',
        rf"\g<1>v{ver3}\g<2>",
        updated,
    )
    updated = re.sub(
        r"releases/download/v\d+\.\d+\.\d+/StatCraft(-Setup)?-v\d+\.\d+\.\d+",
        lambda m: f"releases/download/v{ver3}/StatCraft{m.group(1) or ''}-v{ver3}",
        updated,
    )
    updated = re.sub(r"v\d+\.\d+\.\d+/(StatCraft(?:-Setup)?-)v\d+\.\d+\.\d+", rf"v{ver3}/\g<1>v{ver3}", updated)
    updated = re.sub(r"(id=\"primary-subtext\"[^>]*>[^<]*· )v\d+\.\d+\.\d+(<)", rf"\g<1>v{ver3}\g<2>", updated)
    if updated != text:
        path.write_text(updated, encoding="utf-8")
        return True
    return False


def apply_version(version: str, repo_root: Path = REPO_ROOT, update_docs: bool = True) -> list[str]:
    """Update all metadata files to `version` and return list of modified relative paths."""
    major, minor, patch = parse_semver(version)
    ver3 = f"{major}.{minor}.{patch}"
    ver4 = f"{ver3}.0"
    tuple4 = f"{major}, {minor}, {patch}, 0"
    changed: list[str] = []

    init_path = repo_root / "statcraft" / "__init__.py"
    init_text = init_path.read_text(encoding="utf-8")
    new_init = _replace_required(
        init_text,
        r'^__version__\s*=\s*["\'][^"\']+["\']',
        f'__version__ = "{ver3}"',
        "statcraft/__init__.py",
        flags=re.MULTILINE,
    )
    init_path.write_text(new_init, encoding="utf-8")
    changed.append("statcraft/__init__.py")

    pyproj_path = repo_root / "pyproject.toml"
    pyproj_text = pyproj_path.read_text(encoding="utf-8")
    new_pyproj = _replace_required(
        pyproj_text,
        r'^version\s*=\s*["\'][^"\']+["\']',
        f'version = "{ver3}"',
        "pyproject.toml",
        flags=re.MULTILINE,
    )
    pyproj_path.write_text(new_pyproj, encoding="utf-8")
    changed.append("pyproject.toml")

    for rel in ("app_version.txt", "installer_version.txt"):
        _update_version_rc(repo_root / rel, ver3, ver4, tuple4)
        changed.append(rel)

    for rel in ("app_manifest.xml", "installer_manifest.xml"):
        _update_manifest(repo_root / rel, ver4)
        changed.append(rel)

    if update_docs and _update_pages_html(repo_root / "docs" / "index.html", ver3):
        changed.append("docs/index.html")

    return changed


def check_alignment(repo_root: Path = REPO_ROOT) -> tuple[str, dict[str, str]]:
    """Verify all 6 metadata files agree on the same X.Y.Z version."""
    versions = read_versions(repo_root)
    base = versions["statcraft/__init__.py"]
    expected4 = f"{base}.0"
    mismatches = []
    if versions["pyproject.toml"] != base:
        mismatches.append(f"pyproject.toml={versions['pyproject.toml']} != {base}")
    for rel in ("app_version.txt", "app_manifest.xml", "installer_version.txt", "installer_manifest.xml"):
        if versions[rel] != expected4:
            mismatches.append(f"{rel}={versions[rel]} != {expected4}")
    if mismatches:
        raise RuntimeError("Version alignment mismatch:\n  " + "\n  ".join(mismatches))
    return base, versions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bump or verify aligned StatCraft version metadata.")
    parser.add_argument("version", nargs="?", help="New semantic version X.Y.Z (e.g. 122.0.0)")
    parser.add_argument("--no-docs", action="store_true", help="Do not update fallback links in docs/index.html")
    parser.add_argument("--check", action="store_true", help="Verify all version files match without modifying anything")
    args = parser.parse_args(argv)

    if args.check:
        ver, details = check_alignment()
        print(f"All metadata aligned at {ver}:")
        for k, v in details.items():
            print(f"  {k}: {v}")
        return 0

    if not args.version:
        parser.error("Provide a version X.Y.Z or pass --check")

    changed = apply_version(args.version, update_docs=not args.no_docs)
    ver, _ = check_alignment()
    print(f"Updated StatCraft version to {ver}:")
    for rel in changed:
        print(f"  - {rel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
