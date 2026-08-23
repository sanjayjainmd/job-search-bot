"""SQLite state: what we've seen, its status, and per-source health history.

The database is committed to the (private) repo rather than kept in a CI cache,
so state is durable, inspectable locally, and versioned.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional

from .config import DB_PATH
from .models import Job

STATUSES = ("new", "seen", "applied", "dismissed")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_columns(conn: sqlite3.Connection) -> None:
    """Additive migration, so an existing database is never rebuilt."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(seen_jobs)")}
    if "status" not in cols:
        conn.execute(
            "ALTER TABLE seen_jobs ADD COLUMN status TEXT NOT NULL DEFAULT 'new'")
    if "tier" not in cols:
        conn.execute("ALTER TABLE seen_jobs ADD COLUMN tier TEXT")
    if "posted_at" not in cols:
        conn.execute("ALTER TABLE seen_jobs ADD COLUMN posted_at TEXT")


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
        _ensure_columns(conn)
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
            chunk = keys[i: i + 500]
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
                 score, fit, reason, hook, first_seen, notified, status, tier,
                 posted_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                job.dedup_key, job.title, job.company, job.url, job.location,
                job.source, job.score, job.fit, job.reason, job.hook,
                _now(), int(notified), "new", job.meta.get("tier", "primary"),
                job.posted_at,
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


# --- status tracking -------------------------------------------------------

def all_jobs() -> List[dict]:
    """Every job ever recorded, newest first. Powers the board."""
    with closing(connect()) as conn:
        rows = conn.execute(
            "SELECT * FROM seen_jobs ORDER BY"
            " (posted_at IS NULL), posted_at DESC, first_seen DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def find_by_ref(ref: str) -> Optional[dict]:
    """Look a job up by the short reference shown in the board and CLI."""
    ref = (ref or "").strip().lower()
    if len(ref) < 4:
        return None
    with closing(connect()) as conn:
        rows = conn.execute(
            "SELECT * FROM seen_jobs WHERE dedup_key LIKE ? LIMIT 2", (ref + "%",)
        ).fetchall()
    return dict(rows[0]) if len(rows) == 1 else None


def set_status(dedup_key: str, status: str) -> bool:
    if status not in STATUSES:
        raise ValueError(f"status must be one of {', '.join(STATUSES)}")
    with closing(connect()) as conn:
        cur = conn.execute(
            "UPDATE seen_jobs SET status = ? WHERE dedup_key = ?", (status, dedup_key))
        conn.commit()
        return cur.rowcount > 0


def set_status_all(from_status: str, to_status: str) -> int:
    if to_status not in STATUSES:
        raise ValueError(f"status must be one of {', '.join(STATUSES)}")
    with closing(connect()) as conn:
        cur = conn.execute(
            "UPDATE seen_jobs SET status = ? WHERE status = ?", (to_status, from_status))
        conn.commit()
        return cur.rowcount


def status_counts() -> dict[str, int]:
    with closing(connect()) as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) c FROM seen_jobs GROUP BY status").fetchall()
    counts = {s: 0 for s in STATUSES}
    for row in rows:
        counts[row["status"]] = row["c"]
    return counts


def stats() -> dict:
    """Everything needed to answer: is dedup actually working?"""
    with closing(connect()) as conn:
        total = conn.execute("SELECT COUNT(*) c FROM seen_jobs").fetchone()["c"]
        notified = conn.execute(
            "SELECT COUNT(*) c FROM seen_jobs WHERE notified = 1").fetchone()["c"]
        span = conn.execute(
            "SELECT MIN(first_seen) lo, MAX(first_seen) hi FROM seen_jobs").fetchone()
        by_day = conn.execute(
            "SELECT substr(first_seen,1,10) d, COUNT(*) c FROM seen_jobs"
            " GROUP BY d ORDER BY d DESC LIMIT 14").fetchall()
        runs = conn.execute(
            "SELECT run_ts, runner, source, count FROM source_runs"
            " ORDER BY id DESC LIMIT 12").fetchall()
    return {
        "total": total,
        "notified": notified,
        "first": span["lo"],
        "last": span["hi"],
        "by_day": [(r["d"], r["c"]) for r in by_day],
        "runs": [(r["run_ts"], r["runner"], r["source"], r["count"]) for r in runs],
        "statuses": status_counts(),
    }


def is_empty() -> bool:
    """True if we have no memory of any job - i.e. everything will re-send."""
    with closing(connect()) as conn:
        return conn.execute("SELECT COUNT(*) c FROM seen_jobs").fetchone()["c"] == 0
