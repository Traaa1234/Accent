"""SQLite session history.

One row per analyzed recording. Headline metrics are real columns (sortable,
queryable); the full metric set and the phrase-end / onset distributions are
stored as JSON so new metrics never need a migration.
"""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

SCHEMA_VERSION = 1
COLUMNS = (
    "hrt_rate", "fall_rate", "mean_f0", "std_f0", "range_ratio",
    "voiced_ratio", "high_onset_rate", "low_onset_rate", "n_phrase_ends",
)

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS recordings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at TEXT NOT NULL,
    name TEXT,
    session TEXT NOT NULL,
    take INTEGER NOT NULL,
    source TEXT,
    duration REAL,
    pitch_method TEXT,
    register_label TEXT,
    {", ".join(f"{c} REAL" for c in COLUMNS)},
    metrics TEXT NOT NULL,
    details TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS recordings_time ON recordings (recorded_at);
CREATE INDEX IF NOT EXISTS recordings_session ON recordings (session, take);
"""


def _clean(obj):
    """NaN -> None so the JSON is standard."""
    if isinstance(obj, float) and math.isnan(obj):
        return None
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    return obj


def _nan(value):
    return float("nan") if value is None else value


@dataclass(frozen=True)
class Record:
    id: int
    recorded_at: datetime
    name: str | None
    session: str
    take: int
    source: str | None
    duration: float
    pitch_method: str
    register_label: str
    metrics: dict = field(repr=False)
    details: dict = field(repr=False)

    @property
    def label(self) -> str:
        return self.name or f"{self.recorded_at:%Y-%m-%d %H:%M}"

    def get(self, key: str) -> float:
        return _nan(self.metrics.get(key))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "recorded_at": self.recorded_at.isoformat(timespec="seconds"),
            "name": self.name,
            "label": self.label,
            "session": self.session,
            "take": self.take,
            "source": self.source,
            "duration": self.duration,
            "pitch_method": self.pitch_method,
            "register_label": self.register_label,
            "metrics": _clean(self.metrics),
        }


def _details(result) -> dict:
    p = result.phrasing.primary
    return {
        "phrase_end_deltas": [round(e.delta, 1) for e in p.ends],
        "phrase_end_magnitudes": p.magnitude_counts(),
        "onset_ratios": [round(o.ratio, 3) for o in p.onsets],
        "onset_distribution": {
            "high": p.high_onset_rate, "mid": p.mid_onset_rate, "low": p.low_onset_rate,
        },
        "by_threshold": {f"{t:.2f}": a.summary() for t, a in result.phrasing.by_threshold.items()},
        "windows": result.windows.summary(),
        "findings": [f.to_dict() for f in result.findings],
        "pitch_params": result.track.params,
    }


class HistoryStore:
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise RuntimeError(f"{self.path} was written by a newer accent-analyzer (schema {version})")
        self._conn.executescript(_SCHEMA)
        self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> HistoryStore:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def add(
        self,
        result,
        name: str | None = None,
        session: str | None = None,
        recorded_at: datetime | None = None,
    ) -> Record:
        recorded_at = recorded_at or datetime.now()
        session = session or f"{recorded_at:%Y-%m-%d}"
        take = 1 + self._conn.execute(
            "SELECT COUNT(*) FROM recordings WHERE session = ?", (session,)
        ).fetchone()[0]
        metrics = _clean(result.metrics())
        cols = ", ".join(COLUMNS)
        marks = ", ".join("?" for _ in COLUMNS)
        cur = self._conn.execute(
            f"""INSERT INTO recordings
                (recorded_at, name, session, take, source, duration, pitch_method, register_label,
                 {cols}, metrics, details)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, {marks}, ?, ?)""",
            (
                recorded_at.isoformat(timespec="seconds"), name, session, take, result.source,
                result.duration, result.track.method, result.register_label,
                *(metrics.get(c) for c in COLUMNS),
                json.dumps(metrics), json.dumps(_clean(_details(result))),
            ),
        )
        self._conn.commit()
        return self.get(cur.lastrowid)

    @staticmethod
    def _record(row: sqlite3.Row) -> Record:
        return Record(
            id=row["id"],
            recorded_at=datetime.fromisoformat(row["recorded_at"]),
            name=row["name"],
            session=row["session"],
            take=row["take"],
            source=row["source"],
            duration=row["duration"],
            pitch_method=row["pitch_method"],
            register_label=row["register_label"],
            metrics=json.loads(row["metrics"]),
            details=json.loads(row["details"]),
        )

    def get(self, record_id: int) -> Record:
        row = self._conn.execute("SELECT * FROM recordings WHERE id = ?", (record_id,)).fetchone()
        if row is None:
            raise KeyError(record_id)
        return self._record(row)

    def all(self) -> list[Record]:
        """All recordings, oldest first."""
        rows = self._conn.execute("SELECT * FROM recordings ORDER BY recorded_at, id")
        return [self._record(r) for r in rows]

    def last(self, n: int) -> list[Record]:
        """The latest `n` recordings, oldest first."""
        rows = self._conn.execute(
            "SELECT * FROM (SELECT * FROM recordings ORDER BY recorded_at DESC, id DESC LIMIT ?) "
            "ORDER BY recorded_at, id",
            (n,),
        )
        return [self._record(r) for r in rows]

    def session(self, session: str) -> list[Record]:
        rows = self._conn.execute("SELECT * FROM recordings WHERE session = ? ORDER BY take", (session,))
        return [self._record(r) for r in rows]

    def trajectory(self, keys: tuple[str, ...] = COLUMNS, last: int | None = None) -> list[dict]:
        """Rows of {id, label, recorded_at, <metric>...}, oldest first."""
        records = self.last(last) if last else self.all()
        return [
            {"id": r.id, "label": r.label, "recorded_at": r.recorded_at.isoformat(timespec="seconds"),
             **{k: r.get(k) for k in keys}}
            for r in records
        ]

    def __len__(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM recordings").fetchone()[0]
