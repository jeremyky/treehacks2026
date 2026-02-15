#!/usr/bin/env python3
"""
Convert all Markdown reports to PDF.

Usage:
    python -m himpublic.tools.convert_reports_to_pdf
    python -m himpublic.tools.convert_reports_to_pdf --dir reports
    python -m himpublic.tools.convert_reports_to_pdf --dir artifacts/sessions --pattern "**/report.md"

Requires: pip install markdown weasyprint
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert all .md reports to PDF")
    parser.add_argument("--dir", type=str, default="reports", help="Directory to scan for .md files")
    parser.add_argument("--pattern", type=str, default="*.md", help="Glob pattern (default: *.md)")
    parser.add_argument("--recursive", action="store_true", help="Use **/*.md for subdirs")
    args = parser.parse_args()

    try:
        from himpublic.utils.md_to_pdf import convert_all_mds_to_pdf, pdf_available
    except ImportError:
        from utils.md_to_pdf import convert_all_mds_to_pdf, pdf_available  # type: ignore[no-redef]

    if not pdf_available():
        print("PDF conversion requires: pip install markdown weasyprint", file=sys.stderr)
        return 1

    base = Path(args.dir)
    if not base.is_absolute():
        # Resolve relative to package root (himpublic-py): tools -> himpublic -> src -> repo
        repo_root = Path(__file__).resolve().parent.parent.parent.parent
        base = repo_root / args.dir
    if not base.exists():
        print(f"Directory not found: {base}", file=sys.stderr)
        return 1

    pattern = "**/*.md" if args.recursive else args.pattern
    written: list[str] = []
    for md_file in sorted(base.glob(pattern)):
        try:
            from himpublic.utils.md_to_pdf import md_to_pdf
        except ImportError:
            from utils.md_to_pdf import md_to_pdf  # type: ignore[no-redef]
        out = md_to_pdf(md_file)
        if out:
            written.append(out)

    if not written:
        print(f"No .md files converted in {base} (pattern: {pattern})")
        return 0
    print(f"Converted {len(written)} file(s) to PDF:")
    for p in written:
        print(f"  {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
