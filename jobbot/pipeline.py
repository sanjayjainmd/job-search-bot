"""Shared pipeline. Both runners call run() with a different set of sources."""
from __future__ import annotations

import re
from typing import Callable, List, Tuple

from . import canary, config, db, notify
from .models import Job
from .score import score_job

# A source is (name, callable -> (jobs, errors))
Source = Tuple[str, Callable[[], Tuple[List[Job], List[str]]]]


def _term_in(term: str, text: str) -> bool:
    """Whole-word match. Substring matching wrongly drops 'Internal Audit'
    on the term 'intern', and 'Disaster Recovery' on 'sr'."""
    return re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text) is not None


def _title_allowed(title: str) -> bool:
    low = (title or "").lower()
    excludes = [t.lower() for t in config.FILTERS.get("title_exclude", [])]
    if any(_term_in(term, low) for term in excludes):
        return False
    includes = [t.lower() for t in config.FILTERS.get("title_include", [])]
    if not includes:
        return True
    return any(_term_in(term, low) for term in includes)


def _location_allowed(job: Job) -> bool:
    if not config.TARGETS.get("location_is_hard_filter", False):
        return True
    loc = (job.location or "").lower()
    if not loc:
        return True  # unknown location: let the LLM judge rather than dropping it
    if config.TARGETS.get("remote_ok", True) and "remote" in loc:
        return True
    wanted = [w.lower() for w in config.TARGETS.get("locations", [])]
    return any(w in loc for w in wanted)


def run(runner: str, sources: List[Source]) -> int:
    """Collect, filter, dedup, score, deliver. Returns the count sent."""
    db.init_db()
    print(f"\n=== {runner} run ===")

    collected: List[Job] = []
    stats: dict[str, int] = {}
    errors: List[str] = []

    for name, fetch in sources:
        print(f"-> {name} ...")
        try:
            jobs, errs = fetch()
        except Exception as exc:  # a broken source must not kill the run
            jobs, errs = [], [f"{name}: unhandled error: {exc}"]
        jobs = [j for j in jobs if j.is_valid()]
        stats[name] = len(jobs)
        errors.extend(errs)
        collected.extend(jobs)
        db.record_source_run(runner, name, len(jobs), ok=not errs,
                             note="; ".join(errs)[:500])
        print(f"   {len(jobs)} postings" + (f", {len(errs)} error(s)" if errs else ""))

    # Keyword gate first - it is free, and it keeps LLM spend proportionate.
    relevant = [j for j in collected if _title_allowed(j.title) and _location_allowed(j)]
    print(f"\n{len(collected)} collected -> {len(relevant)} pass keyword filters")

    # Collapse duplicates within this batch (same role on two boards).
    unique: dict[str, Job] = {}
    for job in relevant:
        unique.setdefault(job.dedup_key, job)

    already = db.known_keys(unique.keys())
    fresh = [j for k, j in unique.items() if k not in already]
    print(f"{len(unique)} unique -> {len(fresh)} not seen before")

    if config.SCORING_ENABLED and fresh:
        print(f"\nScoring {len(fresh)} job(s) with {config.LLM_MODEL} ...")
        for job in fresh:
            score_job(job)

    if config.SCORING_ENABLED:
        to_send = [j for j in fresh if (j.score or 0) >= config.MIN_SCORE]
        held = len(fresh) - len(to_send)
        if held:
            print(f"{held} scored below {config.MIN_SCORE} - recorded, not sent")
    else:
        to_send = fresh
        if fresh:
            print("Scoring disabled (no LLM_API_KEY) - sending everything that passed filters")

    cap = int(config.CFG.get("delivery", {}).get("max_send_per_run", 25))
    held_for_later: List[Job] = []
    if cap and len(to_send) > cap:
        to_send.sort(key=lambda j: (j.score is None, -(j.score or 0)))
        held_for_later = to_send[cap:]
        to_send = to_send[:cap]
        print(f"{len(held_for_later)} over the per-run cap of {cap} - they arrive next run")

    warnings = canary.check(stats)
    if held_for_later:
        warnings.append(
            f"{len(held_for_later)} more matched but were held back by the "
            f"per-run cap of {cap}; they will arrive on the next run."
        )
    for err in errors[:10]:
        warnings.append(err)

    delivered = notify.deliver(to_send, warnings, runner, stats)

    # Only mark jobs seen once delivery succeeded, so a failed send retries
    # next run instead of silently swallowing the job.
    if config.DRY_RUN:
        # A dry run must not consume the backlog, or the first real digest
        # would arrive empty with no visible reason.
        print("  (dry run - nothing marked as seen)")
    elif delivered:
        held_keys = {j.dedup_key for j in held_for_later}
        for job in fresh:
            if job.dedup_key in held_keys:
                continue  # leave unseen so the next run picks it up
            db.record_job(job, notified=job in to_send)
    elif not delivered:
        print("  ! delivery failed - not marking jobs as seen; they retry next run")

    print(f"\n=== {runner} done: {len(to_send)} sent ===\n")
    return len(to_send)
