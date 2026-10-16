import json

import soundfile as sf
from click.testing import CliRunner

from accent_analyzer.analyzer import cli
from synth import contour, harmonic_tone


def test_analyze_json(tmp_path):
    path = tmp_path / "take.wav"
    sf.write(path, harmonic_tone(contour([(1.5, 220, 110), (0.5, 0, 0)] * 2)), 16_000)
    result = CliRunner().invoke(cli, ["analyze", str(path), "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["pitch_method"] == "autocorr"
    assert 0.7 < data["metrics"]["voiced_ratio"] < 0.8
    assert 1.5 < data["metrics"]["range_ratio"] < 2.0
    assert set(data["phrasing"]["by_threshold"]) == {"0.20", "0.12"}
    assert any(f["code"] == "small_sample" for f in data["findings"])


def test_analyze_table(tmp_path):
    path = tmp_path / "take.wav"
    sf.write(path, harmonic_tone(150, 1.0), 16_000)
    result = CliRunner().invoke(cli, ["analyze", str(path)])
    assert result.exit_code == 0, result.output
    for section in ("Register & variability", "Phrase endings", "Phrase onsets", "3-second windows", "Findings"):
        assert section in result.output
    assert "[LOW]" in result.output


def test_analyze_reports_errors(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("x")
    result = CliRunner().invoke(cli, ["analyze", str(path)])
    assert result.exit_code != 0
    assert "Unsupported" in result.output
