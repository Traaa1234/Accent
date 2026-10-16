"""Standalone HTML coaching plan (the `coach -o plan.html` output)."""

from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import Path

from accent_analyzer.coaching.library import ACCENT_NAMES
from accent_analyzer.reports.html_report import CSS, _recommendations_html


def render_coaching_html(recs, record, accent: str | None) -> str:
    accent_text = ACCENT_NAMES.get(accent, "not set") if accent else "not set"
    meta = (
        f"Based on {escape(record.label)} ({record.recorded_at:%Y-%m-%d}) · background: {escape(accent_text)} · "
        f"generated {datetime.now():%Y-%m-%d %H:%M}"
    )
    body = _recommendations_html([r.to_report_dict() for r in recs])
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>Coaching plan</title><style>{CSS}</style></head><body><main>"
        f"<header><h1>Coaching plan</h1><p class='meta'>{meta}</p></header>"
        f"<section><h2>What to work on</h2>{body}</section>"
        "<footer>Modules marked as accent-based are suggested from your background; audio detection for "
        "T-flapping, dark /l/, rhoticity and vowels is planned for a later version.</footer>"
        "</main></body></html>"
    )


def write_coaching_html(recs, record, accent: str | None, path: str | Path) -> Path:
    path = Path(path)
    path.write_text(render_coaching_html(recs, record, accent), encoding="utf-8")
    return path
