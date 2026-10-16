import sys
from pathlib import Path

import pytest

# Make the `synth` helper importable from test modules.
sys.path.insert(0, str(Path(__file__).parent))

import synth  # noqa: E402
from accent_analyzer.analysis.pipeline import analyze_track  # noqa: E402
from accent_analyzer.analysis.pitch import extract_f0  # noqa: E402


def _analyze(audio, name):
    return analyze_track(extract_f0(audio, synth.SR), source=f"{name}.wav", duration=len(audio) / synth.SR)


@pytest.fixture(scope="session")
def nze():
    return _analyze(synth.nze_like(), "nze_like")


@pytest.fixture(scope="session")
def ame():
    return _analyze(synth.ame_like(), "ame_like")


@pytest.fixture(scope="session")
def short():
    return _analyze(synth.short_clip(), "short_clip")


@pytest.fixture(scope="session")
def continuous():
    return _analyze(synth.continuous_speech(), "continuous_speech")
