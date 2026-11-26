#!/usr/bin/env python3
"""Deterministic bundler for canonical JARVIS SDLC documentation (DEC-002).

Combines README.md + numbered SDLC documents (01..18) from the canonical SDLC
directory into a single reproducible JARVIS-SDLC-Complete-<version>.md file, or
verifies (--check) that the committed bundle is 100% synchronized with the
canonical split files. Uses Python standard library only.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

SEPARATOR = "\n\n---\n\n"


def collect_canonical_files(sdlc_dir: pathlib.Path) -> list[pathlib.Path]:
    if not sdlc_dir.is_dir():
        raise FileNotFoundError(f"Canonical SDLC directory not found: {sdlc_dir}")

    readme = sdlc_dir / "README.md"
    if not readme.is_file():
        raise FileNotFoundError(f"Missing README.md in {sdlc_dir}")

    numbered = sorted(
        p
        for p in sdlc_dir.glob("*.md")
        if p.name != "README.md" and re.match(r"^\d{2}-.*\.md$", p.name)
    )
    if not numbered:
        raise ValueError(f"No numbered SDLC markdown files found in {sdlc_dir}")

    return [readme, *numbered]


def build_bundle_text(sdlc_dir: pathlib.Path) -> str:
    files = collect_canonical_files(sdlc_dir)
    sections = [f.read_text(encoding="utf-8").strip() for f in files]
    return SEPARATOR.join(sections) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sdlc-dir",
        type=pathlib.Path,
        default=pathlib.Path("JARVIS-SDLC-v0.2.1"),
        help="Path to canonical split SDLC directory.",
    )
    parser.add_argument(
        "--output",
        type=pathlib.Path,
        default=pathlib.Path("JARVIS-SDLC-Complete-v0.2.1.md"),
        help="Output path for generated Complete.md bundle.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify output matches canonical files without modifying disk.",
    )
    args = parser.parse_args()

    expected = build_bundle_text(args.sdlc_dir)
    if args.check:
        if not args.output.is_file():
            print(f"FAIL: Bundle file missing: {args.output}", file=sys.stderr)
            return 1
        actual = args.output.read_text(encoding="utf-8")
        if actual != expected:
            print(
                f"FAIL: {args.output} is out of sync with {args.sdlc_dir}. "
                f"Run `python scripts/build_sdlc_complete.py` to regenerate.",
                file=sys.stderr,
            )
            return 1
        print(f"OK: {args.output} matches {args.sdlc_dir} ({len(expected):,} chars).")
        return 0

    args.output.write_text(expected, encoding="utf-8", newline="\n")
    print(
        f"GENERATED: {args.output} from {len(collect_canonical_files(args.sdlc_dir))} "
        f"canonical files ({len(expected):,} chars)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
