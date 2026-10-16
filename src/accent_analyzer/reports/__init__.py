"""Per-recording reports (HTML and PDF)."""

from __future__ import annotations

from pathlib import Path

from accent_analyzer.reports.html_report import render_html, write_html
from accent_analyzer.reports.pdf_report import build_pdf, write_pdf

FORMATS = {".html": write_html, ".htm": write_html, ".pdf": write_pdf}


def write_report(result, path: str | Path, **kwargs) -> Path:
    """Write an HTML or PDF report, chosen by the file extension."""
    path = Path(path)
    writer = FORMATS.get(path.suffix.lower())
    if writer is None:
        raise ValueError(f"Unsupported report format '{path.suffix}' (use .html or .pdf)")
    return writer(result, path, **kwargs)


__all__ = ["build_pdf", "render_html", "write_html", "write_pdf", "write_report"]
