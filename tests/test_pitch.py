import numpy as np
import pytest

from accent_analyzer.analysis.pitch import extract_f0, extract_f0_autocorr
from synth import SR, contour, expected_f0_at, harmonic_tone


@pytest.mark.parametrize("f0", [85.0, 110.0, 150.0, 220.0, 300.0])
def test_constant_tone_frequency(f0):
    track = extract_f0_autocorr(harmonic_tone(f0, 1.0), SR)
    voiced = track.voiced_f0
    assert track.voiced.mean() > 0.95
    assert np.median(voiced) == pytest.approx(f0, rel=0.01)
    # No octave jumps anywhere in a steady tone.
    assert np.all(np.abs(voiced / f0 - 1) < 0.03)


def test_pure_sine_tracked():
    t = np.arange(SR) / SR
    track = extract_f0_autocorr(0.5 * np.sin(2 * np.pi * 180 * t), SR)
    assert np.median(track.voiced_f0) == pytest.approx(180, rel=0.01)


def test_frame_timing():
    track = extract_f0_autocorr(harmonic_tone(150, 1.0), SR)
    assert track.hop == pytest.approx(0.010)
    assert track.times[0] == pytest.approx(0.020)  # centre of first 40 ms frame
    assert np.allclose(np.diff(track.times), 0.010)
    assert len(track) == 1 + (SR - 640) // 160


def test_glide_is_tracked():
    f0 = contour([(2.0, 120, 260)])
    track = extract_f0_autocorr(harmonic_tone(f0), SR)
    v = track.voiced
    truth = expected_f0_at(f0, track.times)[v]
    rel_err = np.abs(track.f0[v] / truth - 1)
    assert v.mean() > 0.95
    assert np.median(rel_err) < 0.01
    assert np.percentile(rel_err, 95) < 0.03


def test_silence_is_unvoiced():
    track = extract_f0_autocorr(np.zeros(SR, dtype=np.float32), SR)
    assert not track.voiced.any()
    assert np.all(track.f0 == 0)


def test_white_noise_mostly_unvoiced():
    rng = np.random.default_rng(0)
    track = extract_f0_autocorr(0.3 * rng.standard_normal(2 * SR), SR)
    assert track.voiced.mean() < 0.05


def test_pauses_marked_unvoiced():
    f0 = contour([(0.8, 150, 150), (0.5, 0, 0), (0.8, 200, 200)])
    track = extract_f0_autocorr(harmonic_tone(f0), SR)
    in_pause = (track.times > 0.85) & (track.times < 1.25)
    assert not track.voiced[in_pause].any()
    first = track.f0[(track.times > 0.1) & (track.times < 0.7)]
    second = track.f0[(track.times > 1.4) & (track.times < 2.0)]
    assert np.median(first) == pytest.approx(150, rel=0.01)
    assert np.median(second) == pytest.approx(200, rel=0.01)


def test_quiet_background_hum_below_silence_gate():
    # Speech at full level, then a faint 120 Hz hum 50 dB down should not count as voiced.
    loud = harmonic_tone(150, 1.0, amplitude=0.5)
    hum = harmonic_tone(120, 1.0, amplitude=0.5 * 10 ** (-50 / 20))
    track = extract_f0_autocorr(np.concatenate([loud, hum]), SR)
    assert not track.voiced[track.times > 1.05].any()


def test_adjustable_range_limits_output():
    track = extract_f0_autocorr(harmonic_tone(contour([(1.0, 100, 300)])), SR, f0_min=150, f0_max=250)
    voiced = track.voiced_f0
    assert voiced.min() >= 150 * 0.97
    assert voiced.max() <= 250 * 1.03


def test_confidence_threshold_controls_voicing():
    rng = np.random.default_rng(1)
    noisy = harmonic_tone(150, 1.0) + 0.4 * rng.standard_normal(SR).astype(np.float32)
    lenient = extract_f0_autocorr(noisy, SR, confidence_threshold=0.1)
    strict = extract_f0_autocorr(noisy, SR, confidence_threshold=0.9)
    assert lenient.voiced.mean() > strict.voiced.mean()


def test_invalid_range_rejected():
    with pytest.raises(ValueError):
        extract_f0_autocorr(np.zeros(SR), SR, f0_min=300, f0_max=200)
    with pytest.raises(ValueError):
        extract_f0_autocorr(np.zeros(SR), SR, f0_min=40)  # fewer than two periods per 40 ms frame


def test_short_input_does_not_crash():
    track = extract_f0_autocorr(harmonic_tone(150, 0.02), SR)
    assert len(track) == 1


def test_crepe_not_yet_available():
    with pytest.raises(NotImplementedError):
        extract_f0(np.zeros(SR), SR, method="crepe")


@pytest.mark.slow
def test_yin_agrees_with_autocorr():
    f0 = contour([(1.0, 140, 220)])
    audio = harmonic_tone(f0)
    yin = extract_f0(audio, SR, method="yin")
    ac = extract_f0(audio, SR, method="autocorr")
    assert yin.method == "yin"
    assert yin.voiced.mean() > 0.9
    assert np.median(yin.voiced_f0) == pytest.approx(np.median(ac.voiced_f0), rel=0.03)
