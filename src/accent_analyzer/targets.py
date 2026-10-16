"""Target ranges for native General American English, shared by metrics, reports and coaching."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum


class Status(str, Enum):
    ON_TARGET = "on_target"
    BELOW = "below"
    ABOVE = "above"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class TargetRange:
    low: float | None
    high: float | None
    unit: str = ""
    description: str = ""
    percent: bool = False  # value is a 0-1 fraction, displayed as %

    def status(self, value: float) -> Status:
        if value is None or math.isnan(value):
            return Status.UNKNOWN
        if self.low is not None and value < self.low:
            return Status.BELOW
        if self.high is not None and value > self.high:
            return Status.ABOVE
        return Status.ON_TARGET

    def _fmt(self, v: float) -> str:
        return f"{v * 100:g}" if self.percent else f"{v:g}"

    def label(self) -> str:
        unit = "%" if self.percent else self.unit
        if self.low is not None and self.high is not None:
            return f"{self._fmt(self.low)}–{self._fmt(self.high)}{unit}"
        if self.low is not None:
            return f"≥ {self._fmt(self.low)}{unit}"
        return f"≤ {self._fmt(self.high)}{unit}"


TARGETS: dict[str, TargetRange] = {
    # Register & variability
    "range_ratio": TargetRange(2.5, 4.0, "×", "p90/p10 F0 ratio"),
    "std_f0": TargetRange(60.0, None, " Hz", "F0 standard deviation"),
    "voiced_ratio": TargetRange(0.60, 0.80, description="frames with detectable F0", percent=True),
    # Phrase endings and onsets
    "hrt_rate": TargetRange(None, 0.25, description="phrase endings that rise", percent=True),
    "high_onset_rate": TargetRange(0.40, None, description="phrases launched high", percent=True),
    "low_onset_rate": TargetRange(None, 0.20, description="phrases launched low", percent=True),
    # 3-second window movement
    "window_falling_rate": TargetRange(0.50, 0.65, description="3 s windows falling", percent=True),
    "window_level_rate": TargetRange(0.25, 0.35, description="3 s windows level", percent=True),
    "window_rising_rate": TargetRange(0.10, 0.20, description="3 s windows rising", percent=True),
}


def evaluate(values: dict[str, float]) -> dict[str, Status]:
    """Status of every value that has a target."""
    return {k: TARGETS[k].status(v) for k, v in values.items() if k in TARGETS}
