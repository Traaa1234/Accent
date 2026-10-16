"""Register and variability metrics computed from a PitchTrack."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from accent_analyzer.analysis.pitch import PitchTrack
from accent_analyzer.targets import Status, evaluate


@dataclass(frozen=True)
class RegisterMetrics:
    duration: float
    n_frames: int
    n_voiced: int
    voiced_ratio: float
    mean_f0: float
    median_f0: float
    std_f0: float
    p10_f0: float
    p90_f0: float
    range_ratio: float

    def to_dict(self) -> dict:
        return asdict(self)

    def statuses(self) -> dict[str, Status]:
        return evaluate(self.to_dict())


def register_metrics(track: PitchTrack) -> RegisterMetrics:
    n_frames = len(track)
    voiced = track.voiced_f0
    duration = float(track.times[-1] + track.hop / 2) if n_frames else 0.0
    if len(voiced) == 0:
        nan = float("nan")
        return RegisterMetrics(duration, n_frames, 0, 0.0, nan, nan, nan, nan, nan, nan)

    p10, p90 = np.percentile(voiced, [10, 90])
    return RegisterMetrics(
        duration=duration,
        n_frames=n_frames,
        n_voiced=int(len(voiced)),
        voiced_ratio=float(len(voiced) / n_frames),
        mean_f0=float(np.mean(voiced)),
        median_f0=float(np.median(voiced)),
        std_f0=float(np.std(voiced)),
        p10_f0=float(p10),
        p90_f0=float(p90),
        range_ratio=float(p90 / p10),
    )
