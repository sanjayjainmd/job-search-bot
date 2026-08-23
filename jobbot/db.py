"""SQLite state: what we've seen, and per-source health history."""
from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .config import DB_PATH
from .models import Job


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(path: Path | None = None) -> None:
    with closing(connect(path)) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS seen_jobs (
                dedup_key  TEXT PRIMARY KEY,
                title      TEXT NOT NULL,
                company    TEXT NOT NULL,
                url        TEXT,
                location   TEXT,
                source     TEXT,
                score      INTEGER,
                fit        TEXT,
                reason     TEXT,
                hook       TEXT,
                first_seen TEXT NOT NULL,
                notified   INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS source_runs (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                run_ts   TEXT NOT NULL,
                runner   TEXT NOT NULL,
                source   TEXT NOT NULL,
                count    INTEGER NOT NULL,
                ok       INTEGER NOT NULL DEFAULT 1,
                note     TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_source_runs_source
                ON source_runs (source, id DESC);
            """
        )
        conn.commit()


def known_keys(keys: Iterable[str]) -> set[str]:
    """Return the subset of keys already in the database."""
    keys = list(keys)
    if not keys:
        return set()
    found: set[str] = set()
    with closing(connect()) as conn:
        # Chunked to stay under SQLite's variable limit.
        for i in range(0, len(keys), 500):
            chunk = keys[i : i + 500]
            placeholders = ",".join("?" * len(chunk))
            rows = conn.execute(
                f"SELECT dedup_key FROM seen_jobs WHERE dedup_key IN ({placeholders})",
                chunk,
            ).fetchall()
            found.update(r["dedup_key"] for r in rows)
    return found


def record_job(job: Job, notified: bool) -> None:
    with closing(connect()) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO seen_jobs
                (dedup_key, title, company, url, location, source,
                 score, fit, reason, hook, first_seen, notified)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                job.dedup_key, job.title, job.company, job.url, job.location,
                job.source, job.score, job.fit, job.reason, job.hook,
                _now(), int(notified),
            ),
        )
        conn.commit()


def record_source_run(runner: str, source: str, count: int, ok: bool = True,
                      note: str = "") -> None:
    with closing(connect()) as conn:
        conn.execute(
            "INSERT INTO source_runs (run_ts, runner, source, count, ok, note)"
            " VALUES (?,?,?,?,?,?)",
            (_now(), runner, source, count, int(ok), note),
        )
        conn.commit()


def zero_streak(source: str, limit: int = 10) -> int:
    """How many consecutive most-recent runs returned nothing for this source."""
    with closing(connect()) as conn:
        rows = conn.execute(
            "SELECT count FROM source_runs WHERE source = ? ORDER BY id DESC LIMIT ?",
            (source, limit),
        ).fetchall()
    streak = 0
    for row in rows:
        if row["count"] == 0:
            streak += 1
        else:
            break
    return streak
