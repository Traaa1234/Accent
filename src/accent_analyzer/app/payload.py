"""JSON payloads the app front end renders. Built once per analysis and cached on disk."""

from __future__ import annotations

import math

from accent_analyzer.analysis.phrasing import HIGH_ONSET, LOW_ONSET
from accent_analyzer.coaching import recommend
from accent_analyzer.reports.verdict import headline, own_findings, scorecard


def _num(v, digits: int = 3):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return round(float(v), digits)


def result_payload(result, record, progress: list, history: list[dict] | None = None) -> dict:
    """Everything the Results screen shows for one recording."""
    track = result.track
    voiced = track.voiced
    p = result.phrasing.primary
    mean = result.register.mean_f0
    recs = recommend(result.metrics(), accent=record.accent, history=history, limit=3)
    phrase_starts = [ph.start for ph in p.phrases]

    def phrase_start_before(t: float) -> float:
        earlier = [s for s in phrase_starts if s <= t]
        return earlier[-1] if earlier else 0.0

    return {
        "id": record.id,
        "label": record.label,
        "date": record.recorded_at.isoformat(timespec="minutes"),
        "duration": _num(result.duration, 1),
        "register": result.register_label,
        "accent": record.accent,
        "pitch_method": track.method,
        "headline": headline(result),
        "scorecard": [
            {"key": r.key, "label": r.label, "axis": r.axis, "value": r.value, "target": r.target,
             "status": r.status.value, "status_text": r.status_text}
            for r in scorecard(result)
        ],
        "metrics": {k: _num(v) for k, v in result.metrics().items()},
        "contour": {
            "t": [round(float(t), 2) for t in track.times[voiced]],
            "f0": [round(float(f), 1) for f in track.f0[voiced]],
            "mean": _num(mean, 1),
            "high": _num(mean * HIGH_ONSET, 1) if _num(mean) else None,
            "low": _num(mean * LOW_ONSET, 1) if _num(mean) else None,
        },
        "ends": [
            {"time": _num(e.time, 2), "start_hz": _num(e.start_hz, 1), "end_hz": _num(e.end_hz, 1),
             "delta": _num(e.delta, 1), "direction": e.direction, "magnitude": e.magnitude,
             # Playback window: from the start of the phrase (at most 2.5 s back) to just after it ends.
             "play_from": _num(max(phrase_start_before(e.time), e.time - 2.5), 2),
             "play_to": _num(e.time + 0.3, 2)}
            for e in p.ends
        ],
        "phrasing": {
            "pause_threshold": p.pause_threshold,
            "used_fallback": result.phrasing.used_fallback,
            "n_ends": p.n_ends,
            "by_threshold": {f"{t:.2f}": {"n_ends": a.n_ends, "hrt_rate": _num(a.hrt_rate)}
                             for t, a in result.phrasing.by_threshold.items()},
            "onsets": {"high": _num(p.high_onset_rate), "mid": _num(p.mid_onset_rate), "low": _num(p.low_onset_rate)},
        },
        "windows": {
            "n": len(result.windows.windows),
            "falling": _num(result.windows.falling_rate),
            "level": _num(result.windows.level_rate),
            "rising": _num(result.windows.rising_rate),
        },
        "findings": [f.to_dict() for f in own_findings(result, progress)],
        "progress": [f.to_dict() for f in progress],
        "recommendations": [r.to_dict() for r in recs],
    }


def metrics_only_payload(record, progress: list) -> dict:
    """For recordings added from the command line, whose audio the app doesn't have."""
    return {
        "id": record.id,
        "label": record.label,
        "date": record.recorded_at.isoformat(timespec="minutes"),
        "duration": _num(record.duration, 1),
        "register": record.register_label,
        "accent": record.accent,
        "metrics": {k: _num(record.get(k)) for k in record.metrics},
        "progress": [f.to_dict() for f in progress],
        "metrics_only": True,
    }
