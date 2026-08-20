#!/usr/bin/env python3
"""Scaffold a new independent package under packages/."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ROOT / "packages"
TEMPLATE = ROOT / "templates" / "package"

NAME_RE = re.compile(r"^[a-z][a-z0-9_-]*$")


def normalize(raw: str) -> tuple[str, str]:
    name = raw.strip().lower()
    if not NAME_RE.fullmatch(name):
        sys.exit(
            "NAME must be lowercase alphanumeric with hyphens/underscores, "
            "starting with a letter (e.g. my-util)"
        )
    dist = name.replace("_", "-")
    import_name = dist.replace("-", "_")
    return dist, import_name


def copy_template(src: Path, dest: Path, mapping: dict[str, str]) -> None:
    dest.mkdir(parents=True, exist_ok=False)
    for path in sorted(src.rglob("*")):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(src)
        rendered_parts = [mapping.get(part, part) for part in rel.parts]
        target = dest.joinpath(*rendered_parts)
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        text = path.read_text(encoding="utf-8")
        for key, value in mapping.items():
            text = text.replace(key, value)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


def main(argv: list[str]) -> None:
    if not argv:
        sys.exit("usage: new_package.py <name> [description]")
    dist, import_name = normalize(argv[0])
    description = argv[1].strip() if len(argv) > 1 and argv[1].strip() else "Independent utility"

    dest = PACKAGES / dist
    if dest.exists():
        sys.exit(f"package already exists: {dest}")
    if not TEMPLATE.is_dir():
        sys.exit(f"missing template: {TEMPLATE}")

    mapping = {
        "__PKG_NAME__": dist,
        "__IMPORT_NAME__": import_name,
        "__DESCRIPTION__": description,
    }
    copy_template(TEMPLATE, dest, mapping)
    print(f"Created packages/{dist}")
    print(f"  import: {import_name}")
    print(f"  next:   make add PKG={dist} DEP=<library>   # optional")
    print(f"          make test PKG={dist}")


if __name__ == "__main__":
    main(sys.argv[1:])
