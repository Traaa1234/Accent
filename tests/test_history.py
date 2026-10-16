import json
import math
import sqlite3
from datetime import datetime, timedelta

import pytest
import soundfile as sf
from click.testing import CliRunner

from accent_analyzer.analyzer import cli
from accent_analyzer.history import HistoryStore, Record, progression
from accent_analyzer.history.progression import (
    complacency_regression,
    fatigue,
    integration_milestone,
    register_deflation,
    register_independence,
)
import synth

T0 = datetime(2026, 10, 1, 8, 0)


def recs(rows: list[dict]) -> list[Record]:
    """Records from metric dicts; optional 'session' and 'register' keys."""
    out, takes = [], {}
    for i, m in enumerate(rows):
        session = m.pop("session", f"day{i}")
        takes[session] = takes.get(session, 0) + 1
        register = m.pop("register", "neutral")
        out.append(Record(i + 1, T0 + timedelta(days=i), None, session, takes[session], None, 60.0,
                          "autocorr", register, {"n_phrase_ends": 20, **m}, {}))
    return out


# --- store -------------------------------------------------------------------------

def test_add_and_read_back(tmp_path, nze, ame):
    with HistoryStore(tmp_path / "h.db") as store:
        a = store.add(nze, name="Monday", recorded_at=T0)
        b = store.add(ame, recorded_at=T0 + timedelta(hours=1))
        assert len(store) == 2
        assert (a.session, a.take, b.take) == ("2026-10-01", 1, 2)
        assert a.name == "Monday" and a.label == "Monday"
        assert b.label == "2026-10-01 09:00"
        assert a.register_label == "calm"
        assert a.get("hrt_rate") == pytest.approx(nze.metrics()["hrt_rate"])
        assert a.details["phrase_end_magnitudes"] == nze.phrasing.primary.magnitude_counts()
        assert len(a.details["phrase_end_deltas"]) == nze.phrasing.primary.n_ends
        assert set(a.details["by_threshold"]) == {"0.20", "0.12"}


def test_ordering_queries_and_persistence(tmp_path, nze, ame):
    path = tmp_path / "h.db"
    with HistoryStore(path) as store:
        # Inserted out of order: queries sort by recording time.
        for day, result in ((3, nze), (1, ame), (2, nze), (4, ame)):
            store.add(result, name=f"d{day}", recorded_at=T0 + timedelta(days=day))
    with HistoryStore(path) as store:
        assert [r.name for r in store.all()] == ["d1", "d2", "d3", "d4"]
        assert [r.name for r in store.last(2)] == ["d3", "d4"]
        traj = store.trajectory(("hrt_rate", "mean_f0"), last=3)
        assert [t["label"] for t in traj] == ["d2", "d3", "d4"]
        assert set(traj[0]) == {"id", "label", "recorded_at", "hrt_rate", "mean_f0"}
        assert store.session((T0 + timedelta(days=2)).strftime("%Y-%m-%d"))[0].name == "d2"


def test_sortable_columns(tmp_path, nze, ame):
    path = tmp_path / "h.db"
    with HistoryStore(path) as store:
        store.add(nze, name="nze", recorded_at=T0)
        store.add(ame, name="ame", recorded_at=T0)
    rows = sqlite3.connect(path).execute("SELECT name FROM recordings ORDER BY hrt_rate").fetchall()
    assert [r[0] for r in rows] == ["ame", "nze"]


def test_nan_metrics_round_trip(tmp_path, short):
    with HistoryStore(tmp_path / "h.db") as store:
        r = store.add(short)
        raw = store._conn.execute("SELECT metrics FROM recordings").fetchone()[0]
    assert "NaN" not in raw  # strict JSON
    nan_keys = [k for k, v in short.metrics().items() if isinstance(v, float) and math.isnan(v)]
    for k in nan_keys:
        assert math.isnan(r.get(k))


def test_newer_schema_rejected(tmp_path):
    path = tmp_path / "h.db"
    HistoryStore(path).close()
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA user_version = 99")
    conn.commit()
    conn.close()
    with pytest.raises(RuntimeError, match="newer"):
        HistoryStore(path)


# --- progression rules ---------------------------------------------------------------

@pytest.mark.parametrize("f0s,fires", [
    ([200, 185, 170, 160], True),     # 3 drops, 40 Hz
    ([210, 200, 185, 170], True),
    ([200, 190, 185], False),         # only 15 Hz
    ([200, 170, 180, 160], False),    # trailing run is 2 recordings
    ([170, 160, 150, 165], False),    # latest recovered
])
def test_register_deflation(f0s, fires):
    f = register_deflation(recs([{"mean_f0": v} for v in f0s]))
    assert (f is not None) == fires
    if fires:
        assert f.severity == "warning" and "Hz" in f.message


@pytest.mark.parametrize("hrts,fires", [
    ([0.5, 0.2, 0.3, 0.4], True),         # breakthrough, then two climbs
    ([0.2, 0.35, 0.3, 0.4, 0.5], True),   # climb starts after an earlier breakthrough
    ([0.5, 0.4, 0.45, 0.5], False),       # never had a breakthrough
    ([0.4, 0.2, 0.3], False),             # only one climb
    ([0.2, 0.3, 0.4, 0.35], False),       # latest improved
])
def test_complacency_regression(hrts, fires):
    assert (complacency_regression(recs([{"hrt_rate": v} for v in hrts])) is not None) == fires


def test_integration_milestone_first_and_again():
    hit = {"hrt_rate": 0.2, "high_onset_rate": 0.5, "range_ratio": 2.8}
    miss = {"hrt_rate": 0.4, "high_onset_rate": 0.5, "range_ratio": 2.8}
    assert "First" in integration_milestone(recs([dict(miss), dict(hit)])).message
    assert "again (2" in integration_milestone(recs([dict(hit), dict(miss), dict(hit)])).message
    assert integration_milestone(recs([dict(hit), dict(miss)])) is None


def test_fatigue_within_session():
    take1 = {"hrt_rate": 0.2, "high_onset_rate": 0.5, "range_ratio": 2.6, "std_f0": 60, "mean_f0": 180}
    tired = {"hrt_rate": 0.4, "high_onset_rate": 0.3, "range_ratio": 2.5, "std_f0": 55, "mean_f0": 175}
    f = fatigue(recs([{**take1, "session": "s"}, {**tired, "session": "s"}]))
    assert f.severity == "warning" and "HRT 20% → 40%" in f.message and "HIGH onsets" in f.message
    # Same drop across sessions is not fatigue.
    assert fatigue(recs([{**take1, "session": "a"}, {**tired, "session": "b"}])) is None
    # A single degraded metric is not enough.
    one = {**take1, "hrt_rate": 0.4}
    assert fatigue(recs([{**take1, "session": "s"}, {**one, "session": "s"}])) is None


def test_fatigue_compares_latest_take_with_first():
    t = {"hrt_rate": 0.2, "high_onset_rate": 0.5, "range_ratio": 2.6, "std_f0": 60, "mean_f0": 180}
    bad = {**t, "hrt_rate": 0.45, "std_f0": 40}
    f = fatigue(recs([{**t, "session": "s"}, {**t, "session": "s"}, {**bad, "session": "s"}]))
    assert "take 3" in f.message


def _reg(register, hrt, n=20):
    return {"register": register, "hrt_rate": hrt, "n_phrase_ends": n}


def test_register_independence():
    robust = register_independence(recs([_reg("animated", 0.1), _reg("calm", 0.2)]))
    assert robust.severity == "good" and "Robust" in robust.message
    fragile = register_independence(recs([_reg("animated", 0.1), _reg("calm", 0.5), _reg("calm", 0.4)]))
    assert fragile.severity == "warning" and "Fragile" in fragile.message
    untested = register_independence(recs([_reg("animated", 0.1), _reg("neutral", 0.5)]))
    assert untested.severity == "info"
    # Recordings with too few phrase endings don't count.
    assert register_independence(recs([_reg("animated", 0.1, n=4), _reg("calm", 0.5, n=4)])) is None


def test_progression_combines_rules():
    rows = [{"mean_f0": f, "hrt_rate": h, "register": "animated"} for f, h in
            ((220, 0.5), (200, 0.2), (185, 0.3), (170, 0.4))]
    codes = {f.code for f in progression(recs(rows))}
    assert {"register_deflation", "complacency_regression"} <= codes


# --- CLI -----------------------------------------------------------------------------

@pytest.fixture
def takes(tmp_path):
    nze, ame = tmp_path / "nze.wav", tmp_path / "ame.wav"
    sf.write(nze, synth.nze_like(), synth.SR)
    sf.write(ame, synth.ame_like(), synth.SR)
    return nze, ame


def test_cli_analyze_with_history(tmp_path, takes):
    nze, ame = takes
    db, report = tmp_path / "h.db", tmp_path / "r.html"
    runner = CliRunner()
    first = runner.invoke(cli, ["analyze", str(ame), "--history", str(db), "--name", "Mon",
                                "--date", "2026-10-01 08:00", "--session", "s1"])
    assert first.exit_code == 0, first.output
    assert "Progress  (1 recordings in history)" in first.output
    second = runner.invoke(cli, ["analyze", str(nze), "--history", str(db), "--name", "Mon take 2",
                                 "--date", "2026-10-01 08:10", "--session", "s1", "-o", str(report), "--json"])
    assert second.exit_code == 0, second.output
    data = json.loads(second.stdout)
    assert data["history"]["take"] == 2
    assert "fatigue" in {f["code"] for f in data["history"]["progress"]}
    html = report.read_text()
    assert "Compared with previous sessions" in html and "Fatigue pattern" in html
    assert html.count("<picture>") == 5  # four charts + trajectory


def test_cli_history_command(tmp_path, takes):
    nze, ame = takes
    db = tmp_path / "h.db"
    runner = CliRunner()
    for i, path in enumerate((nze, ame, nze)):
        r = runner.invoke(cli, ["analyze", str(path), "--history", str(db), "--date", f"2026-10-0{i + 1} 08:00"])
        assert r.exit_code == 0, r.output
    table = runner.invoke(cli, ["history", "--history", str(db), "--last", "2"])
    assert table.exit_code == 0, table.output
    lines = table.output.splitlines()
    assert "HRT" in lines[0] and len([l for l in lines if l.strip().startswith(("2 ", "3 "))]) == 2
    assert "Progress  (3 recordings in history)" in table.output
    data = json.loads(runner.invoke(cli, ["history", "--history", str(db), "--json"]).output)
    assert len(data["recordings"]) == 3 and data["recordings"][0]["metrics"]["hrt_rate"] is not None


def test_cli_history_env_var_and_errors(tmp_path):
    runner = CliRunner()
    assert runner.invoke(cli, ["history"]).exit_code != 0
    missing = runner.invoke(cli, ["history"], env={"ACCENT_HISTORY": str(tmp_path / "none.db")})
    assert missing.exit_code != 0 and "No history file" in missing.output
