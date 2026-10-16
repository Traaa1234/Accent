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


# ---------------------------------------------------------------------------
# Speech-like fixtures: phrases with declination, pitch accents, consonant gaps,
# a controlled phrase-final movement, and pauses between phrases.

from dataclasses import dataclass  # noqa: E402

FINAL_SEC = 0.45  # final movement; kept fully voiced (phrase-final lengthening)


@dataclass(frozen=True)
class PhraseSpec:
    duration: float
    onset_hz: float  # pitch at phrase start
    base_hz: float  # pitch reached by declination before the final movement
    final_delta: float  # Hz change over the last FINAL_SEC (+ rise, - fall)
    accent_hz: float = 0.0  # max pitch-accent bump height


def _phrase(spec: PhraseSpec, rng: np.random.Generator, gap_range: tuple[float, float], sr: int):
    n = int(round(spec.duration * sr))
    t = np.arange(n) / sr
    body_end = spec.duration - FINAL_SEC
    f0 = np.where(
        t < body_end,
        spec.onset_hz + (spec.base_hz - spec.onset_hz) * t / body_end,
        spec.base_hz + spec.final_delta * (t - body_end) / FINAL_SEC,
    )
    voiced = np.ones(n, dtype=bool)
    pos = 0.25
    while pos < body_end - 0.15:
        syl = rng.uniform(0.16, 0.26)
        if spec.accent_hz:
            centre = pos + syl / 2
            bump = rng.uniform(0.3, 1.0) * spec.accent_hz * np.exp(-(((t - centre) / 0.07) ** 2))
            f0 = f0 + np.where(t < body_end, bump, 0.0)
        pos += syl
        gap = rng.uniform(*gap_range)
        if pos + gap < body_end - 0.05:
            voiced[int(pos * sr) : int((pos + gap) * sr)] = False
        pos += gap
    return np.where(voiced, f0, 0.0), ~voiced


def speech_like(
    phrases: list[PhraseSpec],
    pause_range: tuple[float, float],
    gap_range: tuple[float, float] = (0.04, 0.07),
    seed: int = 0,
    sr: int = SR,
) -> np.ndarray:
    rng = np.random.default_rng(seed)
    f0_parts, fric_parts = [np.zeros(int(0.3 * sr))], [np.zeros(int(0.3 * sr), dtype=bool)]
    for i, spec in enumerate(phrases):
        f0, fric = _phrase(spec, rng, gap_range, sr)
        f0_parts.append(f0)
        fric_parts.append(fric)
        pause = rng.uniform(*pause_range) if i < len(phrases) - 1 else 0.3
        f0_parts.append(np.zeros(int(pause * sr)))
        fric_parts.append(np.zeros(int(pause * sr), dtype=bool))
    f0 = np.concatenate(f0_parts)
    fric = np.concatenate(fric_parts)
    audio = harmonic_tone(f0, sr=sr)
    noise = rng.standard_normal(len(audio)).astype(np.float32)
    audio += np.where(fric, 0.05, 1e-4).astype(np.float32) * noise  # fricatives / room noise
    return audio


def _phrases(rng, n, duration, onset, base, accent, rise_share, rise, fall):
    specs = []
    n_rise = round(n * rise_share)
    rising = rng.permutation([True] * n_rise + [False] * (n - n_rise))
    for r in rising:
        delta = rng.uniform(*rise) if r else -rng.uniform(*fall)
        specs.append(
            PhraseSpec(rng.uniform(*duration), rng.uniform(*onset), rng.uniform(*base), delta, accent)
        )
    return specs


def nze_like(seed: int = 1) -> np.ndarray:
    """~60 s, narrow range, mid/low onsets, 70% rising phrase endings."""
    rng = np.random.default_rng(seed)
    specs = _phrases(rng, 20, (2.0, 2.8), (140, 155), (135, 150), 15, 0.70, (45, 90), (20, 35))
    return speech_like(specs, pause_range=(0.35, 0.6), gap_range=(0.06, 0.10), seed=seed)


def ame_like(seed: int = 2) -> np.ndarray:
    """~60 s, wide range, high onsets, 85% falling phrase endings."""
    rng = np.random.default_rng(seed)
    specs = _phrases(rng, 20, (2.4, 3.2), (255, 280), (135, 150), 55, 0.15, (25, 40), (60, 75))
    return speech_like(specs, pause_range=(0.3, 0.5), gap_range=(0.04, 0.07), seed=seed)


def short_clip(seed: int = 3) -> np.ndarray:
    """~12 s: too few phrase endings for a reliable HRT figure."""
    rng = np.random.default_rng(seed)
    specs = _phrases(rng, 4, (2.2, 2.8), (180, 200), (150, 160), 25, 0.5, (40, 60), (40, 60))
    return speech_like(specs, pause_range=(0.4, 0.6), seed=seed)


def continuous_speech(seed: int = 4) -> np.ndarray:
    """~45 s of run-on speech with only short (~0.16 s) breaths between phrases."""
    rng = np.random.default_rng(seed)
    specs = _phrases(rng, 25, (1.4, 1.8), (190, 210), (150, 165), 25, 0.4, (35, 60), (40, 70))
    return speech_like(specs, pause_range=(0.16, 0.18), seed=seed)
