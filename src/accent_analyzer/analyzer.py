"""Command-line entry point: `accent-analyzer`."""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path

import click

from accent_analyzer.analysis import AudioLoadError
from accent_analyzer.analysis.pipeline import AnalysisResult, analyze_file
from accent_analyzer.analysis.pitch import DEFAULT_F0_MAX, DEFAULT_F0_MIN
from accent_analyzer.coaching import ACCENTS, load_library, recommend
from accent_analyzer.coaching.report import write_coaching_html
from accent_analyzer.dashboard import write_dashboard
from accent_analyzer.history import HistoryStore, progression
from accent_analyzer.reports import FORMATS, write_report
from accent_analyzer.targets import TARGETS, Status

_STATUS_MARK = {Status.ON_TARGET: "ok", Status.BELOW: "LOW", Status.ABOVE: "HIGH", Status.UNKNOWN: "?"}
_SEVERITY_MARK = {"good": "+", "info": "·", "warning": "!"}


def _json_safe(obj):
    """Replace NaN with None so the output is strict JSON."""
    if isinstance(obj, float) and math.isnan(obj):
        return None
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    return obj


def _pct(x: float) -> str:
    return "n/a" if math.isnan(x) else f"{x:.0%}"


def _row(label: str, value: str, key: str | None, statuses: dict) -> str:
    if key is None or statuses.get(key, Status.UNKNOWN) is Status.UNKNOWN:
        return f"  {label:<15}{value}"
    mark = _STATUS_MARK[statuses[key]]
    return f"  {label:<15}{value:<20}target {TARGETS[key].label():<10}[{mark}]"


def _print_report(r: AnalysisResult) -> None:
    m, s = r.metrics(), r.statuses()
    p = r.phrasing.primary
    echo = click.echo
    echo(f"{r.source}  ({r.duration:.1f}s, pitch: {r.track.method}, register: {r.register_label})")

    echo("\nRegister & variability")
    echo(_row("Mean F0", f"{m['mean_f0']:.1f} Hz", None, s))
    echo(_row("Median F0", f"{m['median_f0']:.1f} Hz", None, s))
    echo(_row("Std dev", f"{m['std_f0']:.1f} Hz", "std_f0", s))
    echo(_row("p10 / p90", f"{m['p10_f0']:.0f} / {m['p90_f0']:.0f} Hz", None, s))
    echo(_row("Range ratio", f"{m['range_ratio']:.2f}×", "range_ratio", s))
    echo(_row("Voiced ratio", _pct(m["voiced_ratio"]), "voiced_ratio", s))

    fallback = " (fallback: <15 endings at 0.20s)" if r.phrasing.used_fallback else ""
    echo(f"\nPhrase endings  (pause ≥ {p.pause_threshold:.2f}s{fallback})")
    echo(_row("HRT (rising)", f"{_pct(p.hrt_rate)}  ({p.n_rising}/{p.n_ends})", "hrt_rate", s))
    echo(_row("Falling", f"{_pct(p.fall_rate)}  ({p.n_falling}/{p.n_ends})", None, s))
    echo(_row("Level", f"{_pct(p.level_rate)}  ({p.n_level}/{p.n_ends})", None, s))
    echo(_row("Avg rise/fall", f"+{p.mean_rise_hz:.0f} / -{p.mean_fall_hz:.0f} Hz", None, s))
    mags = p.magnitude_counts()
    echo(_row("Magnitudes", "rise " + "/".join(str(mags[f"rising_{k}"]) for k in ("big", "mod", "small"))
              + "  fall " + "/".join(str(mags[f"falling_{k}"]) for k in ("big", "mod", "small"))
              + "  (big/mod/small)", None, s))
    for t, a in sorted(r.phrasing.by_threshold.items(), reverse=True):
        echo(f"    at {t:.2f}s: {a.n_ends} endings, HRT {_pct(a.hrt_rate)}")

    echo("\nPhrase onsets")
    echo(_row("HIGH", _pct(p.high_onset_rate), "high_onset_rate", s))
    echo(_row("MID", _pct(p.mid_onset_rate), None, s))
    echo(_row("LOW", _pct(p.low_onset_rate), "low_onset_rate", s))

    echo(f"\n3-second windows  ({r.windows.summary()['n_windows']} windows)")
    echo(_row("Falling", _pct(m["window_falling_rate"]), "window_falling_rate", s))
    echo(_row("Level", _pct(m["window_level_rate"]), "window_level_rate", s))
    echo(_row("Rising", _pct(m["window_rising_rate"]), "window_rising_rate", s))

    echo("\nFindings")
    for f in r.findings:
        echo(f"  [{_SEVERITY_MARK[f.severity]}] {f.message}")


def _print_progress(progress: list, n_records: int) -> None:
    click.echo(f"\nProgress  ({n_records} recordings in history)")
    if not progress:
        click.echo("  No progression flags.")
    for f in progress:
        click.echo(f"  [{_SEVERITY_MARK[f.severity]}] {f.message}")


def _print_coaching(recs: list, detailed: bool = False) -> None:
    click.echo("\nCoaching focus" if not detailed else "")
    if not recs:
        click.echo("  No coaching modules triggered.")
    for i, r in enumerate(recs, start=1):
        m = r.module
        flag = " [provisional]" if r.provisional else ""
        click.echo(f"  {i}. {m.name}{flag} — {'; '.join(r.reasons)}")
        if not detailed:
            if m.drills:
                click.echo(f"     Start with: {m.drills[0].name}")
            continue
        click.echo(f"     {m.description}")
        click.echo(f"     Target: {m.target}")
        for d in m.drills:
            mins = f" ({d.minutes} min)" if d.minutes else ""
            click.echo(f"     - {d.name}{mins}")
            for step in d.steps:
                click.echo(f"         {step}")
        if m.examples:
            click.echo("     Practice: " + " | ".join(m.examples))
        if m.words:
            click.echo("     Key words: " + ", ".join(m.words))
        for p in r.progress:
            cur = p.get("current")
            extra = ", ".join(f"{k} {p[k]}" for k in ("previous", "best") if p.get(k))
            value = f" — now {cur}" + (f" ({extra})" if extra else "") if cur else ""
            mark = "✓" if p.get("on_target") else "○"
            click.echo(f"     {mark} {p['text']}{value}")
        click.echo("")


ACCENT_OPTION = click.option(
    "--accent", type=click.Choice(ACCENTS),
    help="Your English background; adds accent-specific modules (remembered in history).",
)

HISTORY_OPTION = click.option(
    "--history", "history_path", type=click.Path(dir_okay=False), envvar="ACCENT_HISTORY",
    help="SQLite history file (or set ACCENT_HISTORY).",
)


@click.group()
@click.version_option(package_name="accent-analyzer")
def cli() -> None:
    """Acoustic analysis and coaching toward an American English accent."""


@cli.command()
@click.argument("path", type=click.Path(exists=True, dir_okay=False))
@click.option(
    "--pitch-method",
    type=click.Choice(["autocorr", "yin", "crepe"]),
    default="autocorr",
    show_default=True,
    help="F0 tracker. 'yin' (pYIN) is slower but more robust to octave errors.",
)
@click.option("--f0-min", type=float, default=DEFAULT_F0_MIN, show_default=True)
@click.option("--f0-max", type=float, default=DEFAULT_F0_MAX, show_default=True)
@click.option("--json", "as_json", is_flag=True, help="Print the full analysis as JSON.")
@click.option(
    "--output", "-o", "outputs", multiple=True, type=click.Path(dir_okay=False),
    help="Write a report; format from extension (.html or .pdf). Repeatable.",
)
@click.option("--name", help="Label for this recording in reports and history (defaults to the file name).")
@HISTORY_OPTION
@click.option("--session", help="Group takes into a session for fatigue checks (default: recording date).")
@click.option(
    "--date", "recorded_at", help="When it was recorded, e.g. '2026-10-16 08:30' (default: now).",
    type=click.DateTime(["%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"]),
)
@click.option("--trajectory", "trajectory_n", type=int, default=10, show_default=True,
              help="Recordings shown in the report's trajectory.")
@ACCENT_OPTION
def analyze(
    path: str, pitch_method: str, f0_min: float, f0_max: float, as_json: bool,
    outputs: tuple[str, ...], name: str | None, history_path: str | None, session: str | None,
    recorded_at: datetime | None, trajectory_n: int, accent: str | None,
) -> None:
    """Analyze a recording (.m4a, .mp3, .wav, .flac)."""
    for out in outputs:
        if Path(out).suffix.lower() not in FORMATS:
            raise click.BadParameter(f"{out}: use a .html or .pdf extension", param_hint="--output")
    try:
        result = analyze_file(path, pitch_method=pitch_method, f0_min=f0_min, f0_max=f0_max)
    except (AudioLoadError, NotImplementedError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc

    history, progress, record, n_records = None, None, None, 0
    if history_path:
        with HistoryStore(history_path) as store:
            if accent is None:  # remembered from the latest recording
                accent = next((r.accent for r in reversed(store.all()) if r.accent), None)
            record = store.add(result, name=name, session=session, recorded_at=recorded_at, accent=accent)
            # Rules judge the new recording against everything recorded up to it.
            records = [r for r in store.all() if r.recorded_at <= record.recorded_at]
            progress = progression(records)
            history = [
                {"label": r.label, **{k: r.get(k) for k in r.metrics}} for r in records[-trajectory_n:]
            ]
            n_records = len(store)

    recs = recommend(result.metrics(), accent=accent, history=history)
    for out in outputs:
        written = write_report(result, out, title=name, history=history, progress=progress,
                               recommendations=[r.to_report_dict() for r in recs])
        click.echo(f"Report written: {written}", err=as_json)

    if as_json:
        data = result.to_dict()
        if record is not None:
            data["history"] = {
                "record_id": record.id, "session": record.session, "take": record.take,
                "progress": [f.to_dict() for f in progress],
            }
        data["accent"] = accent
        data["recommendations"] = [r.to_dict() for r in recs]
        click.echo(json.dumps(_json_safe(data), indent=2))
    else:
        _print_report(result)
        if record is not None:
            _print_progress(progress, n_records)
        _print_coaching(recs)


_HISTORY_COLUMNS = (
    ("HRT", "hrt_rate", lambda v: f"{v:.0%}"),
    ("Falls", "fall_rate", lambda v: f"{v:.0%}"),
    ("Mean F0", "mean_f0", lambda v: f"{v:.0f}"),
    ("Std", "std_f0", lambda v: f"{v:.0f}"),
    ("Range", "range_ratio", lambda v: f"{v:.2f}×"),
    ("Voiced", "voiced_ratio", lambda v: f"{v:.0%}"),
    ("HIGH on", "high_onset_rate", lambda v: f"{v:.0%}"),
)


@cli.command(name="history")
@HISTORY_OPTION
@click.option("--last", "last_n", type=int, default=10, show_default=True, help="Number of recordings.")
@click.option("--json", "as_json", is_flag=True, help="Print the trajectory as JSON.")
def history_cmd(history_path: str | None, last_n: int, as_json: bool) -> None:
    """Show the trajectory over recent recordings and any progression flags."""
    if not history_path:
        raise click.UsageError("Give --history PATH or set ACCENT_HISTORY.")
    if not Path(history_path).expanduser().exists():
        raise click.ClickException(f"No history file at {history_path}")
    with HistoryStore(history_path) as store:
        all_records = store.all()
    records = all_records[-last_n:]
    progress = progression(all_records)
    if as_json:
        click.echo(json.dumps(_json_safe({
            "recordings": [r.to_dict() for r in records],
            "progress": [f.to_dict() for f in progress],
        }), indent=2))
        return
    if not records:
        click.echo("History is empty.")
        return
    header = f"{'#':>4}  {'Recorded':<16}  {'Name':<22}{'Take':>5}" + "".join(f"{c[0]:>9}" for c in _HISTORY_COLUMNS)
    click.echo(header)
    for r in records:
        cells = "".join(
            f"{'n/a' if math.isnan(r.get(k)) else fmt(r.get(k)):>9}" for _, k, fmt in _HISTORY_COLUMNS
        )
        name = (r.name or Path(r.source or "").name)[:21]
        click.echo(f"{r.id:>4}  {r.recorded_at:%Y-%m-%d %H:%M}  {name:<22}{r.take:>5}{cells}")
    _print_progress(progress, len(all_records))


@cli.command()
@HISTORY_OPTION
@ACCENT_OPTION
@click.option("--focus", type=click.Choice(sorted(load_library())), help="Show only this module.")
@click.option("--limit", type=int, default=4, show_default=True, help="Maximum modules (0 = all triggered).")
@click.option("--last", "last_n", type=int, default=10, show_default=True,
              help="Recordings used for previous/best progress values.")
@click.option("--json", "as_json", is_flag=True, help="Print the plan as JSON.")
@click.option("--output", "-o", type=click.Path(dir_okay=False), help="Also write the plan as HTML.")
def coach(history_path: str | None, accent: str | None, focus: str | None, limit: int, last_n: int,
          as_json: bool, output: str | None) -> None:
    """Coaching plan for your latest recording in the history."""
    if not history_path:
        raise click.UsageError("Give --history PATH or set ACCENT_HISTORY.")
    if not Path(history_path).expanduser().exists():
        raise click.ClickException(f"No history file at {history_path}")
    with HistoryStore(history_path) as store:
        records = store.all()
    if not records:
        raise click.ClickException("History is empty; analyze a recording with --history first.")
    latest = records[-1]
    accent = accent or next((r.accent for r in reversed(records) if r.accent), None)
    rows = [{k: r.get(k) for k in r.metrics} for r in records[-last_n:]]
    recs = recommend({k: latest.get(k) for k in latest.metrics}, accent=accent,
                     focus=focus, limit=limit or None, history=rows)
    if output:
        written = write_coaching_html(recs, latest, accent, output)
        click.echo(f"Coaching plan written: {written}", err=as_json)
    if as_json:
        click.echo(json.dumps(_json_safe({
            "recording": latest.to_dict(), "accent": accent,
            "recommendations": [r.to_dict() for r in recs],
        }), indent=2))
        return
    click.echo(f"Coaching plan for {latest.label} ({latest.recorded_at:%Y-%m-%d}), "
               f"accent: {accent or 'not set (use --accent)'}")
    _print_coaching(recs, detailed=True)


@cli.command()
@HISTORY_OPTION
@click.option("--output", "-o", type=click.Path(dir_okay=False), default="accent_dashboard.html",
              show_default=True, help="Where to write the dashboard HTML.")
@click.option("--open", "open_browser", is_flag=True, help="Open the dashboard in your browser.")
def dashboard(history_path: str | None, output: str, open_browser: bool) -> None:
    """Interactive dashboard across every recording in the history."""
    if not history_path:
        raise click.UsageError("Give --history PATH or set ACCENT_HISTORY.")
    if not Path(history_path).expanduser().exists():
        raise click.ClickException(f"No history file at {history_path}")
    with HistoryStore(history_path) as store:
        records = store.all()
    written = write_dashboard(records, output)
    click.echo(f"Dashboard written: {written} ({len(records)} recordings)")
    if open_browser:
        import webbrowser

        webbrowser.open(written.resolve().as_uri())


if __name__ == "__main__":
    cli()
