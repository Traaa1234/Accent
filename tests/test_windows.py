import numpy as np
import pytest

from accent_analyzer.analysis.phrasing import segment_phrases
from accent_analyzer.analysis.windows import analyze_windows, classify_slope, pooled_slope
from test_phrasing import track_from


@pytest.mark.parametrize("slope,direction", [(6, "rising"), (5, "level"), (0, "level"), (-5, "level"), (-6, "falling")])
def test_classify_slope(slope, direction):
    assert classify_slope(slope) == direction


def test_pooled_slope_ignores_offsets_between_groups():
    t = np.arange(20.0)
    f0 = np.concatenate([200 - 2 * t[:10], 260 - 2 * t[10:]])  # falling, with an upward reset
    groups = np.repeat([0, 1], 10)
    assert pooled_slope(t, f0, groups) == pytest.approx(-2)
    assert np.polyfit(t, f0, 1)[0] > 0  # a plain fit reads the reset as a rise


def test_steady_decline_all_falling():
    w = analyze_windows(track_from([(1000, 220, 120)]))  # -10 Hz/s over 10 s
    assert len(w.windows) == 7  # frames span 0.02-10.01 s
    assert w.falling_rate == 1.0
    assert all(x.slope == pytest.approx(-10, abs=0.5) for x in w.windows)


def test_flat_all_level():
    w = analyze_windows(track_from([(800, 150, 150)]))
    assert w.level_rate == 1.0


def test_phrase_resets_not_counted_as_rises():
    # Five 1.5 s phrases each declining 220 -> 160 Hz, separated by 0.3 s pauses.
    track = track_from([(150, 220, 160), (30, 0, 0)] * 5)
    naive = analyze_windows(track)
    within = analyze_windows(track, segment_phrases(track, 0.2))
    assert within.within_phrase
    assert within.falling_rate == 1.0
    assert naive.falling_rate < within.falling_rate


def test_mostly_unvoiced_windows_skipped():
    track = track_from([(50, 150, 150), (500, 0, 0)])
    assert analyze_windows(track).windows == []


def test_clip_shorter_than_window():
    w = analyze_windows(track_from([(200, 150, 150)]))
    assert w.windows == []
    assert np.isnan(w.falling_rate)
