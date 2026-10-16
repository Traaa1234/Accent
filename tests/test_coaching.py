import json
from datetime import datetime

import pytest
import soundfile as sf
from click.testing import CliRunner

from accent_analyzer.analyzer import cli
from accent_analyzer.coaching import load_library, recommend
from accent_analyzer.coaching.library import LibraryError, parse_library
from accent_analyzer.coaching.report import render_coaching_html
from accent_analyzer.history import HistoryStore
from accent_analyzer.reports import build_pdf, render_html
from accent_analyzer.targets import TARGETS
import synth

ON_TARGET = {
    "hrt_rate": 0.15, "fall_rate": 0.8, "range_ratio": 2.8, "std_f0": 70, "voiced_ratio": 0.7,
    "high_onset_rate": 0.5, "low_onset_rate": 0.1, "n_phrase_ends": 20,
}


# --- library -------------------------------------------------------------------------

def test_library_has_all_nine_modules():
    lib = load_library()
    assert set(lib) == {"hrt", "range", "onset", "tflap", "dark_l", "vowels", "rhotic", "connected", "lexical"}
    for m in lib.values():
        assert m.description and m.target and m.drills and m.triggers
        assert all(d.steps for d in m.drills)
        assert m.examples or m.words


def test_spec_content_present():
    lib = load_library()
    assert {d.name for d in lib["hrt"].drills} == {
        "30-second self-audit", "News anchor mode", "Contrast pairs", "Full-stop hand chop"}
    tflap = lib["tflap"].words
    assert len([w for w in tflap if " " not in w]) == 20
    assert {"get it", "put it", "what about", "a lot of"} <= set(tflap)
    assert any("footpath -> sidewalk" == w for w in lib["lexical"].words)


def test_metric_triggers_reference_real_metrics():
    known = set(ON_TARGET) | set(TARGETS)
    for m in load_library().values():
        for t in m.metric_triggers:
            assert t.metric in known, (m.id, t.metric)
        for p in m.progress:
            assert p.metric is None or p.metric in known


def test_spec_trigger_thresholds():
    lib = load_library()
    trig = {m.id: {(t.metric, t.op, t.value) for t in m.metric_triggers} for m in lib.values()}
    assert trig["hrt"] == {("hrt_rate", ">", 0.25)}
    assert trig["range"] == {("range_ratio", "<", 2.5), ("std_f0", "<", 60)}
    assert trig["onset"] == {("high_onset_rate", "<", 0.30), ("low_onset_rate", ">", 0.40)}
    assert trig["connected"] == {("voiced_ratio", "<", 0.50)}
    assert lib["vowels"].accent_triggers[0].accents == ("nze", "aue")


@pytest.mark.parametrize("toml,match", [
    ('[[module]]\nid="x"\nname="X"\npriority=1\ndetection="acoustic"\ndescription="d"\ntarget="t"\n'
     'triggers=[{metric="hrt_rate", op="!=", value=1}]', "operator"),
    ('[[module]]\nid="x"\nname="X"\npriority=1\ndetection="acoustic"\ndescription="d"\ntarget="t"\n'
     'triggers=[{accents=["klingon"]}]', "accents"),
    ('[[module]]\nid="x"\nname="X"\npriority=1\ndetection="acoustic"\ntarget="t"\ntriggers=[]', "description"),
])
def test_library_validation(toml, match):
    with pytest.raises(LibraryError, match=match):
        parse_library(toml)


# --- engine --------------------------------------------------------------------------

def ids(recs):
    return [r.module.id for r in recs]


def test_nothing_triggers_on_target_without_accent():
    assert recommend(ON_TARGET) == []


def test_each_metric_trigger():
    cases = {
        "hrt": {"hrt_rate": 0.4},
        "range": {"range_ratio": 2.0},
        "onset": {"low_onset_rate": 0.5},
        "connected": {"voiced_ratio": 0.4},
    }
    for module, change in cases.items():
        assert ids(recommend({**ON_TARGET, **change})) == [module]


def test_ranked_by_severity():
    recs = recommend({**ON_TARGET, "hrt_rate": 0.30, "range_ratio": 1.2}, limit=None)
    assert ids(recs) == ["range", "hrt"]  # range is further past its threshold
    assert recs[0].score > recs[1].score


def test_accent_modules_after_measured():
    recs = recommend({**ON_TARGET, "hrt_rate": 0.6}, accent="nze", limit=None)
    assert ids(recs)[0] == "hrt"
    assert set(ids(recs)[1:]) == {"tflap", "rhotic", "vowels", "lexical"}
    assert all(r.source == "accent" for r in recs[1:])
    planned = next(r for r in recs if r.module.id == "tflap")
    assert "planned for v2" in planned.reasons[0]


@pytest.mark.parametrize("accent,expected", [
    ("indian", {"tflap", "dark_l", "lexical"}),
    ("british", {"tflap", "dark_l", "rhotic", "lexical"}),
    ("aue", {"tflap", "rhotic", "vowels", "lexical"}),
    ("other", set()),
])
def test_accent_triggers(accent, expected):
    assert set(ids(recommend(ON_TARGET, accent=accent, limit=None))) == expected


def test_limit_and_focus():
    m = {**ON_TARGET, "hrt_rate": 0.6, "range_ratio": 1.5, "voiced_ratio": 0.4}
    assert len(recommend(m, accent="nze")) == 4
    assert ids(recommend(m, focus="hrt")) == ["hrt"]
    # Focusing on a module that didn't trigger still returns it, marked as requested.
    req = recommend(ON_TARGET, focus="hrt")
    assert ids(req) == ["hrt"] and req[0].source == "requested"
    with pytest.raises(KeyError):
        recommend(ON_TARGET, focus="nope")


def test_small_sample_marks_hrt_provisional():
    recs = recommend({**ON_TARGET, "hrt_rate": 0.6, "range_ratio": 2.0, "n_phrase_ends": 4}, limit=None)
    hrt = next(r for r in recs if r.module.id == "hrt")
    assert hrt.provisional and "Provisional" in hrt.why
    assert not next(r for r in recs if r.module.id == "range").provisional


def test_progress_with_history():
    history = [{"hrt_rate": 0.5}, {"hrt_rate": 0.2}, {"hrt_rate": 0.35}]
    rec = recommend({**ON_TARGET, "hrt_rate": 0.35}, history=history)[0]
    hrt_row = next(p for p in rec.progress if p["metric"] == "hrt_rate")
    assert hrt_row["current"] == "35%" and hrt_row["previous"] == "20%"
    assert hrt_row["best"] == "20%"  # lower is better for HRT
    assert hrt_row["on_target"] is False
    assert "HRT share of phrase endings at or below 25% (now 35%)" in rec.to_report_dict()["progress"]
    onset = recommend({**ON_TARGET, "high_onset_rate": 0.1})[0].to_report_dict()["progress"]
    assert "LOW onsets at or below 20% (now 10% ✓ met)" in onset


def test_fixture_recommendations(nze, ame):
    assert ids(recommend(nze.metrics()))[:3] == ["hrt", "onset", "range"]
    assert "hrt" not in ids(recommend(ame.metrics()))


# --- rendering -----------------------------------------------------------------------

def test_reports_render_recommendations(nze):
    recs = [r.to_report_dict() for r in recommend(nze.metrics(), accent="nze")]
    html = render_html(nze, recommendations=recs)
    assert "1. High rising terminal (HRT)" in html
    assert "<strong>News anchor mode</strong>" in html
    assert "Practice sentences" in html and "Key words" in html
    assert "No coaching modules triggered" in render_html(nze, recommendations=[])
    assert build_pdf(nze, recommendations=recs).startswith(b"%PDF")


def test_coaching_html(tmp_path, nze):
    with HistoryStore(tmp_path / "h.db") as store:
        record = store.add(nze, name="Mon", accent="nze")
    html = render_coaching_html(recommend(nze.metrics(), accent="nze"), record, "nze")
    assert "Coaching plan" in html and "New Zealand English" in html and "Flap ladder" in html


# --- CLI -----------------------------------------------------------------------------

@pytest.fixture
def nze_wav(tmp_path):
    path = tmp_path / "nze.wav"
    sf.write(path, synth.nze_like(), synth.SR)
    return path


def test_analyze_prints_coaching_and_remembers_accent(tmp_path, nze_wav):
    db = tmp_path / "h.db"
    runner = CliRunner()
    first = runner.invoke(cli, ["analyze", str(nze_wav), "--history", str(db), "--accent", "nze"])
    assert first.exit_code == 0, first.output
    assert "Coaching focus" in first.output and "1. High rising terminal (HRT)" in first.output
    second = runner.invoke(cli, ["analyze", str(nze_wav), "--history", str(db), "--json"])
    data = json.loads(second.stdout)
    assert data["accent"] == "nze"  # remembered from the first recording
    assert data["recommendations"][0]["id"] == "hrt"
    with HistoryStore(db) as store:
        assert [r.accent for r in store.all()] == ["nze", "nze"]


def test_coach_command(tmp_path, nze_wav):
    db = tmp_path / "h.db"
    runner = CliRunner()
    for day in ("2026-10-01", "2026-10-02"):
        runner.invoke(cli, ["analyze", str(nze_wav), "--history", str(db), "--accent", "nze", "--date", day])
    plan = tmp_path / "plan.html"
    out = runner.invoke(cli, ["coach", "--history", str(db), "--focus", "hrt", "-o", str(plan)])
    assert out.exit_code == 0, out.output
    assert "Coaching plan for" in out.output and "accent: nze" in out.output
    assert "News anchor mode" in out.output and "○ HRT share" in out.output and "previous 70%" in out.output
    assert "News anchor mode" in plan.read_text()
    data = json.loads(runner.invoke(cli, ["coach", "--history", str(db), "--json", "--limit", "0"]).output)
    assert [r["id"] for r in data["recommendations"]][:3] == ["hrt", "onset", "range"]
    assert len(data["recommendations"]) == 7


def test_coach_errors(tmp_path):
    runner = CliRunner()
    assert "Give --history" in runner.invoke(cli, ["coach"]).output
    db = tmp_path / "h.db"
    HistoryStore(db).close()
    assert "History is empty" in runner.invoke(cli, ["coach", "--history", str(db)]).output
