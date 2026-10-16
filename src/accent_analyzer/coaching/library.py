"""Load and validate the coaching content library (modules.toml)."""

from __future__ import annotations

import math
import operator
import tomllib
from dataclasses import dataclass, field
from functools import cache
from importlib import resources
from typing import Literal

ACCENTS = ("nze", "aue", "british", "indian", "other")
ACCENT_NAMES = {
    "nze": "New Zealand English",
    "aue": "Australian English",
    "british": "British English",
    "indian": "Indian English",
    "other": "another variety",
}
Detection = Literal["acoustic", "planned", "self_reported"]

_OPS = {"<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge}


@dataclass(frozen=True)
class Trigger:
    metric: str | None = None
    op: str | None = None
    value: float | None = None
    accents: tuple[str, ...] = ()

    @property
    def is_metric(self) -> bool:
        return self.metric is not None

    def matches_metric(self, metrics: dict) -> bool:
        v = metrics.get(self.metric)
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return False
        return _OPS[self.op](v, self.value)

    def miss(self, metrics: dict) -> float:
        """Relative distance past the threshold (how badly the trigger fires)."""
        v = metrics[self.metric]
        scale = max(abs(self.value), 1e-6)
        return abs(v - self.value) / scale

    def describe(self) -> str:
        if self.is_metric:
            return f"{self.metric} {self.op} {self.value:g}"
        return "accent: " + ", ".join(self.accents)


@dataclass(frozen=True)
class Drill:
    name: str
    steps: tuple[str, ...]
    minutes: int = 0


@dataclass(frozen=True)
class ProgressIndicator:
    text: str
    metric: str | None = None


@dataclass(frozen=True)
class Module:
    id: str
    name: str
    priority: int
    detection: Detection
    description: str
    target: str
    triggers: tuple[Trigger, ...]
    markers: tuple[str, ...] = ()
    drills: tuple[Drill, ...] = ()
    examples: tuple[str, ...] = ()
    words: tuple[str, ...] = ()
    progress: tuple[ProgressIndicator, ...] = field(default=())

    @property
    def metric_triggers(self) -> tuple[Trigger, ...]:
        return tuple(t for t in self.triggers if t.is_metric)

    @property
    def accent_triggers(self) -> tuple[Trigger, ...]:
        return tuple(t for t in self.triggers if not t.is_metric)


class LibraryError(ValueError):
    pass


def _module(raw: dict) -> Module:
    try:
        triggers = []
        for t in raw["triggers"]:
            if "metric" in t:
                if t["op"] not in _OPS:
                    raise LibraryError(f"{raw['id']}: unknown operator {t['op']!r}")
                triggers.append(Trigger(t["metric"], t["op"], float(t["value"])))
            else:
                bad = set(t["accents"]) - set(ACCENTS)
                if bad:
                    raise LibraryError(f"{raw['id']}: unknown accents {sorted(bad)}")
                triggers.append(Trigger(accents=tuple(t["accents"])))
        return Module(
            id=raw["id"],
            name=raw["name"],
            priority=int(raw["priority"]),
            detection=raw["detection"],
            description=" ".join(raw["description"].split()),
            target=raw["target"],
            triggers=tuple(triggers),
            markers=tuple(raw.get("markers", ())),
            drills=tuple(Drill(d["name"], tuple(d["steps"]), int(d.get("minutes", 0))) for d in raw.get("drills", ())),
            examples=tuple(raw.get("examples", ())),
            words=tuple(raw.get("words", ())),
            progress=tuple(ProgressIndicator(p["text"], p.get("metric")) for p in raw.get("progress", ())),
        )
    except KeyError as exc:
        raise LibraryError(f"module {raw.get('id', '?')}: missing field {exc}") from exc


def parse_library(text: str) -> dict[str, Module]:
    modules = [_module(m) for m in tomllib.loads(text)["module"]]
    ids = [m.id for m in modules]
    if len(ids) != len(set(ids)):
        raise LibraryError(f"duplicate module ids in {ids}")
    for m in modules:
        if m.detection not in ("acoustic", "planned", "self_reported"):
            raise LibraryError(f"{m.id}: unknown detection {m.detection!r}")
    return {m.id: m for m in modules}


@cache
def load_library() -> dict[str, Module]:
    text = resources.files("accent_analyzer.coaching").joinpath("modules.toml").read_text(encoding="utf-8")
    return parse_library(text)
