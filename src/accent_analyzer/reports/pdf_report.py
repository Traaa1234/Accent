"""PDF report via reportlab, reusing the light-theme charts."""

from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

import matplotlib
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from accent_analyzer.reports import charts
from accent_analyzer.reports.theme import LIGHT
from accent_analyzer.reports.verdict import headline, scorecard
from accent_analyzer.targets import Status

_FONT = "DejaVuSans"
_FONT_BOLD = "DejaVuSans-Bold"
_SEVERITY_ICON = {"good": "✓", "info": "•", "warning": "!"}


def _register_fonts() -> None:
    if _FONT in pdfmetrics.getRegisteredFontNames():
        return
    ttf = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
    pdfmetrics.registerFont(TTFont(_FONT, str(ttf / "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont(_FONT_BOLD, str(ttf / "DejaVuSans-Bold.ttf")))


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    ink, ink2, muted = (colors.HexColor(c) for c in (LIGHT.ink, LIGHT.ink_secondary, LIGHT.muted))
    return {
        "title": ParagraphStyle("t", parent=base["Title"], fontName=_FONT_BOLD, fontSize=18, alignment=0,
                                textColor=ink, spaceAfter=2),
        "meta": ParagraphStyle("m", parent=base["Normal"], fontName=_FONT, fontSize=8, textColor=muted),
        "h2": ParagraphStyle("h", parent=base["Heading2"], fontName=_FONT_BOLD, fontSize=11.5,
                             textColor=ink, spaceBefore=10, spaceAfter=4),
        "body": ParagraphStyle("b", parent=base["Normal"], fontName=_FONT, fontSize=9.5, leading=13.5,
                               textColor=ink),
        "small": ParagraphStyle("s", parent=base["Normal"], fontName=_FONT, fontSize=8, leading=11,
                                textColor=ink2),
    }


def _image(png: bytes, width: float) -> Image:
    img = Image(io.BytesIO(png))
    img.drawWidth, img.drawHeight = width, width * img.imageHeight / img.imageWidth
    return img


def _scorecard_table(result, width: float) -> Table:
    good, warn = colors.HexColor("#006300"), colors.HexColor("#8a5a00")
    data = [["Metric", "Value", "Target", "Status"]]
    style = [
        ("FONTNAME", (0, 0), (-1, -1), _FONT),
        ("FONTNAME", (0, 0), (-1, 0), _FONT_BOLD),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor(LIGHT.muted)),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor(LIGHT.grid)),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    for i, r in enumerate(scorecard(result), start=1):
        status = f"{r.icon} {r.status_text}" if r.status_text else ""
        data.append([f"{r.label}  ({r.axis})", r.value, r.target, status])
        if r.status_text and r.status is not Status.UNKNOWN:
            style.append(("TEXTCOLOR", (3, i), (3, i), good if r.status is Status.ON_TARGET else warn))
    table = Table(data, colWidths=[width * f for f in (0.46, 0.16, 0.16, 0.22)], repeatRows=1)
    table.setStyle(TableStyle(style))
    return table


def build_pdf(result, title: str | None = None, history: list[dict] | None = None,
              recommendations: list[dict] | None = None) -> bytes:
    _register_fonts()
    st = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm,
                            topMargin=14 * mm, bottomMargin=14 * mm,
                            title=f"Accent report · {title or Path(result.source).name}")
    width = doc.width
    name = title or Path(result.source).name or "Recording"

    story = [
        Paragraph(escape(f"Accent report · {name}"), st["title"]),
        Paragraph(escape(f"{Path(result.source).name} · {result.duration:.1f}s · pitch: {result.track.method} · "
                         f"generated {datetime.now():%Y-%m-%d %H:%M}"), st["meta"]),
        Paragraph("Verdict", st["h2"]),
        Paragraph(escape(headline(result)), st["body"]),
        Paragraph("Scorecard", st["h2"]),
        _scorecard_table(result, width),
    ]
    for heading, fn, data in (
        ("Pitch contour", charts.pitch_contour, result),
        ("Phrase endings", charts.phrase_end_histogram, result),
        ("3-second windows", charts.window_breakdown, result),
        ("Phrase onsets", charts.onset_breakdown, result),
    ):
        story.append(KeepTogether([Paragraph(heading, st["h2"]), _image(fn(data, LIGHT), width)]))
    if history and len(history) >= 2:
        story.append(KeepTogether([Paragraph("Compared with previous sessions", st["h2"]),
                                   _image(charts.trajectory(history, LIGHT), width)]))

    story.append(Paragraph("Findings", st["h2"]))
    for f in result.findings:
        story.append(Paragraph(escape(f"{_SEVERITY_ICON[f.severity]}  {f.message}"), st["body"]))
        story.append(Spacer(1, 3))

    story.append(Paragraph("Coaching recommendations", st["h2"]))
    if recommendations:
        for rec in recommendations:
            story.append(Paragraph(f"<b>{escape(rec['title'])}</b>", st["body"]))
            if rec.get("why"):
                story.append(Paragraph(escape(rec["why"]), st["small"]))
            for i, d in enumerate(rec.get("drills", []), start=1):
                story.append(Paragraph(escape(f"{i}. {d}"), st["small"]))
            story.append(Spacer(1, 4))
    else:
        story.append(Paragraph("The coaching library is not connected yet; see the findings above.", st["small"]))

    doc.build(story)
    return buf.getvalue()


def write_pdf(result, path: str | Path, **kwargs) -> Path:
    path = Path(path)
    path.write_bytes(build_pdf(result, **kwargs))
    return path
