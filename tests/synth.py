"""Synthetic voice-like signals with known F0 contours, used as test fixtures."""

from __future__ import annotations

import numpy as np

SR = 16_000


def harmonic_tone(
    f0: np.ndarray | float,
    duration: float | None = None,
    sr: int = SR,
    n_harmonics: int = 12,
    amplitude: float = 0.5,
) -> np.ndarray:
    """Glottal-like harmonic signal following a per-sample F0 contour.

    Pass a scalar F0 with `duration`, or a per-sample array. F0 <= 0 yields silence.
    Harmonic amplitudes fall off as 1/k, roughly like a voice source.
    """
    if np.isscalar(f0):
        f0 = np.full(int(round(duration * sr)), float(f0))
    f0 = np.asarray(f0, dtype=np.float64)
    voiced = f0 > 0
    phase = 2 * np.pi * np.cumsum(np.where(voiced, f0, 0.0)) / sr
    signal = np.zeros_like(f0)
    for k in range(1, n_harmonics + 1):
        # Drop harmonics above Nyquist for the local F0.
        signal += np.where(k * f0 < sr / 2, np.sin(k * phase) / k, 0.0)
    signal *= voiced
    peak = np.max(np.abs(signal)) or 1.0
    return (amplitude * signal / peak).astype(np.float32)


def contour(segments: list[tuple[float, float, float]], sr: int = SR) -> np.ndarray:
    """Build a per-sample F0 array from (duration_s, start_hz, end_hz) segments.

    Linear glide within each segment; use start = end = 0 for a pause.
    """
    parts = [np.linspace(a, b, int(round(d * sr)), endpoint=False) for d, a, b in segments]
    return np.concatenate(parts)


def expected_f0_at(f0_samples: np.ndarray, times: np.ndarray, sr: int = SR) -> np.ndarray:
    idx = np.clip((times * sr).astype(int), 0, len(f0_samples) - 1)
    return f0_samples[idx]
