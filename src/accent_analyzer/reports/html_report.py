"""Self-contained HTML report: one file, charts embedded as light + dark PNGs."""

from __future__ import annotations

import base64
from datetime import datetime
from html import escape
from pathlib import Path

from accent_analyzer.reports import charts
from accent_analyzer.reports.theme import DARK, LIGHT
from accent_analyzer.reports.verdict import format_value, headline, scorecard
from accent_analyzer.targets import Status

_SEVERITY_ICON = {"good": "✓", "info": "•", "warning": "!"}
_STATUS_CLASS = {
    Status.ON_TARGET: "ok",
    Status.BELOW: "off",
    Status.ABOVE: "off",
    Status.UNKNOWN: "na",
}

CSS = """
:root {
  color-scheme: light;
  --page: #f9f9f7; --surface: #fcfcfb; --ink: #0b0b0b; --ink-2: #52514e; --muted: #898781;
  --grid: #e1e0d9; --border: rgba(11,11,11,0.10);
  --good: #006300; --good-bg: #e7f0e7; --warn: #8a5a00; --warn-bg: #fdf1d6;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --page: #0d0d0d; --surface: #1a1a19; --ink: #f0efec; --ink-2: #c3c2b7; --muted: #898781;
    --grid: #2c2c2a; --border: rgba(255,255,255,0.10);
    --good: #0ca30c; --good-bg: #1f2e1f; --warn: #fab219; --warn-bg: #3a2f15;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --page: #0d0d0d; --surface: #1a1a19; --ink: #f0efec; --ink-2: #c3c2b7; --muted: #898781;
  --grid: #2c2c2a; --border: rgba(255,255,255,0.10);
  --good: #0ca30c; --good-bg: #1f2e1f; --warn: #fab219; --warn-bg: #3a2f15;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--page); color: var(--ink);
  font: 15px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 960px; margin: 0 auto; padding: 32px 16px 64px; }
header h1 { font-size: 26px; margin: 0 0 4px; letter-spacing: -0.01em; }
.meta { color: var(--muted); font-size: 13px; margin: 0; overflow-wrap: anywhere; }
section { background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
  padding: 20px; margin-top: 20px; }
h2 { font-size: 16px; margin: 0 0 12px; }
.verdict { font-size: 16px; margin: 0; }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 14px; }
th, td { text-align: left; padding: 7px 10px; border-bottom: 1px solid var(--grid); vertical-align: top; }
th { color: var(--muted); font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; }
td.num { font-variant-numeric: tabular-nums; white-space: nowrap; }
.chip { display: inline-block; padding: 1px 8px; border-radius: 999px; font-size: 12.5px; white-space: nowrap; }
.chip.ok { color: var(--good); background: var(--good-bg); }
.chip.off { color: var(--warn); background: var(--warn-bg); }
.chip.na { color: var(--muted); }
.axis { color: var(--muted); font-size: 12.5px; }
figure { margin: 0; }
figure img { width: 100%; height: auto; display: block; }
figcaption { color: var(--ink-2); font-size: 13px; margin-top: 8px; }
details { margin-top: 12px; }
summary { cursor: pointer; color: var(--ink-2); font-size: 13px; }
ul.findings { list-style: none; padding: 0; margin: 0; }
ul.findings li { padding: 8px 0; border-bottom: 1px solid var(--grid); display: flex; gap: 10px; }
ul.findings li:last-child { border-bottom: 0; }
.sev { flex: none; width: 22px; height: 22px; border-radius: 50%; display: inline-flex;
  align-items: center; justify-content: center; font-size: 12px; font-weight: 700; }
.sev.good { color: var(--good); background: var(--good-bg); }
.sev.warning { color: var(--warn); background: var(--warn-bg); }
.sev.info { color: var(--muted); border: 1px solid var(--grid); }
.rec h3 { font-size: 15px; margin: 16px 0 4px; }
.rec ol { margin: 4px 0 0; padding-left: 20px; }
footer { color: var(--muted); font-size: 12px; margin-top: 24px; }
@media (max-width: 560px) {
  section { padding: 14px; }
  th, td { padding: 6px 6px; }
  .chip .lbl { display: none; }
}
@media print {
  :root { color-scheme: light; }
  body { background: #fff; }
  section { break-inside: avoid; border-color: #ddd; }
  details { display: none; }
}
"""


def _b64(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode()


def _figure(chart_fn, data, alt: str, caption: str) -> str:
    light, dark = chart_fn(data, LIGHT), chart_fn(data, DARK)
    return (
        "<figure><picture>"
        f'<source media="screen and (prefers-color-scheme: dark)" srcset="{_b64(dark)}">'
        f'<img src="{_b64(light)}" alt="{escape(alt)}">'
        f"</picture><figcaption>{escape(caption)}</figcaption></figure>"
    )


def _scorecard_html(result) -> str:
    rows = []
    for r in scorecard(result):
        chip = (
            f'<span class="chip {_STATUS_CLASS[r.status]}" title="{escape(r.status_text)}">{r.icon}'
            f'<span class="lbl"> {escape(r.status_text)}</span></span>'
            if r.status_text else ""
        )
        rows.append(
            f"<tr><td>{escape(r.label)}<div class='axis'>{escape(r.axis)}</div></td>"
            f"<td class='num'>{escape(r.value)}</td><td class='num'>{escape(r.target)}</td><td>{chip}</td></tr>"
        )
    return (
        "<div class='table-wrap'><table><thead><tr><th>Metric</th><th>Value</th><th>Target</th>"
        f"<th>Status</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
    )


def _phrase_table(result) -> str:
    p = result.phrasing.primary
    if not p.ends:
        return ""
    rows = "".join(
        f"<tr><td class='num'>{e.time:.2f}s</td><td class='num'>{e.start_hz:.0f}</td>"
        f"<td class='num'>{e.end_hz:.0f}</td><td class='num'>{e.delta:+.0f}</td>"
        f"<td>{e.direction}{' · ' + e.magnitude.upper() if e.magnitude else ''}</td></tr>"
        for e in p.ends
    )
    return (
        "<details><summary>Phrase endings as a table</summary><div class='table-wrap'><table>"
        "<thead><tr><th>Time</th><th>Start Hz</th><th>End Hz</th><th>Δ Hz</th><th>Class</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div></details>"
    )


def _thresholds_table(result) -> str:
    rows = "".join(
        f"<tr><td class='num'>{t:.2f}s</td><td class='num'>{a.n_ends}</td>"
        f"<td class='num'>{format_value('hrt_rate', a.hrt_rate)}</td>"
        f"<td class='num'>{format_value('fall_rate', a.fall_rate)}</td>"
        f"<td>{'used' if a is result.phrasing.primary else ''}</td></tr>"
        for t, a in sorted(result.phrasing.by_threshold.items(), reverse=True)
    )
    return (
        "<div class='table-wrap'><table><thead><tr><th>Pause threshold</th><th>Endings</th>"
        f"<th>HRT</th><th>Falling</th><th></th></tr></thead><tbody>{rows}</tbody></table></div>"
    )


def _findings_html(result) -> str:
    items = "".join(
        f"<li><span class='sev {f.severity}' aria-label='{f.severity}'>{_SEVERITY_ICON[f.severity]}</span>"
        f"<span>{escape(f.message)}</span></li>"
        for f in result.findings
    )
    return f"<ul class='findings'>{items}</ul>"


def _recommendations_html(recommendations: list[dict] | None) -> str:
    if not recommendations:
        return "<p class='meta'>No coaching modules triggered.</p>" if recommendations == [] else (
            "<p class='meta'>The coaching library is not connected yet; see the findings above.</p>"
        )
    blocks = []
    for rec in recommendations:
        drills = "".join(f"<li>{escape(d)}</li>" for d in rec.get("drills", []))
        blocks.append(
            f"<div class='rec'><h3>{escape(rec['title'])}</h3><p>{escape(rec.get('why', ''))}</p>"
            + (f"<ol>{drills}</ol>" if drills else "") + "</div>"
        )
    return "".join(blocks)


def render_html(
    result,
    title: str | None = None,
    history: list[dict] | None = None,
    recommendations: list[dict] | None = None,
) -> str:
    name = title or Path(result.source).name or "Recording"
    p = result.phrasing.primary
    fallback = " (fell back from 0.20s: fewer than 15 endings)" if result.phrasing.used_fallback else ""
    sections = [
        f"<section><h2>Verdict</h2><p class='verdict'>{escape(headline(result))}</p></section>",
        f"<section><h2>Scorecard</h2>{_scorecard_html(result)}</section>",
        "<section><h2>Pitch contour</h2>"
        + _figure(charts.pitch_contour, result, "Scatter of pitch over time with mean line and phrase-ending markers",
                  f"{result.duration:.0f} s, {int(result.track.voiced.sum())} voiced frames. Each dot is one 10 ms voiced frame. ▲/▼ mark rising and falling phrase endings. "
                  "The shaded band is the high-onset zone where American English phrases usually start.")
        + "</section>",
        "<section><h2>Phrase endings</h2>"
        + _figure(charts.phrase_end_histogram, result, "Histogram of pitch change at phrase endings",
                  f"{p.n_ends} endings. Pitch change over the last 500 ms of each phrase (pause ≥ {p.pause_threshold:.2f}s{fallback}). "
                  "Left of the gray band = falling, right = rising; BIG marks ±80 Hz.")
        + _thresholds_table(result) + _phrase_table(result) + "</section>",
        "<section><h2>3-second windows</h2>"
        + _figure(charts.window_breakdown, result, "Bar chart of falling, level and rising 3-second windows",
                  f"{len(result.windows.windows)} windows. Slope of pitch within phrases across sliding 3 s windows "
                  "(±5 Hz/s). Shaded = native target.")
        + "</section>",
        "<section><h2>Phrase onsets</h2>"
        + _figure(charts.onset_breakdown, result, "Bar chart of HIGH, MID and LOW phrase onsets",
                  f"{len(p.onsets)} onsets. Mean pitch over the first 500 ms of each phrase relative to the "
                  "recording's mean. Shaded = native target.")
        + "</section>",
    ]
    if history and len(history) >= 2:
        sections.append(
            "<section><h2>Compared with previous sessions</h2>"
            + _figure(charts.trajectory, history, "Trajectory of key metrics across sessions",
                      f"{len(history)} sessions. Shaded = target range.")
            + "</section>"
        )
    sections += [
        f"<section><h2>Findings</h2>{_findings_html(result)}</section>",
        f"<section><h2>Coaching recommendations</h2>{_recommendations_html(recommendations)}</section>",
    ]
    params = result.track.params
    meta = (
        f"{escape(Path(result.source).name or 'recording')} · {result.duration:.1f}s · "
        f"pitch: {escape(result.track.method)} ({params.get('f0_min', '')}–{params.get('f0_max', '')} Hz) · "
        f"generated {datetime.now():%Y-%m-%d %H:%M}"
    )
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>Accent report · {escape(name)}</title><style>{CSS}</style></head><body><main>"
        f"<header><h1>Accent report · {escape(name)}</h1><p class='meta'>{meta}</p></header>"
        + "".join(sections)
        + "<footer>Targets are General American reference ranges. HRT = proportion of phrase endings "
        "whose pitch rises more than 10 Hz over the final 500 ms.</footer></main></body></html>"
    )


def write_html(result, path: str | Path, **kwargs) -> Path:
    path = Path(path)
    path.write_text(render_html(result, **kwargs), encoding="utf-8")
    return path
