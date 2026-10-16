"""Command-line entry point: `accent-analyzer`."""

from __future__ import annotations

import json
import math

import click

from accent_analyzer.analysis import AudioLoadError
from accent_analyzer.analysis.pipeline import AnalysisResult, analyze_file
from accent_analyzer.analysis.pitch import DEFAULT_F0_MAX, DEFAULT_F0_MIN
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
def analyze(path: str, pitch_method: str, f0_min: float, f0_max: float, as_json: bool) -> None:
    """Analyze a recording (.m4a, .mp3, .wav, .flac)."""
    try:
        result = analyze_file(path, pitch_method=pitch_method, f0_min=f0_min, f0_max=f0_max)
    except (AudioLoadError, NotImplementedError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc

    if as_json:
        click.echo(json.dumps(_json_safe(result.to_dict()), indent=2))
    else:
        _print_report(result)


if __name__ == "__main__":
    cli()
