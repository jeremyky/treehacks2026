"""
Convert Markdown files to PDF.

Tries, in order: (1) markdown + weasyprint, (2) pypandoc, (3) subprocess pandoc.
Install one of: pip install markdown weasyprint  |  pip install pypandoc  (and pandoc binary).
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_PDF_AVAILABLE = False
_PDF_BACKEND = None  # "weasyprint" | "pypandoc" | "pandoc"
_PDF_CSS = None
try:
    import markdown
    from weasyprint import HTML, CSS
    _PDF_AVAILABLE = True
    _PDF_BACKEND = "weasyprint"
    _PDF_CSS = CSS(string="""
@page { size: A4; margin: 2cm; }
body { font-family: system-ui, sans-serif; font-size: 11pt; line-height: 1.4; color: #222; }
h1 { font-size: 18pt; margin-top: 0; }
h2 { font-size: 14pt; margin-top: 1em; }
h3 { font-size: 12pt; }
table { border-collapse: collapse; width: 100%; margin: 0.5em 0; }
th, td { border: 1px solid #ccc; padding: 4px 8px; text-align: left; }
th { background: #f0f0f0; }
img { max-width: 100%; height: auto; }
blockquote { margin: 0.5em 0; padding-left: 1em; border-left: 3px solid #888; color: #444; }
""")
except Exception as e:
    # Catch both ImportError and OSError (missing system libs like Pango)
    logger.debug("weasyprint unavailable: %s", e)
    markdown = None  # type: ignore[assignment]
    HTML = None  # type: ignore[assignment]

if not _PDF_AVAILABLE:
    try:
        import pypandoc
        _PDF_AVAILABLE = True
        _PDF_BACKEND = "pypandoc"
    except ImportError:
        pypandoc = None  # type: ignore[assignment]


def _md_to_pdf_weasyprint(md_path: Path, pdf_path: Path) -> bool:
    base_url = md_path.parent.resolve().as_uri() + "/"
    md_content = md_path.read_text(encoding="utf-8")
    html_body = markdown.markdown(
        md_content,
        extensions=["extra", "tables", "nl2br"],
        extension_configs={"tables": {}},
    )
    html_doc = f"""<!DOCTYPE html><html><head><meta charset="utf-8"/></head><body>{html_body}</body></html>"""
    HTML(string=html_doc, base_url=base_url).write_pdf(
        pdf_path, stylesheets=[_PDF_CSS] if _PDF_CSS else []
    )
    return True


def _md_to_pdf_pandoc(md_path: Path, pdf_path: Path) -> bool:
    if _PDF_BACKEND == "pypandoc" and pypandoc is not None:
        pypandoc.convert_file(str(md_path), "pdf", outputfile=str(pdf_path), extra_args=["--pdf-engine=xelatex"])
        return True
    # Use xelatex for better Unicode support (handles ✓, emojis, etc.)
    # Use just the filename since we set cwd to parent directory
    r = subprocess.run(
        ["pandoc", md_path.name, "-o", pdf_path.name, "--pdf-engine=xelatex"],
        capture_output=True,
        timeout=60,
        cwd=str(md_path.parent),
    )
    if r.returncode != 0:
        logger.debug("pandoc stderr: %s", r.stderr.decode())
    return r.returncode == 0


def md_to_pdf(md_path: str | Path, pdf_path: str | Path | None = None) -> str | None:
    """
    Convert a Markdown file to PDF.

    Returns the path to the written PDF, or None if conversion failed or PDF deps missing.
    If pdf_path is None, uses the same path as md_path with .pdf extension.
    """
    if not _PDF_AVAILABLE and not _pandoc_available():
        logger.warning(
            "PDF conversion skipped: install markdown+weasyprint or pypandoc (or have pandoc in PATH)"
        )
        return None

    md_path = Path(md_path)
    if not md_path.exists():
        logger.warning("md_to_pdf: file not found %s", md_path)
        return None

    pdf_path = Path(pdf_path) if pdf_path else md_path.with_suffix(".pdf")

    try:
        if _PDF_BACKEND == "weasyprint":
            _md_to_pdf_weasyprint(md_path, pdf_path)
        elif _PDF_BACKEND == "pypandoc" or _pandoc_available():
            if not _md_to_pdf_pandoc(md_path, pdf_path):
                return None
        else:
            return None
        logger.info("md_to_pdf: wrote %s", pdf_path)
        return str(pdf_path)
    except Exception as e:
        logger.warning("md_to_pdf: conversion failed for %s: %s", md_path, e)
        return None


def _pandoc_available() -> bool:
    try:
        subprocess.run(["pandoc", "--version"], capture_output=True, timeout=5)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def convert_all_mds_to_pdf(
    directory: str | Path = "reports",
    pattern: str = "*.md",
) -> list[str]:
    """
    Convert all Markdown files in a directory to PDF.

    Returns list of written PDF paths.
    """
    directory = Path(directory)
    if not directory.exists():
        logger.warning("convert_all_mds_to_pdf: directory not found %s", directory)
        return []

    written: list[str] = []
    for md_file in sorted(directory.glob(pattern)):
        out = md_to_pdf(md_file)
        if out:
            written.append(out)
    return written


def pdf_available() -> bool:
    """Return True if PDF conversion is available (weasyprint, pypandoc, or pandoc in PATH)."""
    return _PDF_AVAILABLE or _pandoc_available()
