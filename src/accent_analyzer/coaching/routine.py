"""Daily 5-minute drill routine, streaks and the weekly summary.

The routine is deterministic for a given day: the focus drill rotates through the
weekday, the 10 target words rotate through your accent's word lists, and the
reading passage rotates too, so every day is a little different but repeatable.
"""

from __future__ import annotations

import math
import tomllib
from datetime import date, timedelta
from functools import cache
from importlib import resources

from accent_analyzer.coaching.engine import recommend
from accent_analyzer.coaching.library import load_library

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
# Every level is the same 5 minutes; levels change how much material and how it's said.
LEVELS = {
    "beginner": {"sentences": 2, "note": "Go slowly and exaggerate every movement; accuracy over speed."},
    "intermediate": {"sentences": 3, "note": "Exaggerate first, then repeat at a natural pace."},
    "advanced": {"sentences": 5, "note": "Natural speed throughout; aim for consistent, subtle falls."},
}
BASE_MINUTES = {"warmup": 1.0, "focus": 2.0, "words": 1.0, "record": 1.0}
# Word lists for the target-words step, by accent. Planned-detection modules supply the words.
ACCENT_WORD_MODULES = {
    "nze": ("tflap", "rhotic", "vowels"),
    "aue": ("tflap", "rhotic", "vowels"),
    "british": ("tflap", "rhotic", "dark_l"),
    "indian": ("tflap", "dark_l"),
}
DEFAULT_WORD_MODULES = ("tflap", "rhotic")
N_WORDS = 10


@cache
def passages() -> list[dict]:
    text = resources.files("accent_analyzer.coaching").joinpath("prompts.toml").read_text(encoding="utf-8")
    return [{**p, "text": " ".join(p["text"].split())} for p in tomllib.loads(text)["passage"]]


def date_for_weekday(name: str, today: date | None = None) -> date:
    """This week's date for a weekday name (weeks start on Monday)."""
    today = today or date.today()
    idx = WEEKDAYS.index(name.lower())
    return today - timedelta(days=today.weekday()) + timedelta(days=idx)


def _word_pool(accent: str | None) -> list[str]:
    library = load_library()
    pool = []
    for module_id in ACCENT_WORD_MODULES.get(accent, DEFAULT_WORD_MODULES):
        for entry in library[module_id].words:
            # Vowel entries look like "KIT: fish, chip, fit"; split them into words.
            words = entry.split(":", 1)[1].split(",") if ":" in entry else [entry]
            pool += [w.strip() for w in words if w.strip()]
    seen = set()
    return [w for w in pool if not (w in seen or seen.add(w))]


def build_routine(day: date, level: str = "intermediate", metrics: dict | None = None,
                  accent: str | None = None) -> dict:
    if level not in LEVELS:
        raise ValueError(f"Unknown level {level!r}; choose from {', '.join(LEVELS)}")
    library = load_library()
    measured = [r for r in recommend(metrics, limit=None) if r.source == "measured"] if metrics else []
    focus = measured[0].module if measured else library["hrt"]
    reason = "; ".join(measured[0].reasons) if measured else "HRT is the core habit; it's the default focus until you record"
    weekday = day.weekday()
    drill = focus.drills[weekday % len(focus.drills)]
    warm = library["range"].drills[0]
    pool = _word_pool(accent)
    start = (day.toordinal() * N_WORDS) % len(pool)
    words = [pool[(start + i) % len(pool)] for i in range(min(N_WORDS, len(pool)))]
    passage = passages()[day.toordinal() % len(passages())]
    mins = BASE_MINUTES
    steps = [
        {"id": "warmup", "title": f"Warm-up: {warm.name}", "minutes": mins["warmup"], "steps": list(warm.steps)},
        {"id": "focus", "title": f"Focus: {drill.name}", "module": focus.id, "minutes": mins["focus"],
         "steps": list(drill.steps), "items": list(focus.examples[: LEVELS[level]["sentences"]])},
        {"id": "words", "title": "Your 10 target words", "minutes": mins["words"],
         "steps": ["Say each word twice: slowly and exaggerated, then at normal speed."], "items": words},
        {"id": "record", "title": f"Record: {passage['title']}", "minutes": mins["record"],
         "steps": ["Read the passage once, using what you just practiced."], "passage": passage["id"]},
    ]
    return {
        "date": day.isoformat(),
        "weekday": WEEKDAYS[weekday].capitalize(),
        "level": level,
        "note": LEVELS[level]["note"],
        "focus": {"id": focus.id, "name": focus.name, "reason": reason},
        "steps": steps,
        "words": words,
        "minutes": round(sum(s["minutes"] for s in steps), 1),
    }


def streak(days: set[date], today: date | None = None) -> int:
    """Consecutive practice days ending today (or yesterday, if today isn't done yet)."""
    today = today or date.today()
    cur = today if today in days else today - timedelta(days=1)
    n = 0
    while cur in days:
        n += 1
        cur -= timedelta(days=1)
    return n


# metric, label, which way is better (+1 higher, -1 lower, 0 neutral), formatter
TREND_METRICS = (
    ("hrt_rate", "HRT", -1, lambda v: f"{v:.0%}"),
    ("high_onset_rate", "HIGH onsets", +1, lambda v: f"{v:.0%}"),
    ("range_ratio", "range", +1, lambda v: f"{v:.2f}×"),
    ("mean_f0", "mean pitch", 0, lambda v: f"{v:.0f} Hz"),
)


def _ok(v) -> bool:
    return v is not None and not (isinstance(v, float) and math.isnan(v))


def weekly_summary(records: list, drill_days: set[date], today: date | None = None) -> dict:
    """The last 7 days: practice days, recordings, and how key metrics moved."""
    today = today or date.today()
    week = [today - timedelta(days=6 - i) for i in range(7)]
    in_week = [r for r in records if week[0] <= r.recorded_at.date() <= today]
    strip = [{"date": d.isoformat(), "weekday": WEEKDAYS[d.weekday()][:3].capitalize(),
              "drill": d in drill_days, "recordings": sum(r.recorded_at.date() == d for r in in_week)}
             for d in week]
    active = sum(1 for s in strip if s["drill"] or s["recordings"])
    trends, lines = [], []
    for key, label, better, fmt in TREND_METRICS:
        vals = [r.get(key) for r in in_week if _ok(r.get(key))]
        if len(vals) < 2:
            continue
        first, last = vals[0], vals[-1]
        delta = last - first
        verdict = "steady" if abs(delta) < 1e-9 or better == 0 else ("better" if delta * better > 0 else "worse")
        trends.append({"metric": key, "label": label, "first": first, "last": last, "verdict": verdict})
        lines.append(f"{label} {fmt(first)} → {fmt(last)}" + ("" if better == 0 else f" ({verdict})"))
    headline = f"Practiced {active} of the last 7 days, {len(in_week)} recording{'s' if len(in_week) != 1 else ''}."
    if lines:
        headline += " " + "; ".join(lines) + "."
    elif in_week:
        headline += " Record at least twice in a week to see trends."
    return {"days": strip, "active_days": active, "recordings": len(in_week),
            "trends": trends, "headline": headline, "streak": streak(drill_days, today)}
