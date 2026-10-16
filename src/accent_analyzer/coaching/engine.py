"""Recommendation engine: which coaching modules to work on, in what order.

Measured problems come first, ranked by how far past its trigger threshold the
worst metric is. Modules triggered only by accent background follow, ordered by
the library's priority. Rising HRT on a recording with too few phrase endings is
still recommended but marked provisional.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from accent_analyzer.analysis.interpret import MIN_RELIABLE_ENDS
from accent_analyzer.coaching.library import ACCENT_NAMES, Module, load_library
from accent_analyzer.reports.verdict import format_value
from accent_analyzer.targets import TARGETS, Status

DEFAULT_LIMIT = 4
_LABELS = {
    "hrt_rate": "HRT", "range_ratio": "range ratio", "std_f0": "pitch std dev",
    "high_onset_rate": "HIGH onsets", "low_onset_rate": "LOW onsets", "voiced_ratio": "voiced ratio",
    "fall_rate": "falling endings",
}
_PHRASE_METRICS = {"hrt_rate", "fall_rate", "high_onset_rate", "low_onset_rate"}


@dataclass(frozen=True)
class Recommendation:
    module: Module
    score: float
    source: str  # "measured" | "accent"
    reasons: tuple[str, ...]
    provisional: bool = False
    progress: tuple[dict, ...] = field(default=())

    @property
    def why(self) -> str:
        reasons = "; ".join(self.reasons)
        tail = " Provisional: fewer than 10 phrase endings were measurable." if self.provisional else ""
        return f"{self.module.description} Triggered by: {reasons}.{tail}"

    def to_report_dict(self) -> dict:
        m = self.module
        return {
            "id": m.id,
            "title": m.name,
            "why": self.why,
            "target": m.target,
            "detection": m.detection,
            "drills": [{"name": d.name, "minutes": d.minutes, "steps": list(d.steps)} for d in m.drills],
            "examples": list(m.examples),
            "words": list(m.words),
            "progress": [_progress_text(p) for p in self.progress],
        }

    def to_dict(self) -> dict:
        m = self.module
        return {
            "id": m.id,
            "name": m.name,
            "score": round(self.score, 3),
            "source": self.source,
            "provisional": self.provisional,
            "detection": m.detection,
            "reasons": list(self.reasons),
            "description": m.description,
            "target": m.target,
            "drills": [{"name": d.name, "minutes": d.minutes, "steps": list(d.steps)} for d in m.drills],
            "examples": list(m.examples),
            "words": list(m.words),
            "progress": list(self.progress),
        }


def _progress_text(p: dict) -> str:
    if not p.get("current"):
        return p["text"]
    met = " ✓ met" if p.get("on_target") else ""
    return f"{p['text']} (now {p['current']}{met})"


def _progress(module: Module, metrics: dict, history: list[dict] | None) -> tuple[dict, ...]:
    """Each indicator with the current value and, given history, previous and best."""
    out = []
    for p in module.progress:
        row = {"text": p.text, "metric": p.metric}
        if p.metric and p.metric in metrics:
            v = metrics[p.metric]
            row["current"] = format_value(p.metric, v)
            target = TARGETS.get(p.metric)
            if target:
                row["on_target"] = target.status(v) is Status.ON_TARGET
            if history:
                past = [h.get(p.metric) for h in history[:-1]]
                past = [x for x in past if x is not None and not (isinstance(x, float) and math.isnan(x))]
                if past:
                    row["previous"] = format_value(p.metric, past[-1])
                    lower_better = target is not None and target.high is not None and target.low is None
                    row["best"] = format_value(p.metric, min(past + [v]) if lower_better else max(past + [v]))
        out.append(row)
    return tuple(out)


def recommend(
    metrics: dict,
    accent: str | None = None,
    focus: str | None = None,
    limit: int | None = DEFAULT_LIMIT,
    history: list[dict] | None = None,
) -> list[Recommendation]:
    """Rank coaching modules for one recording's flat metrics (AnalysisResult.metrics())."""
    library = load_library()
    if focus and focus not in library:
        raise KeyError(f"Unknown module {focus!r}; choose from {', '.join(library)}")
    recs = []
    for module in library.values():
        fired = [t for t in module.metric_triggers if t.matches_metric(metrics)]
        if fired:
            reasons = tuple(
                f"{_LABELS.get(t.metric, t.metric)} {format_value(t.metric, metrics[t.metric])} "
                f"(trigger {t.op} {format_value(t.metric, t.value)})"
                for t in fired
            )
            provisional = (
                any(t.metric in _PHRASE_METRICS for t in fired)
                and metrics.get("n_phrase_ends", MIN_RELIABLE_ENDS) < MIN_RELIABLE_ENDS
            )
            score = 1.0 + max(t.miss(metrics) for t in fired) - (0.5 if provisional else 0.0)
            recs.append(Recommendation(module, score, "measured", reasons, provisional,
                                       _progress(module, metrics, history)))
        elif accent and any(accent in t.accents for t in module.accent_triggers):
            reason = f"your {ACCENT_NAMES.get(accent, accent)} background"
            if module.detection == "planned":
                reason += " (detection from audio is planned for v2)"
            recs.append(Recommendation(module, 0.5 - module.priority / 100, "accent", (reason,),
                                       progress=_progress(module, metrics, history)))
        elif focus == module.id:
            recs.append(Recommendation(module, 0.0, "requested", ("you asked to focus on it",),
                                       progress=_progress(module, metrics, history)))
    recs.sort(key=lambda r: (-r.score, r.module.priority))
    if focus:
        recs = [r for r in recs if r.module.id == focus]
    return recs[:limit] if limit else recs
