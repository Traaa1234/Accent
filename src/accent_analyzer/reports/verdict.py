"""Headline verdict and scorecard rows, shared by the HTML and PDF reports."""

from __future__ import annotations

import math
from dataclasses import dataclass

from accent_analyzer.analysis.interpret import DIRECTION_METRICS, FOUNDATION_METRICS, MIN_RELIABLE_ENDS
from accent_analyzer.targets import TARGETS, Status

SCORECARD = (
    # key, label, axis
    ("hrt_rate", "HRT (rising phrase endings)", "Direction"),
    ("high_onset_rate", "HIGH phrase onsets", "Direction"),
    ("low_onset_rate", "LOW phrase onsets", "Direction"),
    ("window_falling_rate", "3 s windows falling", "Direction"),
    ("window_level_rate", "3 s windows level", "Direction"),
    ("window_rising_rate", "3 s windows rising", "Direction"),
    ("range_ratio", "Range ratio (p90/p10)", "Foundation"),
    ("std_f0", "F0 standard deviation", "Foundation"),
    ("voiced_ratio", "Voiced ratio", "Foundation"),
    ("mean_f0", "Mean F0", "Register"),
    ("median_f0", "Median F0", "Register"),
    ("fall_rate", "Falling phrase endings", "Direction"),
    ("mean_fall_hz", "Average fall size", "Direction"),
    ("mean_rise_hz", "Average rise size", "Direction"),
)

STATUS_TEXT = {
    Status.ON_TARGET: ("✓", "On target"),
    Status.BELOW: ("▼", "Below target"),
    Status.ABOVE: ("▲", "Above target"),
    Status.UNKNOWN: ("–", "No data"),
}


def format_value(key: str, value: float) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "n/a"
    target = TARGETS.get(key)
    if (target and target.percent) or key.endswith("_rate"):
        return f"{value:.0%}"
    if key == "range_ratio":
        return f"{value:.2f}×"
    if key.endswith("_hz") or key.endswith("_f0"):
        return f"{value:.0f} Hz"
    return f"{value:g}"


@dataclass(frozen=True)
class ScoreRow:
    key: str
    label: str
    axis: str
    value: str
    target: str
    status: Status

    @property
    def icon(self) -> str:
        return STATUS_TEXT[self.status][0]

    @property
    def status_text(self) -> str:
        return STATUS_TEXT[self.status][1] if self.key in TARGETS else ""


def scorecard(result) -> list[ScoreRow]:
    m, s = result.metrics(), result.statuses()
    rows = []
    for key, label, axis in SCORECARD:
        target = TARGETS.get(key)
        rows.append(ScoreRow(
            key, label, axis, format_value(key, m[key]),
            target.label() if target else "—",
            s.get(key, Status.UNKNOWN),
        ))
    return rows


def _miss(key: str, value: float) -> float:
    """Relative distance outside the target range (0 when on target)."""
    t = TARGETS[key]
    if t.low is not None and value < t.low:
        return (t.low - value) / max(abs(t.low), 0.1)
    if t.high is not None and value > t.high:
        return (value - t.high) / max(abs(t.high), 0.1)
    return 0.0


_LABELS = {key: label for key, label, _ in SCORECARD}
# Core coaching metrics outrank the 3 s window shares when choosing what to headline.
_WEIGHT = {"window_falling_rate": 0.4, "window_level_rate": 0.4, "window_rising_rate": 0.4}


def _phrase(key: str, value: float) -> str:
    return f"{_LABELS[key]} {format_value(key, value)} (target {TARGETS[key].label()})"


def headline(result) -> str:
    m, s = result.metrics(), result.statuses()
    known = {k: v for k, v in s.items() if v is not Status.UNKNOWN}
    on = [k for k, v in known.items() if v is Status.ON_TARGET]
    parts = [
        f"This {result.duration:.0f}-second recording ({result.register_label} register, "
        f"mean pitch {format_value('mean_f0', m['mean_f0'])}) meets {len(on)} of {len(known)} targets."
    ]

    def axis_summary(names, title):
        ks = [k for k in names if k in known]
        if not ks:
            return None
        n_on = sum(known[k] is Status.ON_TARGET for k in ks)
        return f"{title} {n_on}/{len(ks)}"

    axes = [a for a in (axis_summary(DIRECTION_METRICS, "pitch direction"),
                        axis_summary(FOUNDATION_METRICS, "acoustic foundation")) if a]
    if axes:
        parts.append("Scored separately: " + ", ".join(axes) + ".")

    off = sorted((k for k in known if known[k] is not Status.ON_TARGET), key=lambda k: -_miss(k, m[k]) * _WEIGHT.get(k, 1.0))
    if off:
        worst = off[:2]
        parts.append("Biggest gaps: " + "; ".join(_phrase(k, m[k]) for k in worst) + ".")
    if on:
        best = [k for k in ("hrt_rate", "high_onset_rate", "range_ratio", "voiced_ratio", "std_f0") if k in on][:2]
        if best:
            parts.append("Holding up: " + "; ".join(_phrase(k, m[k]) for k in best) + ".")
    if result.phrasing.primary.n_ends < MIN_RELIABLE_ENDS:
        parts.append(
            f"Only {result.phrasing.primary.n_ends} phrase endings were measurable, so treat the HRT figure "
            "as indicative; record at least a minute of speech for a reliable reading."
        )
    return " ".join(parts)
