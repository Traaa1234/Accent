"""Single-recording interpretation rules.

Rules that need several recordings (register-independent HRT, deflation,
complacency regression, fatigue) live with the session history.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Literal

from accent_analyzer.targets import TARGETS, Status

if TYPE_CHECKING:
    from accent_analyzer.analysis.pipeline import AnalysisResult

Severity = Literal["good", "info", "warning"]
Axis = Literal["foundation", "direction", "data", "progress"]

MIN_RELIABLE_ENDS = 10
ANIMATED_F0 = 180.0
CALM_F0 = 160.0

FOUNDATION_METRICS = ("range_ratio", "std_f0", "voiced_ratio")
DIRECTION_METRICS = ("hrt_rate", "high_onset_rate", "low_onset_rate")

MILESTONE_HRT = 0.25
MILESTONE_HIGH_ONSET = 0.40
MILESTONE_RANGE = 2.6


@dataclass(frozen=True)
class Finding:
    code: str
    severity: Severity
    axis: Axis
    message: str

    def to_dict(self) -> dict:
        return asdict(self)


def register_label(mean_f0: float) -> str:
    if math.isnan(mean_f0):
        return "unknown"
    if mean_f0 > ANIMATED_F0:
        return "animated"
    if mean_f0 < CALM_F0:
        return "calm"
    return "neutral"


def _pct(x: float) -> str:
    return "n/a" if math.isnan(x) else f"{x:.0%}"


def small_sample(result: AnalysisResult) -> Finding | None:
    n = result.phrasing.primary.n_ends
    if n >= MIN_RELIABLE_ENDS:
        return None
    detail = "; ".join(
        f"{t:.2f}s pauses: {a.n_ends} endings, HRT {_pct(a.hrt_rate)}"
        for t, a in sorted(result.phrasing.by_threshold.items(), reverse=True)
    )
    return Finding(
        "small_sample",
        "warning",
        "data",
        f"Only {n} measurable phrase endings: insufficient data for reliable HRT "
        f"measurement (need {MIN_RELIABLE_ENDS}+). {detail}.",
    )


def direction_asymmetry(result: AnalysisResult) -> Finding | None:
    p = result.phrasing.primary
    rises, falls = p.n_rising, p.n_falling
    if rises + falls == 0:
        return None
    rise_mag, fall_mag = p.mean_rise_hz, p.mean_fall_hz
    counts = f"{falls} falls (avg {fall_mag:.0f} Hz) vs {rises} rises (avg {rise_mag:.0f} Hz)"
    if falls > rises and (rises == 0 or fall_mag >= rise_mag):
        return Finding("direction_asymmetry", "good", "direction", f"Falls dominate in count and size: {counts}.")
    if falls > rises:
        return Finding(
            "direction_asymmetry",
            "warning",
            "direction",
            f"You fall more often than you rise, but your falls are smaller: {counts}. "
            "Commit to the drop at the end of statements.",
        )
    if falls > 0 and fall_mag > rise_mag:
        return Finding(
            "direction_asymmetry",
            "warning",
            "direction",
            f"Your falls are big but rises are more frequent: {counts}. "
            "The fall is there; use it on more phrase endings.",
        )
    return Finding("direction_asymmetry", "warning", "direction", f"Rising endings dominate: {counts}.")


def voiced_ratio_band(result: AnalysisResult) -> Finding | None:
    v = result.register.voiced_ratio
    if math.isnan(v) or result.register.n_voiced == 0:
        return None
    if v > 0.85:
        return Finding("voiced_ratio", "warning", "foundation", f"Voiced ratio {v:.0%}: rushing, few natural pauses.")
    if v < 0.40:
        return Finding("voiced_ratio", "warning", "foundation", f"Voiced ratio {v:.0%}: hesitant, word-by-word delivery.")
    if 0.60 <= v <= 0.80:
        return Finding("voiced_ratio", "good", "foundation", f"Voiced ratio {v:.0%}: natural conversational flow.")
    side = "slightly choppy" if v < 0.60 else "slightly rushed"
    return Finding("voiced_ratio", "info", "foundation", f"Voiced ratio {v:.0%}: {side} (60–80% is natural).")


def _axis_finding(result: AnalysisResult, axis: Axis, names: tuple[str, ...], title: str) -> Finding:
    statuses = result.statuses()
    known = [n for n in names if statuses.get(n, Status.UNKNOWN) is not Status.UNKNOWN]
    on = [n for n in known if statuses[n] is Status.ON_TARGET]
    off = [TARGETS[n].description for n in known if n not in on]
    if not known:
        return Finding(f"{axis}_axis", "info", axis, f"{title}: not enough data.")
    severity: Severity = "good" if len(on) == len(known) else "warning"
    tail = f"; off target: {', '.join(off)}" if off else ""
    return Finding(f"{axis}_axis", severity, axis, f"{title}: {len(on)}/{len(known)} on target{tail}.")


def integration_milestone(result: AnalysisResult) -> Finding | None:
    m = result.metrics()
    if (
        m["hrt_rate"] < MILESTONE_HRT
        and m["high_onset_rate"] > MILESTONE_HIGH_ONSET
        and m["range_ratio"] > MILESTONE_RANGE
    ):
        return Finding(
            "integration_milestone",
            "good",
            "direction",
            "Integration milestone: HRT under 25%, high onsets over 40% and range over "
            "2.6× all in the same recording.",
        )
    return None


def interpret(result: AnalysisResult) -> list[Finding]:
    findings = [
        small_sample(result),
        integration_milestone(result),
        _axis_finding(result, "foundation", FOUNDATION_METRICS, "Acoustic foundation"),
        _axis_finding(result, "direction", DIRECTION_METRICS, "Pitch direction"),
        direction_asymmetry(result),
        voiced_ratio_band(result),
    ]
    return [f for f in findings if f is not None]
