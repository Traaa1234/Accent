import numpy as np
import pytest

from accent_analyzer.analysis.phrasing import (
    Phrase,
    analyze_phrasing,
    classify_delta,
    classify_onset,
    measure_end,
    measure_onset,
    segment_phrases,
)
from accent_analyzer.analysis.pitch import PitchTrack

HOP = 0.01


def track_from(segments: list[tuple[int, float, float]]) -> PitchTrack:
    """Build a PitchTrack from (n_frames, start_hz, end_hz); 0 Hz = unvoiced."""
    f0 = np.concatenate([np.linspace(a, b, n) for n, a, b in segments])
    return PitchTrack(f0=f0, times=0.02 + HOP * np.arange(len(f0)), confidence=np.ones(len(f0)))


@pytest.mark.parametrize(
    "delta,direction,magnitude",
    [
        (5, "level", None),
        (10, "level", None),
        (-10, "level", None),
        (15, "rising", "small"),
        (30, "rising", "mod"),
        (80, "rising", "mod"),
        (95, "rising", "big"),
        (-25, "falling", "small"),
        (-50, "falling", "mod"),
        (-120, "falling", "big"),
    ],
)
def test_classify_delta(delta, direction, magnitude):
    assert classify_delta(delta) == (direction, magnitude)


@pytest.mark.parametrize("ratio,category", [(1.2, "high"), (1.15, "mid"), (1.0, "mid"), (0.9, "mid"), (0.85, "low")])
def test_classify_onset(ratio, category):
    assert classify_onset(ratio) == category


def test_segmentation_depends_on_threshold():
    track = track_from([(100, 150, 150), (25, 0, 0), (100, 150, 150), (15, 0, 0), (100, 150, 150)])
    assert len(segment_phrases(track, 0.20)) == 2
    phrases = segment_phrases(track, 0.12)
    assert len(phrases) == 3
    assert phrases[0].start == pytest.approx(0.02)
    assert phrases[0].end == pytest.approx(0.02 + 99 * HOP)


def test_leading_and_trailing_silence_are_not_phrases():
    track = track_from([(50, 0, 0), (100, 150, 150), (50, 0, 0)])
    phrases = segment_phrases(track, 0.2)
    assert len(phrases) == 1
    assert phrases[0].start == pytest.approx(0.02 + 50 * HOP)


def test_short_voiced_blips_ignored():
    track = track_from([(100, 150, 150), (30, 0, 0), (5, 200, 200), (30, 0, 0), (100, 150, 150)])
    assert len(segment_phrases(track, 0.2)) == 2


def test_rising_end_measured():
    # 1 s flat at 150 Hz, then the last 0.5 s rises linearly to 250 Hz.
    track = track_from([(100, 150, 150), (50, 150, 250)])
    end = measure_end(track, segment_phrases(track, 0.2)[0])
    assert end.direction == "rising"
    assert end.magnitude == "mod"
    assert end.delta == pytest.approx(66, abs=5)  # medians of first vs last third


def test_big_fall_measured():
    track = track_from([(100, 220, 220), (50, 220, 90)])
    end = measure_end(track, segment_phrases(track, 0.2)[0])
    assert (end.direction, end.magnitude) == ("falling", "big")


def test_end_window_clipped_to_short_phrase():
    track = track_from([(35, 150, 200)])  # 0.35 s phrase: window covers whole phrase
    end = measure_end(track, segment_phrases(track, 0.2)[0])
    assert end is not None and end.direction == "rising"


def test_too_short_phrase_end_unmeasurable():
    track = track_from([(20, 150, 200)])
    assert measure_end(track, Phrase(0.02, 0.21)) is None


def test_onset_ratio():
    track = track_from([(50, 260, 260), (150, 180, 180)])
    onset = measure_onset(track, segment_phrases(track, 0.2)[0], overall_mean=200)
    assert onset.ratio == pytest.approx(1.3)
    assert onset.category == "high"


def _many_phrases(n: int, gap_frames: int) -> PitchTrack:
    segments = []
    for i in range(n):
        segments += [(100, 200, 200), (50, 200, 140 if i % 4 else 260), (gap_frames, 0, 0)]
    return track_from(segments)


def test_adaptive_threshold_keeps_primary_when_enough_boundaries():
    result = analyze_phrasing(_many_phrases(16, gap_frames=30))
    assert not result.used_fallback
    assert result.primary.pause_threshold == 0.20
    assert result.primary.n_ends == 16
    assert set(result.by_threshold) == {0.20, 0.12}


def test_adaptive_threshold_falls_back_for_continuous_speech():
    result = analyze_phrasing(_many_phrases(16, gap_frames=15))
    assert result.used_fallback
    assert result.by_threshold[0.20].n_ends == 1
    assert result.primary.pause_threshold == 0.12
    assert result.primary.n_ends == 16


def test_rates_and_magnitudes():
    p = analyze_phrasing(_many_phrases(16, gap_frames=30)).primary
    # Every 4th phrase rises 200 -> 260, others fall 200 -> 140.
    assert p.n_rising == 4 and p.n_falling == 12
    assert p.hrt_rate == pytest.approx(0.25)
    assert p.fall_rate == pytest.approx(0.75)
    assert p.mean_rise_hz == pytest.approx(p.mean_fall_hz, rel=0.05)
    assert sum(p.magnitude_counts().values()) == 16


def test_empty_track():
    result = analyze_phrasing(track_from([(100, 0, 0)]))
    assert result.primary.n_ends == 0
    assert np.isnan(result.primary.hrt_rate)
