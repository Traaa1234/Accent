"""Target ranges for native General American English, shared by metrics, reports and coaching."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Status(str, Enum):
    ON_TARGET = "on_target"
    BELOW = "below"
    ABOVE = "above"


@dataclass(frozen=True)
class TargetRange:
    low: float | None
    high: float | None
    unit: str = ""
    description: str = ""

    def status(self, value: float) -> Status:
        if self.low is not None and value < self.low:
            return Status.BELOW
        if self.high is not None and value > self.high:
            return Status.ABOVE
        return Status.ON_TARGET

    def label(self) -> str:
        if self.low is not None and self.high is not None:
            return f"{self.low:g}–{self.high:g}{self.unit}"
        if self.low is not None:
            return f"≥ {self.low:g}{self.unit}"
        return f"≤ {self.high:g}{self.unit}"


TARGETS: dict[str, TargetRange] = {
    "range_ratio": TargetRange(2.5, 4.0, "×", "p90/p10 F0 ratio"),
    "std_f0": TargetRange(60.0, None, " Hz", "F0 standard deviation"),
    "voiced_ratio": TargetRange(0.60, 0.80, "", "share of frames with detectable F0"),
}
