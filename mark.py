#!/usr/bin/env python
"""Change a job's status, then regenerate board.html.

    py mark.py                      list everything still marked "new"
    py mark.py 3f9a21bc applied     set one job's status (ref from the board)
    py mark.py --all-seen           mark every "new" job as "seen"
    py mark.py --counts             status totals only

Statuses: new, seen, applied, dismissed.
"""
from __future__ import annotations

import sys

from jobbot import board, db


def _print_counts() -> None:
    counts = db.status_counts()
    print("  " + "   ".join(f"{k}: {v}" for k, v in counts.items()))


def list_new() -> int:
    jobs = [j for j in db.all_jobs() if (j.get("status") or "new") == "new"]
    if not jobs:
        print("Nothing is marked 'new'.")
        _print_counts()
        return 0
    print(f"{len(jobs)} job(s) marked 'new':\n")
    for job in jobs:
        score = f"{job['score']:>3}" if job.get("score") is not None else "  -"
        tier = "~" if job.get("tier") == "stretch" else " "
        print(f"  {job['dedup_key'][:8]} {score} {tier} {job['title'][:52]:<52} {job['company']}")
    print()
    print("Set one with:  py mark.py <ref> seen|applied|dismissed")
    _print_counts()
    return 0


def main() -> int:
    db.init_db()
    args = [a for a in sys.argv[1:]]

    if "--counts" in args:
        _print_counts()
        return 0

    if "--all-seen" in args:
        n = db.set_status_all("new", "seen")
        print(f"Marked {n} job(s) as seen.")
        print(f"Board written to {board.write()}")
        return 0

    if not args:
        return list_new()

    if len(args) != 2:
        print(__doc__)
        return 1

    ref, status = args[0], args[1].lower()
    if status not in db.STATUSES:
        print(f"Status must be one of: {', '.join(db.STATUSES)}")
        return 1

    job = db.find_by_ref(ref)
    if not job:
        print(f"No single job matches reference '{ref}'.")
        print("Use at least 4 characters, or run 'py mark.py' to list references.")
        return 1

    db.set_status(job["dedup_key"], status)
    print(f"{job['title']} @ {job['company']}  ->  {status}")
    print(f"Board written to {board.write()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
