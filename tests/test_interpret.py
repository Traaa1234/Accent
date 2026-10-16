from types import SimpleNamespace

import pytest

from accent_analyzer.analysis.interpret import (
    direction_asymmetry,
    integration_milestone,
    register_label,
    voiced_ratio_band,
)
from accent_analyzer.analysis.phrasing import PhraseAnalysis, PhraseEnd, classify_delta


def _ends(deltas):
    return [PhraseEnd(float(i), 150, 150 + d, d, *classify_delta(d)) for i, d in enumerate(deltas)]


def _result(deltas=(), voiced_ratio=0.7, metrics=None):
    primary = PhraseAnalysis(0.2, [], _ends(deltas), [])
    return SimpleNamespace(
        phrasing=SimpleNamespace(primary=primary),
        register=SimpleNamespace(voiced_ratio=voiced_ratio, n_voiced=100),
        metrics=lambda: metrics or {},
    )


@pytest.mark.parametrize(
    "deltas,severity,phrase",
    [
        ([-60, -60, -60, 40], "good", "Falls dominate"),
        ([-20, -20, -20, 60], "warning", "falls are smaller"),
        ([-90, 30, 30, 30], "warning", "falls are big but rises are more frequent"),
        ([40, 40, 40, -5], "warning", "Rising endings dominate"),
    ],
)
def test_direction_asymmetry(deltas, severity, phrase):
    f = direction_asymmetry(_result(deltas))
    assert f.severity == severity
    assert phrase in f.message


def test_direction_asymmetry_needs_data():
    assert direction_asymmetry(_result([0, 2, -3])) is None


@pytest.mark.parametrize(
    "ratio,severity,word",
    [(0.9, "warning", "rushing"), (0.82, "info", "rushed"), (0.7, "good", "natural"),
     (0.5, "info", "choppy"), (0.3, "warning", "hesitant")],
)
def test_voiced_ratio_band(ratio, severity, word):
    f = voiced_ratio_band(_result(voiced_ratio=ratio))
    assert f.severity == severity and word in f.message


def test_integration_milestone():
    hit = {"hrt_rate": 0.2, "high_onset_rate": 0.45, "range_ratio": 2.7}
    assert integration_milestone(_result(metrics=hit)).severity == "good"
    assert integration_milestone(_result(metrics={**hit, "range_ratio": 2.5})) is None
    assert integration_milestone(_result(metrics={**hit, "hrt_rate": 0.3})) is None


@pytest.mark.parametrize("f0,label", [(200, "animated"), (170, "neutral"), (140, "calm"), (float("nan"), "unknown")])
def test_register_label(f0, label):
    assert register_label(f0) == label
