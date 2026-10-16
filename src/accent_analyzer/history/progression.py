"""Multi-recording progression rules.

* Register deflation: mean F0 falls on each of 3+ consecutive recordings, by > 30 Hz in total.
* Complacency regression: HRT rises on 2+ consecutive recordings after a breakthrough
  (a recording with HRT on target).
* Integration milestone: HRT < 25%, HIGH onsets > 40% and range > 2.6x in one recording.
* Fatigue: the latest take in a session is clearly worse than the session's first take.
* Register-independent HRT: HRT control that holds in both animated (> 180 Hz) and
  calm (< 160 Hz) registers is robust; control only when animated is fragile.

Every rule takes the recordings oldest-first and looks at how the series ends, so the
warnings describe the current state rather than something long past.
"""

from __future__ import annotations

import math

from accent_analyzer.analysis.interpret import (
    MILESTONE_HIGH_ONSET,
    MILESTONE_HRT,
    MILESTONE_RANGE,
    MIN_RELIABLE_ENDS,
    Finding,
)
from accent_analyzer.history.store import Record

DEFLATION_HZ = 30.0
DEFLATION_MIN_RECORDINGS = 3
REGRESSION_MIN_CLIMBS = 2
BREAKTHROUGH_HRT = 0.25
REGISTER_WINDOW = 10
HRT_CONTROLLED = 0.25

# take 1 -> latest take: (metric, worse direction, threshold, label, formatter)
FATIGUE_CHECKS = (
    ("hrt_rate", +1, 0.15, "HRT", lambda v: f"{v:.0%}"),
    ("high_onset_rate", -1, 0.15, "HIGH onsets", lambda v: f"{v:.0%}"),
    ("range_ratio", -1, 0.30, "range ratio", lambda v: f"{v:.2f}×"),
    ("std_f0", -1, 15.0, "pitch std dev", lambda v: f"{v:.0f} Hz"),
    ("mean_f0", -1, 20.0, "mean F0", lambda v: f"{v:.0f} Hz"),
)
FATIGUE_MIN_SIGNALS = 2


def _finite(*values: float) -> bool:
    return all(v is not None and math.isfinite(v) for v in values)


def _trailing_run(values: list[float], step) -> int:
    """Length (in recordings) of the run at the end of `values` where step(prev, cur) holds."""
    n = 1
    for prev, cur in zip(reversed(values[:-1]), reversed(values[1:])):
        if not (_finite(prev, cur) and step(prev, cur)):
            break
        n += 1
    return n if values else 0


def register_deflation(records: list[Record]) -> Finding | None:
    f0 = [r.get("mean_f0") for r in records]
    run = _trailing_run(f0, lambda prev, cur: cur < prev)
    if run < DEFLATION_MIN_RECORDINGS:
        return None
    start, end = f0[-run], f0[-1]
    if start - end <= DEFLATION_HZ:
        return None
    return Finding(
        "register_deflation", "warning", "progress",
        f"Register deflation: mean pitch has dropped on {run} recordings in a row, "
        f"{start:.0f} → {end:.0f} Hz ({start - end:.0f} Hz). Calm speech is fine, but American "
        "intonation needs headroom; warm up with a siren drill and launch phrases higher.",
    )


def complacency_regression(records: list[Record]) -> Finding | None:
    hrt = [r.get("hrt_rate") for r in records]
    run = _trailing_run(hrt, lambda prev, cur: cur > prev)
    climbs = run - 1
    if climbs < REGRESSION_MIN_CLIMBS:
        return None
    base = len(hrt) - run
    # The climb must start at or after a breakthrough recording.
    if not any(_finite(v) and v <= BREAKTHROUGH_HRT for v in hrt[: base + 1]):
        return None
    path = " → ".join(f"{v:.0%}" for v in hrt[base:])
    return Finding(
        "complacency_regression", "warning", "progress",
        f"Complacency regression: HRT has climbed on {climbs} recordings in a row since your "
        f"breakthrough ({path}). Go back to the 30-second self-audit and count rises vs falls.",
    )


def _milestone(r: Record) -> bool:
    return (
        _finite(r.get("hrt_rate"), r.get("high_onset_rate"), r.get("range_ratio"))
        and r.get("hrt_rate") < MILESTONE_HRT
        and r.get("high_onset_rate") > MILESTONE_HIGH_ONSET
        and r.get("range_ratio") > MILESTONE_RANGE
    )


def integration_milestone(records: list[Record]) -> Finding | None:
    if not records or not _milestone(records[-1]):
        return None
    hits = sum(_milestone(r) for r in records)
    first = hits == 1
    return Finding(
        "integration_milestone", "good", "progress",
        ("First integration milestone! " if first else f"Integration milestone again ({hits} recordings so far). ")
        + "Low HRT, high onsets and wide range all landed in the same recording.",
    )


def fatigue(records: list[Record]) -> Finding | None:
    if not records:
        return None
    latest = records[-1]
    takes = [r for r in records if r.session == latest.session]
    if len(takes) < 2:
        return None
    first = takes[0]
    worse = []
    for key, direction, threshold, label, fmt in FATIGUE_CHECKS:
        a, b = first.get(key), latest.get(key)
        if _finite(a, b) and (b - a) * direction >= threshold:
            worse.append(f"{label} {fmt(a)} → {fmt(b)}")
    if len(worse) < FATIGUE_MIN_SIGNALS:
        return None
    return Finding(
        "fatigue", "warning", "progress",
        f"Fatigue pattern: take {latest.take} of session {latest.session} is worse than take 1 "
        f"({'; '.join(worse)}). Short, fresh sessions beat long ones; stop after the take that "
        "felt best.",
    )


def register_independence(records: list[Record]) -> Finding | None:
    recent = [
        r for r in records[-REGISTER_WINDOW:]
        if _finite(r.get("hrt_rate")) and r.metrics.get("n_phrase_ends", 0) >= MIN_RELIABLE_ENDS
    ]
    by_register = {
        reg: [r.get("hrt_rate") <= HRT_CONTROLLED for r in recent if r.register_label == reg]
        for reg in ("animated", "calm")
    }
    controlled = {reg: bool(v) and sum(v) / len(v) >= 0.5 for reg, v in by_register.items()}
    counts = {reg: f"{sum(v)}/{len(v)}" for reg, v in by_register.items()}
    if not any(by_register.values()):
        return None
    if controlled["animated"] and controlled["calm"]:
        return Finding(
            "register_independence", "good", "progress",
            f"Robust HRT control: it holds in both animated ({counts['animated']}) and calm "
            f"({counts['calm']}) recordings.",
        )
    if controlled["animated"] and by_register["calm"]:
        return Finding(
            "register_independence", "warning", "progress",
            f"Fragile HRT control: falls hold when you're animated ({counts['animated']}) but not in "
            f"calm speech ({counts['calm']}). Practice statement falls at a relaxed, low pitch.",
        )
    if controlled["animated"]:
        return Finding(
            "register_independence", "info", "progress",
            "HRT is under control in animated recordings; record a calm take (mean pitch under "
            "160 Hz) to check it holds there too.",
        )
    if controlled["calm"] and by_register["animated"]:
        return Finding(
            "register_independence", "warning", "progress",
            f"HRT control holds in calm speech ({counts['calm']}) but slips when you're animated "
            f"({counts['animated']}).",
        )
    return None


RULES = (integration_milestone, register_deflation, complacency_regression, fatigue, register_independence)


def progression(records: list[Record]) -> list[Finding]:
    """Findings about the latest recording in the context of all earlier ones (oldest first)."""
    return [f for rule in RULES if (f := rule(records)) is not None]
