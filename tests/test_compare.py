import json

import numpy as np
import pytest

from accent_analyzer.analysis.compare import compare_takes, profile, semitone_contour, shadow
from accent_analyzer.analysis.pipeline import analyze_track
from accent_analyzer.analysis.pitch import PitchTrack, extract_f0
import synth


@pytest.fixture(scope="module")
def takes():
    return {k: analyze_track(extract_f0(a, synth.SR), duration=len(a) / synth.SR)
            for k, a in synth.sentence_takes().items()}


def test_same_intonation_in_another_voice_scores_high(takes):
    r = shadow(takes["ref"], takes["same"])
    assert r.contour_match >= 90
    assert r.ending_agreement == 1.0
    assert r.score >= 85
    assert r.tips == ["Close match. Try a faster or more animated reference next."]


def test_flipped_endings_are_caught(takes):
    r = shadow(takes["ref"], takes["flipped"])
    assert r.ending_agreement == 0.0
    assert r.score < 60
    # Coaching only targets missed falls (the reference's one rise isn't coached).
    falls_missed = [c for c in r.endings if c.ref_direction == "falling"]
    assert len(falls_missed) == 3
    assert sum("Drop your pitch" in t for t in r.tips) == 3


def test_monotone_scores_lowest(takes):
    mono = shadow(takes["ref"], takes["monotone"])
    assert mono.range_match < 15
    assert mono.score < shadow(takes["ref"], takes["flipped"]).score
    assert any("exaggerate the highs and lows" in t for t in mono.tips)


def test_shadow_overlay_and_json(takes):
    r = shadow(takes["ref"], takes["same"])
    o = r.overlay
    assert len(o["ref_t"]) == len(o["ref_st"]) == len(o["user_st"]) > 100
    assert json.loads(json.dumps(r.to_dict()))["score"] == r.score


def test_shadow_needs_voiced_speech(takes):
    f0 = np.zeros(300)
    silent = analyze_track(PitchTrack(f0=f0, times=0.02 + 0.01 * np.arange(300), confidence=f0))
    with pytest.raises(ValueError, match="Not enough voiced"):
        shadow(takes["ref"], silent)


def test_median_filter_removes_octave_spike():
    f0 = np.full(200, 150.0)
    f0[100] = 300.0  # one-frame octave error
    result = analyze_track(PitchTrack(f0=f0, times=0.02 + 0.01 * np.arange(200), confidence=np.ones(200)))
    _, st = semitone_contour(result, step=0.01)
    assert np.max(np.abs(st)) < 0.01


def test_ab_prefers_falling_take_with_reasons(takes):
    r = compare_takes(takes["flipped"], takes["same"])
    assert r.winner == "B"
    assert r.a.final_direction == "rising" and r.b.final_direction == "falling"
    assert r.reasons[0].startswith("Take B ends falling")
    assert len(r.overlay["t"]) == len(r.overlay["a_st"]) == len(r.overlay["b_st"])


def test_ab_reason_names_the_falling_take_even_when_it_loses(takes, nze, ame):
    # AmE wins overall on range and onsets, though NZE's last phrase happens to fall.
    r = compare_takes(nze, ame)
    assert r.winner == "B"
    assert r.reasons[0].startswith("Take A ends falling")


def test_ab_identical_is_too_close(takes):
    r = compare_takes(takes["same"], takes["same"])
    assert r.winner is None and r.reasons[0].startswith("Too close to call")


def test_profile_scores(takes):
    good, bad = profile(takes["same"]), profile(takes["monotone"])
    assert 0 <= bad.score < good.score <= 1
    assert good.span > 5 and bad.span < 2
