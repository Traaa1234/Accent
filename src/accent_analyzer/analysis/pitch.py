"""F0 (pitch) extraction.

The default tracker is a frame-wise autocorrelation method:

* 40 ms Hann-windowed frames, 10 ms hop
* search lags corresponding to [f0_min, f0_max] (default 80-320 Hz)
* a frame is voiced when the best autocorrelation peak / zero-lag value
  exceeds `confidence_threshold` (default 0.3) and the frame is not silent
* F0 = 0 marks an unvoiced frame

`method="yin"` uses librosa's probabilistic YIN (pYIN), which is slower but
more robust to octave errors. CREPE is reserved for a later version.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np

PitchMethod = Literal["autocorr", "yin", "crepe"]

FRAME_SEC = 0.040
HOP_SEC = 0.010
DEFAULT_F0_MIN = 80.0
DEFAULT_F0_MAX = 320.0
DEFAULT_CONFIDENCE = 0.3
# Frames quieter than this (dB relative to the loudest frame) are treated as silence.
DEFAULT_SILENCE_DB = -40.0
_CHUNK_FRAMES = 4096


@dataclass(frozen=True)
class PitchTrack:
    """F0 values (Hz, 0 = unvoiced) with frame-centre timestamps (s)."""

    f0: np.ndarray
    times: np.ndarray
    confidence: np.ndarray
    hop: float = HOP_SEC
    method: str = "autocorr"
    params: dict = field(default_factory=dict)

    @property
    def voiced(self) -> np.ndarray:
        return self.f0 > 0

    @property
    def voiced_f0(self) -> np.ndarray:
        return self.f0[self.voiced]

    def __len__(self) -> int:
        return len(self.f0)


def _frame(samples: np.ndarray, frame_len: int, hop_len: int) -> np.ndarray:
    if len(samples) < frame_len:
        samples = np.pad(samples, (0, frame_len - len(samples)))
    n_frames = 1 + (len(samples) - frame_len) // hop_len
    # Strided view with the hop built in. (sliding_window_view(...)[::hop] first creates a
    # view of every 1-sample shift, whose nominal size overflows 32-bit memory in the browser.)
    samples = np.ascontiguousarray(samples)
    step = samples.strides[0]
    return np.lib.stride_tricks.as_strided(samples, shape=(n_frames, frame_len),
                                           strides=(hop_len * step, step), writeable=False)


def _parabolic_offset(y_prev: np.ndarray, y0: np.ndarray, y_next: np.ndarray) -> np.ndarray:
    """Sub-sample peak offset in [-0.5, 0.5] from a parabola through three points."""
    denom = y_prev - 2 * y0 + y_next
    with np.errstate(divide="ignore", invalid="ignore"):
        offset = np.where(np.abs(denom) > 1e-12, 0.5 * (y_prev - y_next) / denom, 0.0)
    return np.clip(offset, -0.5, 0.5)


def _autocorr_chunk(
    frames: np.ndarray, window: np.ndarray, min_lag: int, max_lag: int
) -> tuple[np.ndarray, np.ndarray]:
    """Return (best lag in samples, confidence) for each frame in the chunk."""
    x = frames - frames.mean(axis=1, keepdims=True)
    x = x * window
    nfft = 1 << int(np.ceil(np.log2(2 * x.shape[1])))
    spec = np.fft.rfft(x, n=nfft, axis=1)
    ac = np.fft.irfft(spec * np.conj(spec), n=nfft, axis=1)[:, : max_lag + 2]

    r0 = ac[:, 0]
    with np.errstate(divide="ignore", invalid="ignore"):
        norm = np.where(r0[:, None] > 1e-12, ac / r0[:, None], 0.0)

    # Only accept true local maxima inside the lag search range, so a curve that
    # is still decaying at min_lag (high-frequency energy) is not mistaken for a peak.
    lags = np.arange(min_lag, max_lag + 1)
    centre = norm[:, lags]
    is_peak = (centre >= norm[:, lags - 1]) & (centre >= norm[:, lags + 1])
    candidates = np.where(is_peak, centre, -np.inf)
    best_idx = np.argmax(candidates, axis=1)
    rows = np.arange(len(norm))
    best_lag = lags[best_idx]
    best_val = candidates[rows, best_idx]

    offset = _parabolic_offset(
        norm[rows, best_lag - 1], norm[rows, best_lag], norm[rows, best_lag + 1]
    )
    confidence = np.where(np.isfinite(best_val), best_val, 0.0)
    return best_lag + offset, confidence


def extract_f0_autocorr(
    samples: np.ndarray,
    sr: int,
    f0_min: float = DEFAULT_F0_MIN,
    f0_max: float = DEFAULT_F0_MAX,
    confidence_threshold: float = DEFAULT_CONFIDENCE,
    frame_sec: float = FRAME_SEC,
    hop_sec: float = HOP_SEC,
    silence_db: float = DEFAULT_SILENCE_DB,
) -> PitchTrack:
    if not 0 < f0_min < f0_max:
        raise ValueError(f"Invalid F0 range: {f0_min}-{f0_max} Hz")
    frame_len = int(round(frame_sec * sr))
    hop_len = int(round(hop_sec * sr))
    min_lag = max(2, int(np.floor(sr / f0_max)))
    max_lag = int(np.ceil(sr / f0_min))
    # A frame must span at least two periods of the lowest F0 for a reliable peak.
    if 2 * max_lag > frame_len:
        raise ValueError(
            f"f0_min={f0_min} Hz is too low for a {frame_sec * 1000:.0f} ms frame "
            f"(minimum {2 / frame_sec:.0f} Hz)"
        )

    samples = np.asarray(samples, dtype=np.float64)
    frames = _frame(samples, frame_len, hop_len)
    window = np.hanning(frame_len)

    lag = np.empty(len(frames))
    conf = np.empty(len(frames))
    for start in range(0, len(frames), _CHUNK_FRAMES):
        sl = slice(start, start + _CHUNK_FRAMES)
        lag[sl], conf[sl] = _autocorr_chunk(frames[sl], window, min_lag, max_lag)

    rms = np.sqrt(np.mean(frames**2, axis=1))
    ref = rms.max() if len(rms) and rms.max() > 0 else 1.0
    with np.errstate(divide="ignore"):
        level_db = 20 * np.log10(np.maximum(rms, 1e-12) / ref)

    f0 = sr / lag
    voiced = (conf > confidence_threshold) & (level_db > silence_db)
    voiced &= (f0 >= f0_min * 0.97) & (f0 <= f0_max * 1.03)
    f0 = np.where(voiced, f0, 0.0)
    times = (np.arange(len(frames)) * hop_len + frame_len / 2) / sr

    return PitchTrack(
        f0=f0,
        times=times,
        confidence=conf,
        hop=hop_len / sr,
        method="autocorr",
        params={
            "f0_min": f0_min,
            "f0_max": f0_max,
            "confidence_threshold": confidence_threshold,
            "frame_sec": frame_sec,
            "hop_sec": hop_sec,
            "silence_db": silence_db,
        },
    )


def extract_f0_yin(
    samples: np.ndarray,
    sr: int,
    f0_min: float = DEFAULT_F0_MIN,
    f0_max: float = DEFAULT_F0_MAX,
    hop_sec: float = HOP_SEC,
) -> PitchTrack:
    import librosa

    hop_len = int(round(hop_sec * sr))
    # pYIN needs at least two periods of the lowest F0 in a frame.
    frame_len = 1 << int(np.ceil(np.log2(2.2 * sr / f0_min)))
    f0, voiced_flag, voiced_prob = librosa.pyin(
        np.asarray(samples, dtype=np.float32),
        fmin=f0_min,
        fmax=f0_max,
        sr=sr,
        frame_length=frame_len,
        hop_length=hop_len,
        center=True,
    )
    f0 = np.where(voiced_flag & np.isfinite(f0), f0, 0.0)
    times = librosa.frames_to_time(np.arange(len(f0)), sr=sr, hop_length=hop_len)
    return PitchTrack(
        f0=f0,
        times=times,
        confidence=np.nan_to_num(voiced_prob),
        hop=hop_len / sr,
        method="yin",
        params={"f0_min": f0_min, "f0_max": f0_max, "hop_sec": hop_sec},
    )


def extract_f0(
    samples: np.ndarray,
    sr: int,
    method: PitchMethod = "autocorr",
    f0_min: float = DEFAULT_F0_MIN,
    f0_max: float = DEFAULT_F0_MAX,
    **kwargs,
) -> PitchTrack:
    if method == "autocorr":
        return extract_f0_autocorr(samples, sr, f0_min=f0_min, f0_max=f0_max, **kwargs)
    if method == "yin":
        return extract_f0_yin(samples, sr, f0_min=f0_min, f0_max=f0_max, **kwargs)
    if method == "crepe":
        raise NotImplementedError(
            "CREPE pitch tracking is planned for a later version; use 'autocorr' or 'yin'."
        )
    raise ValueError(f"Unknown pitch method: {method}")
