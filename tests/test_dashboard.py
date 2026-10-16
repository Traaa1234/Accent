import json
import re
from datetime import datetime, timedelta

import pytest
from click.testing import CliRunner

from accent_analyzer.analyzer import cli
from accent_analyzer.dashboard import dashboard_data, render_dashboard
from accent_analyzer.dashboard.build import (
    best_index,
    deflation_runs,
    overall_score,
    radar_scores,
)
from accent_analyzer.history import HistoryStore, Record

T0 = datetime(2026, 7, 1, 8)
GOOD = {"hrt_rate": 0.15, "fall_rate": 0.8, "high_onset_rate": 0.5, "range_ratio": 2.8,
        "std_f0": 70, "voiced_ratio": 0.7, "mean_f0": 200, "n_phrase_ends": 20}


def rec(i, **metrics):
    return Record(i, T0 + timedelta(days=i), f"r{i}", f"s{i}", 1, None, 60.0, "autocorr", "neutral",
                  {"n_phrase_ends": 20, **metrics}, {"accent": "nze"})


def embedded(html: str) -> dict:
    m = re.search(r"const D = (\{.*?\});\n", html, re.S)
    return json.loads(m.group(1))


# --- derived numbers -----------------------------------------------------------------

def test_radar_scores_on_target_are_one():
    assert set(radar_scores(GOOD).values()) == {1.0}
    assert overall_score(GOOD) == 1.0


@pytest.mark.parametrize("metric,value,axis,expected", [
    ("hrt_rate", 0.75, "hrt", 0.0),
    ("hrt_rate", 0.50, "hrt", 0.5),
    ("fall_rate", 0.375, "falls", 0.5),
    ("high_onset_rate", 0.20, "onsets", 0.5),
    ("range_ratio", 1.75, "range", 0.5),
    ("std_f0", 30, "std", 0.5),
    ("voiced_ratio", 0.45, "flow", 0.5),
    ("voiced_ratio", 0.90, "flow", 0.5),
    ("voiced_ratio", 1.0, "flow", 0.0),
])
def test_radar_axis_scaling(metric, value, axis, expected):
    assert radar_scores({**GOOD, metric: value})[axis] == pytest.approx(expected)


def test_radar_missing_metric_is_none():
    scores = radar_scores({**GOOD, "hrt_rate": float("nan"), "std_f0": None})
    assert scores["hrt"] is None and scores["std"] is None


def test_best_prefers_reliable_recordings():
    weak = {**GOOD, "hrt_rate": 0.6}
    records = [rec(0, **weak), rec(1, **GOOD), rec(2, **{**GOOD, "n_phrase_ends": 4})]
    assert best_index(records) == 1  # #2 ties on score but has too few endings
    assert best_index([rec(0, **{**weak, "n_phrase_ends": 3})]) == 0  # fallback when none reliable
    assert best_index([]) is None


@pytest.mark.parametrize("f0s,expected", [
    ([200, 190, 175, 160, 170], [{"start": 0, "end": 3, "drop": 40.0}]),
    ([200, 190, 185, 180], []),                       # only 20 Hz
    ([200, 180, 190, 170, 150, 140], [{"start": 2, "end": 5, "drop": 50.0}]),
    ([220, 200, 180, 200, 180, 160, 140], [{"start": 0, "end": 2, "drop": 40.0},
                                           {"start": 3, "end": 6, "drop": 60.0}]),
    ([200, None, 180, 160, 140], [{"start": 2, "end": 4, "drop": 40.0}]),
])
def test_deflation_runs(f0s, expected):
    assert deflation_runs(f0s) == expected


def test_dashboard_data_shape():
    records = [rec(i, **{**GOOD, "mean_f0": f, "hrt_rate": h})
               for i, (f, h) in enumerate([(210, 0.5), (190, 0.4), (170, 0.3), (160, 0.2)])]
    d = dashboard_data(records)
    assert [r["id"] for r in d["records"]] == [0, 1, 2, 3]
    assert d["records"][0]["metrics"]["hrt_rate"] == 0.5
    assert d["records"][0]["accent"] == "nze"
    assert d["best"] == 3
    assert d["deflation"] == [{"start": 0, "end": 3, "drop": 50.0}]
    assert {f["code"] for f in d["flags"]} >= {"register_deflation"}
    assert [a["key"] for a in d["radarAxes"]] == ["hrt", "falls", "onsets", "range", "std", "flow"]
    assert d["targets"]["hrt_rate"]["high"] == 0.25


# --- HTML ----------------------------------------------------------------------------

def test_render_embeds_data_and_sections():
    html = render_dashboard([rec(0, **GOOD), rec(1, **GOOD)])
    for heading in ("HRT and falling phrase endings", "Mean pitch per recording", "Latest vs best-ever",
                    "Progress flags", "All recordings"):
        assert heading in html
    assert len(embedded(html)["records"]) == 2
    assert "/*__DATA__*/" not in html
    assert "<script src" not in html and "https://" not in html  # fully offline


def test_hostile_names_cannot_break_out_of_script():
    name = "</script><img src=x onerror=alert(1)>" + chr(0x2028)
    hostile = Record(0, T0, name, "s", 1, None, 60.0, "autocorr", "neutral", GOOD, {})
    html = render_dashboard([hostile])
    data_line = html[html.index("const D = "):].split("\n", 1)[0]
    assert "</script>" not in data_line and "<img" not in data_line
    assert chr(0x2028) not in html  # a raw U+2028 would end a JS line early in old engines
    assert embedded(html)["records"][0]["label"] == name
    assert "innerHTML" not in html  # all data reaches the DOM via textContent


def test_empty_history_renders():
    html = render_dashboard([])
    assert embedded(html)["records"] == [] and embedded(html)["best"] is None


def test_template_ships_in_package():
    from importlib import resources
    assert resources.files("accent_analyzer.dashboard").joinpath("template.html").is_file()


# --- CLI -----------------------------------------------------------------------------

def test_cli_dashboard(tmp_path, nze, ame):
    db = tmp_path / "h.db"
    with HistoryStore(db) as store:
        store.add(nze, name="first", recorded_at=T0)
        store.add(ame, name="second", recorded_at=T0 + timedelta(days=1))
    out = tmp_path / "dash.html"
    result = CliRunner().invoke(cli, ["dashboard", "--history", str(db), "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert "(2 recordings)" in result.output
    data = embedded(out.read_text())
    assert [r["label"] for r in data["records"]] == ["first", "second"]
    assert data["best"] == 1


def test_cli_dashboard_errors(tmp_path):
    runner = CliRunner()
    assert "Give --history" in runner.invoke(cli, ["dashboard"]).output
    assert "No history file" in runner.invoke(cli, ["dashboard", "--history", str(tmp_path / "x.db")]).output
