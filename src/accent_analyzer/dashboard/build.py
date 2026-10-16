"""Comparative dashboard across all recordings in the history.

Python computes every derived number (radar scores, best-ever benchmark,
deflation runs, flags) so it is testable; the embedded JS only draws.
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from importlib import resources
from pathlib import Path

from accent_analyzer.analysis.interpret import MIN_RELIABLE_ENDS
from accent_analyzer.history.progression import DEFLATION_HZ, DEFLATION_MIN_RECORDINGS, progression
from accent_analyzer.history.store import Record
from accent_analyzer.targets import TARGETS

TABLE_METRICS = (
    "hrt_rate", "fall_rate", "mean_f0", "std_f0", "range_ratio", "voiced_ratio",
    "high_onset_rate", "low_onset_rate", "n_phrase_ends",
)


def _ok(v) -> bool:
    return v is not None and not (isinstance(v, float) and math.isnan(v))


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


# Each radar axis maps a metric to 0..1, where 1 means "at or beyond the target".
RADAR_AXES = (
    ("hrt", "Falling statements", "hrt_rate", lambda v: _clamp((0.75 - v) / 0.50)),       # 25% -> 1, 75% -> 0
    ("falls", "Falls share", "fall_rate", lambda v: _clamp(v / 0.75)),
    ("onsets", "High onsets", "high_onset_rate", lambda v: _clamp(v / 0.40)),
    ("range", "Pitch range", "range_ratio", lambda v: _clamp((v - 1.0) / 1.5)),           # 2.5x -> 1
    ("std", "Variability", "std_f0", lambda v: _clamp(v / 60.0)),
    ("flow", "Flow", "voiced_ratio",
     lambda v: 1.0 if 0.6 <= v <= 0.8 else _clamp(1 - (0.6 - v) / 0.3) if v < 0.6 else _clamp(1 - (v - 0.8) / 0.2)),
)


def radar_scores(metrics: dict) -> dict[str, float | None]:
    return {
        key: (round(fn(metrics[m]), 3) if _ok(metrics.get(m)) else None)
        for key, _, m, fn in RADAR_AXES
    }


def overall_score(metrics: dict) -> float:
    """Mean radar score; missing axes count as 0."""
    scores = radar_scores(metrics)
    return sum(v or 0.0 for v in scores.values()) / len(scores)


def best_index(records: list[Record]) -> int | None:
    """Best-ever benchmark: highest overall score, preferring reliable recordings."""
    if not records:
        return None
    reliable = [i for i, r in enumerate(records) if (r.metrics.get("n_phrase_ends") or 0) >= MIN_RELIABLE_ENDS]
    pool = reliable or list(range(len(records)))
    return max(pool, key=lambda i: (overall_score(records[i].metrics), i))


def deflation_runs(f0: list[float | None]) -> list[dict]:
    """Every maximal run of strictly falling mean F0 spanning 3+ recordings and > 30 Hz."""
    runs, start = [], 0
    for i in range(1, len(f0) + 1):
        falling = i < len(f0) and _ok(f0[i]) and _ok(f0[i - 1]) and f0[i] < f0[i - 1]
        if not falling:
            if i - start >= DEFLATION_MIN_RECORDINGS and f0[start] - f0[i - 1] > DEFLATION_HZ:
                runs.append({"start": start, "end": i - 1, "drop": round(f0[start] - f0[i - 1], 1)})
            start = i
    return runs


def _clean(v):
    return None if isinstance(v, float) and math.isnan(v) else v


def dashboard_data(records: list[Record]) -> dict:
    rows = []
    for r in records:
        rows.append({
            "id": r.id,
            "label": r.label,
            "date": r.recorded_at.isoformat(timespec="minutes"),
            "session": r.session,
            "take": r.take,
            "duration": round(r.duration or 0, 1),
            "register": r.register_label,
            "accent": r.accent,
            "metrics": {k: _clean(r.metrics.get(k)) for k in TABLE_METRICS},
            "radar": radar_scores(r.metrics),
            "score": round(overall_score(r.metrics), 3),
        })
    best = best_index(records)
    return {
        "generated": datetime.now().isoformat(timespec="minutes"),
        "records": rows,
        "best": best,
        "deflation": deflation_runs([r.metrics.get("mean_f0") for r in records]),
        "flags": [f.to_dict() for f in progression(records)],
        "radarAxes": [
            {"key": key, "label": label, "metric": m,
             "target": TARGETS[m].label() if m in TARGETS else ""}
            for key, label, m, _ in RADAR_AXES
        ],
        "targets": {
            k: {"low": t.low, "high": t.high, "label": t.label()}
            for k, t in TARGETS.items() if k in TABLE_METRICS
        },
        "registers": {"calm": 160, "animated": 180},
    }


def _json_for_script(data: dict) -> str:
    # Safe inside <script>: no "</script>", no HTML comment openers, no U+2028/9 line breaks.
    text = json.dumps(data, ensure_ascii=False)
    return (text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def render_dashboard(records: list[Record]) -> str:
    template = resources.files("accent_analyzer.dashboard").joinpath("template.html").read_text(encoding="utf-8")
    return template.replace("/*__DATA__*/null", _json_for_script(dashboard_data(records)))


def write_dashboard(records: list[Record], path: str | Path) -> Path:
    path = Path(path)
    path.write_text(render_dashboard(records), encoding="utf-8")
    return path
