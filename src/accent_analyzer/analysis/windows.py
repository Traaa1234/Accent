"""3-second sliding-window pitch movement.

Each window fits a least-squares line through its voiced F0 points and is
classified by slope: rising (> +5 Hz/s), falling (< -5 Hz/s) or level.
Windows with too little voicing are skipped.

When phrases are supplied (the default in the pipeline), the line is fitted
with a shared slope but a separate intercept per phrase. Otherwise a window
straddling a pause would read the pitch reset between phrases (low end of one,
high start of the next) as a rise, and the metric would mostly count resets.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

import numpy as np

from accent_analyzer.analysis.phrasing import Phrase
from accent_analyzer.analysis.pitch import PitchTrack

WINDOW_SEC = 3.0
HOP_SEC = 1.0
SLOPE_HZ_PER_S = 5.0
MIN_VOICED_FRACTION = 0.3

WindowDirection = Literal["rising", "falling", "level"]


@dataclass(frozen=True)
class PitchWindow:
    start: float
    slope: float  # Hz/s
    n_voiced: int
    direction: WindowDirection


def classify_slope(slope: float) -> WindowDirection:
    if slope > SLOPE_HZ_PER_S:
        return "rising"
    if slope < -SLOPE_HZ_PER_S:
        return "falling"
    return "level"


@dataclass(frozen=True)
class WindowAnalysis:
    windows: list[PitchWindow]
    window_sec: float = WINDOW_SEC
    hop_sec: float = HOP_SEC
    within_phrase: bool = False

    def _rate(self, direction: str) -> float:
        if not self.windows:
            return float("nan")
        return sum(w.direction == direction for w in self.windows) / len(self.windows)

    @property
    def rising_rate(self) -> float:
        return self._rate("rising")

    @property
    def falling_rate(self) -> float:
        return self._rate("falling")

    @property
    def level_rate(self) -> float:
        return self._rate("level")

    def summary(self) -> dict:
        return {
            "n_windows": len(self.windows),
            "within_phrase": self.within_phrase,
            "window_rising_rate": self.rising_rate,
            "window_falling_rate": self.falling_rate,
            "window_level_rate": self.level_rate,
        }

    def to_dict(self) -> dict:
        return {**self.summary(), "windows": [asdict(w) for w in self.windows]}


def pooled_slope(t: np.ndarray, f0: np.ndarray, groups: np.ndarray) -> float:
    """Least-squares slope shared across groups, each group with its own intercept."""
    sxy = sxx = 0.0
    for g in np.unique(groups):
        m = groups == g
        if m.sum() < 3:
            continue
        dt = t[m] - t[m].mean()
        sxy += float(np.dot(dt, f0[m] - f0[m].mean()))
        sxx += float(np.dot(dt, dt))
    return sxy / sxx if sxx > 1e-9 else float("nan")


def _phrase_ids(track: PitchTrack, phrases: list[Phrase]) -> np.ndarray:
    ids = np.full(len(track), -1)
    for i, p in enumerate(phrases):
        ids[(track.times >= p.start - 1e-9) & (track.times <= p.end + 1e-9)] = i
    return ids


def analyze_windows(
    track: PitchTrack,
    phrases: list[Phrase] | None = None,
    window_sec: float = WINDOW_SEC,
    hop_sec: float = HOP_SEC,
    min_voiced_fraction: float = MIN_VOICED_FRACTION,
) -> WindowAnalysis:
    within = phrases is not None
    windows: list[PitchWindow] = []
    if len(track) == 0:
        return WindowAnalysis(windows, window_sec, hop_sec, within)
    ids = _phrase_ids(track, phrases) if within else np.zeros(len(track), dtype=int)
    usable = track.voiced & (ids >= 0)
    frames_per_window = window_sec / track.hop
    t_first, t_last = track.times[0], track.times[-1]
    start = t_first
    while start + window_sec <= t_last + track.hop / 2:
        mask = (track.times >= start) & (track.times < start + window_sec) & usable
        n = int(mask.sum())
        if n >= max(3, min_voiced_fraction * frames_per_window):
            slope = pooled_slope(track.times[mask], track.f0[mask], ids[mask])
            if not np.isnan(slope):
                windows.append(PitchWindow(float(start), slope, n, classify_slope(slope)))
        start += hop_sec
    return WindowAnalysis(windows, window_sec, hop_sec, within)
