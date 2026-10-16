"""Command-line entry point: `accent-analyzer`."""

from __future__ import annotations

import json
import math

import click

from accent_analyzer.analysis import AudioLoadError, extract_f0, load_audio, register_metrics
from accent_analyzer.analysis.pitch import DEFAULT_F0_MAX, DEFAULT_F0_MIN
from accent_analyzer.targets import TARGETS, Status

_STATUS_MARK = {Status.ON_TARGET: "ok", Status.BELOW: "LOW", Status.ABOVE: "HIGH"}


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
@click.option("--json", "as_json", is_flag=True, help="Print metrics as JSON.")
def analyze(path: str, pitch_method: str, f0_min: float, f0_max: float, as_json: bool) -> None:
    """Analyze a recording (.m4a, .mp3, .wav, .flac)."""
    try:
        audio = load_audio(path)
        track = extract_f0(audio.samples, audio.sr, pitch_method, f0_min=f0_min, f0_max=f0_max)
    except (AudioLoadError, NotImplementedError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc

    metrics = register_metrics(track)
    if as_json:
        click.echo(json.dumps({"file": path, "pitch_method": pitch_method, **metrics.to_dict()}, indent=2))
        return

    statuses = metrics.statuses()
    click.echo(f"{path}  ({metrics.duration:.1f}s, pitch: {pitch_method})")
    rows = [
        ("Mean F0", f"{metrics.mean_f0:.1f} Hz", None),
        ("Median F0", f"{metrics.median_f0:.1f} Hz", None),
        ("Std dev", f"{metrics.std_f0:.1f} Hz", "std_f0"),
        ("p10 / p90", f"{metrics.p10_f0:.1f} / {metrics.p90_f0:.1f} Hz", None),
        ("Range ratio", f"{metrics.range_ratio:.2f}×", "range_ratio"),
        ("Voiced ratio", f"{metrics.voiced_ratio:.0%}", "voiced_ratio"),
    ]
    for label, value, key in rows:
        if key is None or math.isnan(getattr(metrics, key)):
            click.echo(f"  {label:<13}{value}")
            continue
        mark = _STATUS_MARK[statuses[key]]
        click.echo(f"  {label:<13}{value:<18}target {TARGETS[key].label():<12}[{mark}]")


if __name__ == "__main__":
    cli()
