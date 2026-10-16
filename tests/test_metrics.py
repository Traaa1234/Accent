import numpy as np
import pytest

from accent_analyzer.analysis.metrics import register_metrics
from accent_analyzer.analysis.pitch import PitchTrack, extract_f0_autocorr
from accent_analyzer.targets import Status
from synth import SR, contour, harmonic_tone


def _track(f0: np.ndarray) -> PitchTrack:
    f0 = np.asarray(f0, dtype=float)
    return PitchTrack(f0=f0, times=0.02 + 0.01 * np.arange(len(f0)), confidence=np.ones(len(f0)))


def test_basic_statistics_on_known_track():
    f0 = np.concatenate([np.full(40, 100.0), np.full(40, 300.0), np.zeros(20)])
    m = register_metrics(_track(f0))
    assert m.voiced_ratio == pytest.approx(0.8)
    assert m.mean_f0 == pytest.approx(200)
    assert m.median_f0 == pytest.approx(200)
    assert m.std_f0 == pytest.approx(100)
    assert m.p10_f0 == pytest.approx(100)
    assert m.p90_f0 == pytest.approx(300)
    assert m.range_ratio == pytest.approx(3.0)
    assert m.statuses()["range_ratio"] is Status.ON_TARGET
    assert m.statuses()["voiced_ratio"] is Status.ON_TARGET


def test_unvoiced_track_gives_nan_metrics():
    m = register_metrics(_track(np.zeros(50)))
    assert m.voiced_ratio == 0
    assert np.isnan(m.mean_f0) and np.isnan(m.range_ratio)


def test_monotone_flagged_below_targets():
    m = register_metrics(extract_f0_autocorr(harmonic_tone(contour([(3.0, 140, 160)])), SR))
    assert m.range_ratio < 1.2
    statuses = m.statuses()
    assert statuses["range_ratio"] is Status.BELOW
    assert statuses["std_f0"] is Status.BELOW
    # Continuous phonation with no pauses: "rushing" side of the voiced-ratio target.
    assert statuses["voiced_ratio"] is Status.ABOVE


def test_voiced_ratio_with_pauses():
    # 70% voiced, 30% pause.
    f0 = contour([(1.4, 180, 120), (0.6, 0, 0)] * 3)
    m = register_metrics(extract_f0_autocorr(harmonic_tone(f0), SR))
    assert m.voiced_ratio == pytest.approx(0.70, abs=0.03)
    assert m.duration == pytest.approx(6.0, abs=0.05)
