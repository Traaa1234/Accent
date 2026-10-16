"""Phrase segmentation, phrase-ending direction (HRT) and phrase-onset height.

Phrases are voiced stretches separated by unvoiced (F0 = 0) runs at least
`pause_threshold` long. The start and end of speech count as boundaries too, so
a recording with N internal pauses has N + 1 phrases, each with one ending and
one onset.

The pause threshold is adaptive: 0.20 s first, falling back to 0.12 s when that
yields fewer than 15 phrase endings (continuous conversational speech). Both
results are always kept so reports can show them side by side.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

import numpy as np

from accent_analyzer.analysis.pitch import PitchTrack

PRIMARY_PAUSE = 0.20
FALLBACK_PAUSE = 0.12
MIN_BOUNDARIES = 15
END_WINDOW = 0.5
ONSET_WINDOW = 0.5
MIN_PHRASE_VOICED = 0.10  # shorter voiced blips are ignored
MIN_END_WINDOW = 0.25  # phrase-end window must span at least this to be measurable

LEVEL_HZ = 10.0
MOD_HZ = 30.0
BIG_HZ = 80.0
HIGH_ONSET = 1.15
LOW_ONSET = 0.90

Direction = Literal["rising", "falling", "level"]
Magnitude = Literal["big", "mod", "small"]
OnsetCategory = Literal["high", "mid", "low"]


@dataclass(frozen=True)
class Phrase:
    start: float  # time of first voiced frame
    end: float  # time of last voiced frame


@dataclass(frozen=True)
class PhraseEnd:
    time: float
    start_hz: float
    end_hz: float
    delta: float
    direction: Direction
    magnitude: Magnitude | None  # None for level endings


@dataclass(frozen=True)
class Onset:
    time: float
    mean_hz: float
    ratio: float
    category: OnsetCategory


def classify_delta(delta: float) -> tuple[Direction, Magnitude | None]:
    if delta > LEVEL_HZ:
        direction: Direction = "rising"
    elif delta < -LEVEL_HZ:
        direction = "falling"
    else:
        return "level", None
    mag = abs(delta)
    return direction, "big" if mag > BIG_HZ else "mod" if mag >= MOD_HZ else "small"


def classify_onset(ratio: float) -> OnsetCategory:
    if ratio > HIGH_ONSET:
        return "high"
    if ratio < LOW_ONSET:
        return "low"
    return "mid"


def _rate(n: int, total: int) -> float:
    return n / total if total else float("nan")


def _mean(values: list[float]) -> float:
    return float(np.mean(values)) if values else float("nan")


@dataclass(frozen=True)
class PhraseAnalysis:
    pause_threshold: float
    phrases: list[Phrase]
    ends: list[PhraseEnd]
    onsets: list[Onset]
    n_unmeasurable_ends: int = 0

    @property
    def n_ends(self) -> int:
        return len(self.ends)

    def _count(self, direction: str) -> int:
        return sum(e.direction == direction for e in self.ends)

    @property
    def n_rising(self) -> int:
        return self._count("rising")

    @property
    def n_falling(self) -> int:
        return self._count("falling")

    @property
    def n_level(self) -> int:
        return self._count("level")

    @property
    def hrt_rate(self) -> float:
        return _rate(self.n_rising, self.n_ends)

    @property
    def fall_rate(self) -> float:
        return _rate(self.n_falling, self.n_ends)

    @property
    def level_rate(self) -> float:
        return _rate(self.n_level, self.n_ends)

    @property
    def mean_rise_hz(self) -> float:
        return _mean([e.delta for e in self.ends if e.direction == "rising"])

    @property
    def mean_fall_hz(self) -> float:
        """Average fall magnitude (positive Hz)."""
        return _mean([-e.delta for e in self.ends if e.direction == "falling"])

    def magnitude_counts(self) -> dict[str, int]:
        counts = {f"{d}_{m}": 0 for d in ("rising", "falling") for m in ("big", "mod", "small")}
        for e in self.ends:
            if e.magnitude:
                counts[f"{e.direction}_{e.magnitude}"] += 1
        return counts

    def _onset_rate(self, category: str) -> float:
        return _rate(sum(o.category == category for o in self.onsets), len(self.onsets))

    @property
    def high_onset_rate(self) -> float:
        return self._onset_rate("high")

    @property
    def mid_onset_rate(self) -> float:
        return self._onset_rate("mid")

    @property
    def low_onset_rate(self) -> float:
        return self._onset_rate("low")

    def summary(self) -> dict:
        return {
            "pause_threshold": self.pause_threshold,
            "n_phrases": len(self.phrases),
            "n_ends": self.n_ends,
            "n_unmeasurable_ends": self.n_unmeasurable_ends,
            "n_rising": self.n_rising,
            "n_falling": self.n_falling,
            "n_level": self.n_level,
            "hrt_rate": self.hrt_rate,
            "fall_rate": self.fall_rate,
            "level_rate": self.level_rate,
            "mean_rise_hz": self.mean_rise_hz,
            "mean_fall_hz": self.mean_fall_hz,
            "magnitudes": self.magnitude_counts(),
            "n_onsets": len(self.onsets),
            "high_onset_rate": self.high_onset_rate,
            "mid_onset_rate": self.mid_onset_rate,
            "low_onset_rate": self.low_onset_rate,
        }

    def to_dict(self) -> dict:
        return {
            **self.summary(),
            "ends": [asdict(e) for e in self.ends],
            "onsets": [asdict(o) for o in self.onsets],
        }


@dataclass(frozen=True)
class PhrasingResult:
    primary: PhraseAnalysis
    by_threshold: dict[float, PhraseAnalysis] = field(default_factory=dict)

    @property
    def used_fallback(self) -> bool:
        return self.primary.pause_threshold != PRIMARY_PAUSE

    def to_dict(self) -> dict:
        return {
            "pause_threshold": self.primary.pause_threshold,
            "used_fallback": self.used_fallback,
            "primary": self.primary.to_dict(),
            "by_threshold": {f"{k:.2f}": v.summary() for k, v in self.by_threshold.items()},
        }


def segment_phrases(track: PitchTrack, pause_threshold: float) -> list[Phrase]:
    voiced_idx = np.flatnonzero(track.voiced)
    if len(voiced_idx) == 0:
        return []
    # Gaps between consecutive voiced frames; a gap of g frames hides g - 1 unvoiced frames.
    gaps = np.diff(voiced_idx) - 1
    breaks = np.flatnonzero(gaps * track.hop >= pause_threshold - 1e-9)
    starts = np.concatenate([[voiced_idx[0]], voiced_idx[breaks + 1]])
    ends = np.concatenate([voiced_idx[breaks], [voiced_idx[-1]]])

    phrases = []
    for s, e in zip(starts, ends):
        if track.voiced[s : e + 1].sum() * track.hop >= MIN_PHRASE_VOICED:
            phrases.append(Phrase(float(track.times[s]), float(track.times[e])))
    return phrases


def _voiced_in(track: PitchTrack, t0: float, t1: float, closed: bool = True) -> np.ndarray:
    upper = track.times <= t1 + 1e-9 if closed else track.times < t1 - 1e-9
    mask = (track.times >= t0 - 1e-9) & upper & track.voiced
    return track.f0[mask]


def measure_end(track: PitchTrack, phrase: Phrase) -> PhraseEnd | None:
    """Pitch movement over the last 500 ms: first-third vs last-third median F0."""
    w0 = max(phrase.start, phrase.end - END_WINDOW)
    span = phrase.end - w0
    if span < MIN_END_WINDOW:
        return None
    first = _voiced_in(track, w0, w0 + span / 3)
    last = _voiced_in(track, phrase.end - span / 3, phrase.end)
    if len(first) < 2 or len(last) < 2:
        return None
    # Medians resist the octave jumps and creak that are common at phrase ends.
    start_hz, end_hz = float(np.median(first)), float(np.median(last))
    delta = end_hz - start_hz
    direction, magnitude = classify_delta(delta)
    return PhraseEnd(phrase.end, start_hz, end_hz, delta, direction, magnitude)


def measure_onset(track: PitchTrack, phrase: Phrase, overall_mean: float) -> Onset | None:
    t1 = phrase.start + ONSET_WINDOW
    # Half-open [start, start + 500 ms) unless the phrase ends first.
    f0 = _voiced_in(track, phrase.start, min(t1, phrase.end), closed=t1 >= phrase.end)
    if len(f0) < 5 or not overall_mean > 0:
        return None
    mean_hz = float(np.mean(f0))
    ratio = mean_hz / overall_mean
    return Onset(phrase.start, mean_hz, ratio, classify_onset(ratio))


def analyze_at_threshold(track: PitchTrack, pause_threshold: float) -> PhraseAnalysis:
    phrases = segment_phrases(track, pause_threshold)
    overall_mean = float(np.mean(track.voiced_f0)) if track.voiced.any() else float("nan")
    measured = [measure_end(track, p) for p in phrases]
    ends = [e for e in measured if e is not None]
    onsets = [o for p in phrases if (o := measure_onset(track, p, overall_mean)) is not None]
    return PhraseAnalysis(pause_threshold, phrases, ends, onsets, len(measured) - len(ends))


def analyze_phrasing(
    track: PitchTrack,
    primary: float = PRIMARY_PAUSE,
    fallback: float = FALLBACK_PAUSE,
    min_boundaries: int = MIN_BOUNDARIES,
) -> PhrasingResult:
    results = {t: analyze_at_threshold(track, t) for t in (primary, fallback)}
    chosen = results[primary] if results[primary].n_ends >= min_boundaries else results[fallback]
    return PhrasingResult(primary=chosen, by_threshold=results)
