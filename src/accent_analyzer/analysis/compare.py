"""Comparing pitch contours: shadowing (you vs a reference) and A/B (take vs take).

Contours are compared in semitones relative to each speaker's own median pitch,
so a low voice copying a high one is judged on shape, not on register. The two
contours are aligned with dynamic time warping (DTW) on the voiced frames, which
absorbs differences in speaking rate and pause length.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

import numpy as np
from scipy.signal import medfilt

from accent_analyzer.analysis.phrasing import PhraseEnd

STEP = 0.02  # contour resampling step (s)
REFERENCE_F0 = (70.0, 400.0)  # a reference speaker's voice is unknown, so search a wider range
MAX_FRAMES = 1500  # longer contours are decimated before DTW (keeps it fast)
END_MATCH_WINDOW = 0.6  # s: how far an aligned phrase ending may be from the reference's
LEVEL_ST = 0.5  # semitone change treated as level when comparing endings


def semitone_contour(result, step: float = STEP) -> tuple[np.ndarray, np.ndarray]:
    """Voiced frames as (times, semitones re: the speaker's median), resampled to `step`."""
    track = result.track
    voiced = track.voiced
    if voiced.sum() < 5:
        return np.array([]), np.array([])
    median = float(np.median(track.f0[voiced]))
    idx = np.flatnonzero(voiced)
    st = 12 * np.log2(track.f0[idx] / median)
    # A 5-frame median filter removes single-frame octave jumps before alignment.
    st = medfilt(st, kernel_size=5) if len(st) >= 5 else st
    hop = max(1, int(round(step / track.hop)))
    return track.times[idx][::hop], st[::hop]


def _features(st: np.ndarray) -> np.ndarray:
    """DTW features: centred pitch plus its local slope (shape matters more than level)."""
    centred = st - np.median(st)
    slope = np.gradient(centred) * 4
    return np.vstack([centred, slope])


def align(ref_st: np.ndarray, user_st: np.ndarray) -> np.ndarray:
    """DTW warping path as an (n, 2) array of (ref_index, user_index), in time order."""
    import librosa

    _, wp = librosa.sequence.dtw(X=_features(ref_st), Y=_features(user_st), metric="euclidean",
                                 global_constraints=True, band_rad=0.3)
    return wp[::-1]


def _decimate(t: np.ndarray, st: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    if len(st) <= MAX_FRAMES:
        return t, st
    k = math.ceil(len(st) / MAX_FRAMES)
    return t[::k], st[::k]


def _pearson(a: np.ndarray, b: np.ndarray) -> float:
    if len(a) < 3 or np.std(a) < 1e-9 or np.std(b) < 1e-9:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def span_st(st: np.ndarray) -> float:
    """Pitch range in semitones (p10 to p90)."""
    if len(st) < 5:
        return float("nan")
    p10, p90 = np.percentile(st, [10, 90])
    return float(p90 - p10)


def _end_st(end: PhraseEnd) -> float:
    """Phrase-end movement in semitones (comparable across voices)."""
    return 12 * math.log2(end.end_hz / end.start_hz)


def _direction(semitones: float) -> str:
    return "rising" if semitones > LEVEL_ST else "falling" if semitones < -LEVEL_ST else "level"


@dataclass(frozen=True)
class EndingCheck:
    ref_time: float
    ref_direction: str
    ref_semitones: float
    user_time: float | None
    user_direction: str | None
    user_semitones: float | None

    @property
    def agrees(self) -> bool:
        return self.user_direction == self.ref_direction


@dataclass
class ShadowResult:
    contour_match: float  # 0-100: correlation of the aligned contours
    range_match: float  # 0-100: how close your range is to the reference's
    ending_agreement: float | None  # 0-1 share of reference endings you matched in direction
    score: float  # 0-100 overall
    ref_span: float
    user_span: float
    endings: list[EndingCheck] = field(default_factory=list)
    overlay: dict = field(default_factory=dict)  # ref_t, ref_st, user_st (user warped onto ref time)
    tips: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        for k, v in d.items():
            if isinstance(v, float) and math.isnan(v):
                d[k] = None
        return d


def _map_time(path: np.ndarray, ref_t: np.ndarray, user_t: np.ndarray, t: float) -> float:
    """Where in the user's take a reference time lands, via the warping path."""
    i = int(np.argmin(np.abs(ref_t - t)))
    js = path[path[:, 0] == i, 1]
    return float(user_t[int(np.median(js))]) if len(js) else float("nan")


def compare_endings(ref, user, path, ref_t, user_t) -> list[EndingCheck]:
    checks = []
    user_ends = user.phrasing.primary.ends
    for e in ref.phrasing.primary.ends:
        r_st = _end_st(e)
        target = _map_time(path, ref_t, user_t, e.time)
        near = [u for u in user_ends if math.isfinite(target) and abs(u.time - target) <= END_MATCH_WINDOW]
        match = min(near, key=lambda u: abs(u.time - target)) if near else None
        u_st = _end_st(match) if match else None
        checks.append(EndingCheck(
            ref_time=round(e.time, 2), ref_direction=_direction(r_st), ref_semitones=round(r_st, 1),
            user_time=round(match.time, 2) if match else None,
            user_direction=_direction(u_st) if match else None,
            user_semitones=round(u_st, 1) if match else None,
        ))
    return checks


def shadow(reference, user) -> ShadowResult:
    """Score how closely `user` (an AnalysisResult) follows `reference`'s intonation."""
    ref_t, ref_st = _decimate(*semitone_contour(reference))
    user_t, user_st = _decimate(*semitone_contour(user))
    if len(ref_st) < 10 or len(user_st) < 10:
        raise ValueError("Not enough voiced speech in one of the recordings to compare.")
    path = align(ref_st, user_st)
    r, u = ref_st[path[:, 0]], user_st[path[:, 1]]
    contour_match = 100 * max(0.0, _pearson(r, u))
    ref_span, user_span = span_st(ref_st), span_st(user_st)
    range_match = 100 * min(ref_span, user_span) / max(ref_span, user_span) if ref_span > 0 and user_span > 0 else 0.0
    endings = compare_endings(reference, user, path, ref_t, user_t)
    agreement = sum(c.agrees for c in endings) / len(endings) if endings else None
    parts = [(contour_match, 0.6), (range_match, 0.2)] + ([(100 * agreement, 0.2)] if agreement is not None else [])
    score = sum(v * w for v, w in parts) / sum(w for _, w in parts)

    # Overlay: the user's pitch at each reference frame (mean over the frames DTW mapped there).
    warped = np.full(len(ref_st), np.nan)
    for i in range(len(ref_st)):
        js = path[path[:, 0] == i, 1]
        if len(js):
            warped[i] = float(np.mean(user_st[js]))
    overlay = {
        "ref_t": [round(float(x), 2) for x in ref_t],
        "ref_st": [round(float(x), 2) for x in ref_st],
        "user_st": [None if np.isnan(x) else round(float(x), 2) for x in warped],
    }

    tips = []
    if user_span < 0.7 * ref_span:
        tips.append(f"Your range was {user_span:.1f} semitones against the reference's {ref_span:.1f}: "
                    "exaggerate the highs and lows more.")
    for c in endings:
        if c.user_direction is None:
            continue
        if c.ref_direction == "falling" and c.user_direction != "falling":
            tips.append(f"At {c.ref_time:.1f}s the reference falls ({c.ref_semitones:+.1f} st) but you went "
                        f"{c.user_direction} ({c.user_semitones:+.1f} st). Drop your pitch on that last word.")
    if contour_match < 50:
        tips.append("The overall shape differs a lot. Listen once more and copy one phrase at a time.")
    if not tips:
        tips.append("Close match. Try a faster or more animated reference next.")
    return ShadowResult(round(contour_match, 1), round(range_match, 1),
                        None if agreement is None else round(agreement, 3), round(score, 1),
                        round(ref_span, 2), round(user_span, 2), endings, overlay, tips)


# ------------------------------------------------------------------------------------
# A/B contrast

@dataclass
class TakeProfile:
    final_direction: str | None
    final_semitones: float | None
    final_time: float | None
    fall_share: float | None
    span: float
    onset_ratio: float | None
    score: float  # 0-1, higher = more American-sounding intonation

    def to_dict(self) -> dict:
        return {k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in asdict(self).items()}


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def profile(result) -> TakeProfile:
    p = result.phrasing.primary
    _, st = semitone_contour(result)
    span = span_st(st)
    final = p.ends[-1] if p.ends else None
    final_st = _end_st(final) if final else None
    final_dir = _direction(final_st) if final else None
    dirs = [_direction(_end_st(e)) for e in p.ends]
    fall_share = dirs.count("falling") / len(dirs) if dirs else None
    onset = p.onsets[0].ratio if p.onsets else None
    parts = [
        ({"falling": 1.0, "level": 0.4, "rising": 0.0}.get(final_dir, 0.5), 0.35),
        (fall_share if fall_share is not None else 0.5, 0.25),
        (_clamp((span - 3) / 6) if math.isfinite(span) else 0.0, 0.2),
        (_clamp((onset - 0.9) / 0.25) if onset else 0.5, 0.2),
    ]
    return TakeProfile(final_dir, None if final_st is None else round(final_st, 1),
                       None if final is None else round(final.time, 2),
                       None if fall_share is None else round(fall_share, 3),
                       round(span, 2) if math.isfinite(span) else float("nan"),
                       None if onset is None else round(onset, 3),
                       round(sum(v * w for v, w in parts), 3))


@dataclass
class ABResult:
    a: TakeProfile
    b: TakeProfile
    winner: str | None  # "A", "B" or None (too close to call)
    reasons: list[str]
    overlay: dict

    def to_dict(self) -> dict:
        return {"a": self.a.to_dict(), "b": self.b.to_dict(), "winner": self.winner,
                "reasons": self.reasons, "overlay": self.overlay}


CLOSE_CALL = 0.05


def _ending_text(p: TakeProfile) -> str:
    if not p.final_direction:
        return "has no measurable ending"
    return f"ends {p.final_direction} ({p.final_semitones:+.1f} semitones at {p.final_time:.1f}s)"


def compare_takes(a, b) -> ABResult:
    """Which of two takes of the same sentence sounds more American, and why."""
    takes = {"A": profile(a), "B": profile(b)}
    diff = takes["B"].score - takes["A"].score
    winner = None if abs(diff) < CLOSE_CALL else ("B" if diff > 0 else "A")
    lead = winner or "B"
    other = "A" if lead == "B" else "B"
    w, l = takes[lead], takes[other]
    reasons = []

    rank = {"falling": 2, "level": 1, "rising": 0, None: -1}
    if w.final_direction != l.final_direction:
        # Name the better ending first, whichever take won overall.
        good, poor = (lead, other) if rank[w.final_direction] > rank[l.final_direction] else (other, lead)
        reasons.append(f"Take {good} {_ending_text(takes[good])}; take {poor} {_ending_text(takes[poor])}. "
                       "American statements end with a fall.")
    elif (w.final_direction == l.final_direction == "falling"
          and abs(w.final_semitones - l.final_semitones) >= 1):
        deep, shallow = ("A", "B") if takes["A"].final_semitones < takes["B"].final_semitones else ("B", "A")
        reasons.append(f"Both end falling; take {deep} falls further "
                       f"({takes[deep].final_semitones:+.1f} vs {takes[shallow].final_semitones:+.1f} semitones).")
    pa, pb = takes["A"], takes["B"]
    if math.isfinite(pa.span) and math.isfinite(pb.span) and abs(pa.span - pb.span) >= 1:
        wide, narrow = ("A", "B") if pa.span > pb.span else ("B", "A")
        reasons.append(f"Take {wide} uses a wider pitch range: {takes[wide].span:.1f} vs "
                       f"{takes[narrow].span:.1f} semitones.")
    if pa.onset_ratio and pb.onset_ratio and abs(pa.onset_ratio - pb.onset_ratio) >= 0.08:
        high, low = ("A", "B") if pa.onset_ratio > pb.onset_ratio else ("B", "A")
        reasons.append(f"Take {high} starts higher: {takes[high].onset_ratio:.2f}× vs "
                       f"{takes[low].onset_ratio:.2f}× its mean pitch.")
    if winner is None:
        reasons.insert(0, "Too close to call: the two takes have very similar intonation.")
    elif not reasons:
        reasons.append(f"Take {winner} scores slightly higher overall on endings, range and onset.")

    # Overlay both takes on A's timeline.
    ta, sa = _decimate(*semitone_contour(a))
    tb, sb = _decimate(*semitone_contour(b))
    overlay = {"t": [], "a_st": [], "b_st": []}
    if len(sa) >= 10 and len(sb) >= 10:
        path = align(sa, sb)
        warped = np.full(len(sa), np.nan)
        for i in range(len(sa)):
            js = path[path[:, 0] == i, 1]
            if len(js):
                warped[i] = float(np.mean(sb[js]))
        overlay = {
            "t": [round(float(x), 2) for x in ta],
            "a_st": [round(float(x), 2) for x in sa],
            "b_st": [None if np.isnan(x) else round(float(x), 2) for x in warped],
        }
    return ABResult(takes["A"], takes["B"], winner, reasons, overlay)
