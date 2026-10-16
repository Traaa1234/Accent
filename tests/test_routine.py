import json
import sqlite3
from datetime import date, datetime, timedelta

import pytest
import soundfile as sf
from click.testing import CliRunner

from accent_analyzer.analyzer import cli
from accent_analyzer.coaching.routine import (
    build_routine,
    date_for_weekday,
    streak,
    weekly_summary,
)
from accent_analyzer.history import HistoryStore, Record
import synth

DAY = date(2026, 10, 16)  # a Friday
POOR = {"hrt_rate": 0.7, "range_ratio": 1.2, "std_f0": 16, "high_onset_rate": 0.0, "low_onset_rate": 0.0,
        "voiced_ratio": 0.7, "n_phrase_ends": 20}


def test_routine_shape_and_determinism():
    r = build_routine(DAY, "intermediate", POOR, "nze")
    assert r["weekday"] == "Friday" and r["minutes"] == 5
    assert [s["id"] for s in r["steps"]] == ["warmup", "focus", "words", "record"]
    assert len(r["words"]) == 10 and len(set(r["words"])) == 10
    assert r["focus"]["id"] == "hrt" and "HRT 70%" in r["focus"]["reason"]
    assert build_routine(DAY, "intermediate", POOR, "nze") == r


def test_words_and_drills_rotate_by_day():
    a, b = build_routine(DAY, "intermediate", POOR, "nze"), build_routine(DAY + timedelta(days=1), "intermediate", POOR, "nze")
    assert a["words"] != b["words"]
    assert a["steps"][1]["title"] != b["steps"][1]["title"]


def test_levels_keep_five_minutes_but_change_material():
    counts = {lvl: len(build_routine(DAY, lvl, POOR)["steps"][1]["items"]) for lvl in ("beginner", "intermediate", "advanced")}
    assert counts == {"beginner": 2, "intermediate": 3, "advanced": 5}
    assert {build_routine(DAY, lvl)["minutes"] for lvl in counts} == {5}
    with pytest.raises(ValueError):
        build_routine(DAY, "expert")


def test_default_focus_without_recordings():
    r = build_routine(DAY)
    assert r["focus"]["id"] == "hrt" and "default focus" in r["focus"]["reason"]


@pytest.mark.parametrize("accent,expected_word", [("indian", "milk"), ("nze", "fish"), ("british", "car")])
def test_word_pool_follows_accent(accent, expected_word):
    words = set()
    for i in range(30):  # the 10 words rotate; across a month the whole pool appears
        words |= set(build_routine(DAY + timedelta(days=i), accent=accent)["words"])
    assert expected_word in words


def test_date_for_weekday():
    assert date_for_weekday("monday", DAY) == date(2026, 10, 12)
    assert date_for_weekday("Sunday", DAY) == date(2026, 10, 18)


@pytest.mark.parametrize("offsets,expected", [
    ((0, 1, 2), 3),       # done today and the two days before
    ((1, 2, 3), 3),       # not yet today: yesterday's streak is still alive
    ((0, 2, 3), 1),       # gap yesterday
    ((2, 3), 0),          # missed yesterday and today
    ((), 0),
])
def test_streak(offsets, expected):
    assert streak({DAY - timedelta(days=o) for o in offsets}, DAY) == expected


def _rec(i, when, **m):
    return Record(i, when, None, "s", 1, None, 60, "autocorr", "neutral", {"n_phrase_ends": 20, **m}, {})


def test_weekly_summary_trends():
    recs = [
        _rec(1, datetime(2026, 10, 1, 8), hrt_rate=0.9),  # outside the 7-day window
        _rec(2, datetime(2026, 10, 11, 8), hrt_rate=0.6, range_ratio=1.5, high_onset_rate=0.2, mean_f0=170),
        _rec(3, datetime(2026, 10, 15, 8), hrt_rate=0.3, range_ratio=1.4, high_onset_rate=0.2, mean_f0=160),
    ]
    s = weekly_summary(recs, {date(2026, 10, 15), date(2026, 10, 16)}, DAY)
    assert s["recordings"] == 2 and s["active_days"] == 3 and s["streak"] == 2
    verdicts = {t["metric"]: t["verdict"] for t in s["trends"]}
    assert verdicts == {"hrt_rate": "better", "range_ratio": "worse", "high_onset_rate": "steady", "mean_f0": "steady"}
    assert "HRT 60% → 30% (better)" in s["headline"]
    assert [d["drill"] for d in s["days"]][-2:] == [True, True]
    assert s["days"][-1]["weekday"] == "Fri"


def test_weekly_summary_empty():
    s = weekly_summary([], set(), DAY)
    assert s["headline"] == "Practiced 0 of the last 7 days, 0 recordings."


# --- storage ------------------------------------------------------------------------

def test_store_logs_drills_once_per_day(tmp_path):
    with HistoryStore(tmp_path / "h.db") as st:
        st.log_drill(DAY, level="beginner")
        st.log_drill(DAY, level="advanced")  # same day: replaced, not duplicated
        st.log_drill(DAY - timedelta(days=1))
        assert st.drill_days() == {DAY, DAY - timedelta(days=1)}


def test_v1_database_is_upgraded_in_place(tmp_path, nze):
    path = tmp_path / "old.db"
    with HistoryStore(path) as st:
        st.add(nze, name="kept")
    conn = sqlite3.connect(path)
    conn.execute("DROP TABLE drills")
    conn.execute("PRAGMA user_version = 1")
    conn.commit(); conn.close()
    with HistoryStore(path) as st:
        assert [r.name for r in st.all()] == ["kept"]
        st.log_drill(DAY)
        assert st.drill_days() == {DAY}
    assert sqlite3.connect(path).execute("PRAGMA user_version").fetchone()[0] == 2


# --- CLI ----------------------------------------------------------------------------

def test_cli_drill_without_history():
    out = CliRunner().invoke(cli, ["drill", "--day", "monday", "--level", "beginner"])
    assert out.exit_code == 0, out.output
    assert "Monday routine · beginner · 5 minutes" in out.output
    assert "Your 10 target words" in out.output
    assert "Streak" not in out.output


def test_cli_drill_done_needs_history():
    out = CliRunner().invoke(cli, ["drill", "--done"])
    assert out.exit_code != 0 and "--done needs --history" in out.output


def test_cli_drill_with_history(tmp_path, nze):
    db = tmp_path / "h.db"
    with HistoryStore(db) as st:
        st.add(nze, accent="indian")
    runner = CliRunner()
    out = runner.invoke(cli, ["drill", "--history", str(db), "--done"])
    assert out.exit_code == 0, out.output
    assert "Streak: 1 day" in out.output and "Marked as done" in out.output
    data = json.loads(runner.invoke(cli, ["drill", "--history", str(db), "--json"]).output)
    assert data["routine"]["focus"]["id"] == "hrt"  # from the stored NZE metrics
    assert data["week"]["streak"] == 1


def test_cli_shadow_and_compare(tmp_path):
    files = {}
    for name, audio in synth.sentence_takes().items():
        files[name] = tmp_path / f"{name}.wav"
        sf.write(files[name], audio, synth.SR)
    runner = CliRunner()
    sh = runner.invoke(cli, ["shadow", "-r", str(files["ref"]), "-u", str(files["flipped"])])
    assert sh.exit_code == 0, sh.output
    assert "Shadowing score:" in sh.output and "✗" in sh.output and "Drop your pitch" in sh.output
    data = json.loads(runner.invoke(cli, ["shadow", "-r", str(files["ref"]), "-u", str(files["same"]), "--json"]).output)
    assert data["score"] >= 85
    cmp_ = runner.invoke(cli, ["compare", str(files["flipped"]), str(files["same"])])
    assert cmp_.exit_code == 0 and cmp_.output.startswith("Take B sounds more American.")
