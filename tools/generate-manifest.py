#!/usr/bin/env python3
"""Assemble org.ladybird.Ladybird.json from manifest-template.json plus the
generated source fragments under sources/.

The template's module "sources" arrays may contain sentinel strings
("@@NAME@@") in place of a source object. Each sentinel is replaced in-place
by the full contents of the matching sources/<file>.json array. A sentinel
whose fragment file doesn't exist yet is dropped silently (that vendoring
step just hasn't been done yet) and reported at the end.
"""
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = REPO_ROOT / "manifest-template.json"
OUTPUT = REPO_ROOT / "org.ladybird.Ladybird.json"

SENTINELS = {
    "@@CARGO_SOURCES@@": REPO_ROOT / "sources" / "cargo-sources.json",
    "@@VCPKG_SOURCES@@": REPO_ROOT / "sources" / "vcpkg-sources.json",
}


def expand_sources(sources: list, missing: set) -> list:
    expanded = []
    for entry in sources:
        if isinstance(entry, str) and entry in SENTINELS:
            fragment_path = SENTINELS[entry]
            if not fragment_path.exists():
                missing.add(entry)
                continue
            fragment = json.loads(fragment_path.read_text())
            if not isinstance(fragment, list):
                raise SystemExit(f"{fragment_path} must contain a JSON array")
            expanded.extend(fragment)
        else:
            expanded.append(entry)
    return expanded


def main() -> None:
    template = json.loads(TEMPLATE.read_text())
    missing: set = set()

    for module in template.get("modules", []):
        if "sources" in module:
            module["sources"] = expand_sources(module["sources"], missing)

    OUTPUT.write_text(json.dumps(template, indent=4) + "\n")
    print(f"Wrote {OUTPUT.relative_to(REPO_ROOT)}")

    if missing:
        print(
            "Note: the following sentinels have no fragment file yet and were "
            f"dropped: {', '.join(sorted(missing))}",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
