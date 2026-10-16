"""End-to-end expectations on the four synthetic speech fixtures."""

import pytest

from accent_analyzer.analysis.pitch import extract_f0
from accent_analyzer.analysis.pipeline import analyze_track
from accent_analyzer.targets import Status
import synth


def _analyze(audio):
    return analyze_track(extract_f0(audio, synth.SR), duration=len(audio) / synth.SR)


@pytest.fixture(scope="module")
def nze():
    return _analyze(synth.nze_like())


@pytest.fixture(scope="module")
def ame():
    return _analyze(synth.ame_like())


@pytest.fixture(scope="module")
def short():
    return _analyze(synth.short_clip())


@pytest.fixture(scope="module")
def continuous():
    return _analyze(synth.continuous_speech())


def codes(result):
    return {f.code: f for f in result.findings}


class TestNZELike:
    def test_high_hrt(self, nze):
        m, s = nze.metrics(), nze.statuses()
        assert nze.phrasing.primary.n_ends == 20
        assert not nze.phrasing.used_fallback
        assert m["hrt_rate"] >= 0.6
        assert s["hrt_rate"] is Status.ABOVE

    def test_narrow_range(self, nze):
        m, s = nze.metrics(), nze.statuses()
        assert m["range_ratio"] < 1.5
        assert m["std_f0"] < 30
        assert s["range_ratio"] is Status.BELOW and s["std_f0"] is Status.BELOW

    def test_onsets_not_high(self, nze):
        assert nze.metrics()["high_onset_rate"] < 0.2

    def test_findings(self, nze):
        f = codes(nze)
        assert f["direction_asymmetry"].severity == "warning"
        assert f["direction_axis"].severity == "warning"
        assert f["foundation_axis"].severity == "warning"
        assert "small_sample" not in f


class TestAmELike:
    def test_low_hrt_and_dominant_falls(self, ame):
        m = ame.metrics()
        assert m["hrt_rate"] <= 0.2
        assert m["fall_rate"] >= 0.8
        assert m["mean_fall_hz"] > m["mean_rise_hz"]
        assert ame.statuses()["hrt_rate"] is Status.ON_TARGET

    def test_high_onsets(self, ame):
        m = ame.metrics()
        assert m["high_onset_rate"] >= 0.8
        assert m["low_onset_rate"] <= 0.1

    def test_wider_range_than_nze(self, ame, nze):
        m = ame.metrics()
        assert m["range_ratio"] > 2.0
        assert m["range_ratio"] > 1.5 * nze.metrics()["range_ratio"]
        assert m["std_f0"] > 2 * nze.metrics()["std_f0"]

    def test_voiced_ratio_natural(self, ame):
        assert ame.statuses()["voiced_ratio"] is Status.ON_TARGET

    def test_windows_mostly_falling(self, ame, nze):
        assert ame.metrics()["window_falling_rate"] > 0.5
        assert ame.metrics()["window_falling_rate"] > nze.metrics()["window_falling_rate"]

    def test_direction_axis_good(self, ame):
        f = codes(ame)
        assert f["direction_axis"].severity == "good"
        assert f["direction_asymmetry"].severity == "good"


class TestShortClip:
    def test_under_20_seconds(self, short):
        assert short.duration < 20

    def test_small_sample_caveat_reports_both_thresholds(self, short):
        assert short.phrasing.primary.n_ends < 10
        f = codes(short)["small_sample"]
        assert f.severity == "warning"
        assert "0.20s" in f.message and "0.12s" in f.message


class TestContinuousSpeech:
    def test_triggers_adaptive_fallback(self, continuous):
        p = continuous.phrasing
        assert p.used_fallback
        assert p.primary.pause_threshold == 0.12
        assert p.by_threshold[0.20].n_ends < 15
        assert p.by_threshold[0.12].n_ends >= 23  # 25 phrases synthesized

    def test_both_thresholds_in_output(self, continuous):
        d = continuous.to_dict()["phrasing"]["by_threshold"]
        assert set(d) == {"0.20", "0.12"}
