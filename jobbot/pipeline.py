"""Shared pipeline. Both runners call run() with a different set of sources.

Filtering is tiered rather than binary. A keyword filter that DROPS a job
loses it silently, and you never find out what you missed - so senior-sounding
titles are demoted into a "Worth a look" section instead of being deleted.
"""
from __future__ import annotations

import os
import re
from typing import Callable, List, Tuple

from . import board, canary, config, db, notify
from .models import Job
from .score import score_job

# A source is (name, callable -> (jobs, errors))
Source = Tuple[str, Callable[[], Tuple[List[Job], List[str]]]]

PRIMARY, STRETCH, REJECT = "primary", "stretch", "reject"


def _term_in(term: str, text: str) -> bool:
    """Whole-word match. Substring matching wrongly drops 'Internal Controls
    Finance Analyst' on the exclude term 'intern'."""
    return re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text) is not None


def _is_small_company(job: Job) -> bool:
    """Company size, judged by open-role count unless explicitly overridden."""
    override = job.meta.get("company_size")
    if override in ("small", "large"):
        return override == "small"
    count = job.meta.get("company_posting_count")
    if count is None:
        return bool(config.TARGETS.get("treat_unknown_size_as_small", True))
    return count <= int(config.TARGETS.get("small_company_max_postings", 120))


def _location_allowed(job: Job) -> bool:
    if not config.TARGETS.get("location_is_hard_filter", False):
        return True
    loc = (job.location or "").lower()
    if not loc:
        return True
    if config.TARGETS.get("remote_ok", True) and "remote" in loc:
        return True
    wanted = [w.lower() for w in config.TARGETS.get("locations", [])]
    return any(w in loc for w in wanted)


def classify(job: Job) -> str:
    """PRIMARY, STRETCH or REJECT. Only REJECT loses the job."""
    low = (job.title or "").lower()

    excludes = [t.lower() for t in config.FILTERS.get("title_exclude", [])]
    if any(_term_in(t, low) for t in excludes):
        return REJECT

    includes = [t.lower() for t in config.FILTERS.get("title_include", [])]
    if includes and not any(_term_in(t, low) for t in includes):
        return REJECT

    if not _location_allowed(job):
        return REJECT

    stretch = [t.lower() for t in config.FILTERS.get("title_stretch", [])]
    if any(_term_in(t, low) for t in stretch):
        # "Head of Finance" at a 20-person startup is the first finance hire.
        # At an 800-person company it is an executive. Same words, different job.
        return PRIMARY if _is_small_company(job) else STRETCH

    return PRIMARY


def run(runner: str, sources: List[Source]) -> int:
    """Collect, classify, dedup, score, deliver. Returns the count sent."""
    db.init_db()
    print(f"\n=== {runner} run ===")

    # If the cloud cache failed to restore, the database is empty and every
    # job looks new. Say so in the digest rather than letting it read as a
    # flood of duplicates with no explanation.
    state_lost = (db.is_empty()
                  and os.getenv("STATE_RESTORED", "").lower() == "false")

    collected: List[Job] = []
    stats: dict[str, int] = {}
    errors: List[str] = []

    for name, fetch in sources:
        print(f"-> {name} ...")
        try:
            jobs, errs = fetch()
        except Exception as exc:
            jobs, errs = [], [f"{name}: unhandled error: {exc}"]
        jobs = [j for j in jobs if j.is_valid()]
        stats[name] = len(jobs)
        errors.extend(errs)
        collected.extend(jobs)
        db.record_source_run(runner, name, len(jobs), ok=not errs,
                             note="; ".join(errs)[:500])
        print(f"   {len(jobs)} postings" + (f", {len(errs)} error(s)" if errs else ""))

    # Keyword gate first - it is free, and keeps LLM spend proportionate.
    relevant: List[Job] = []
    for job in collected:
        tier = classify(job)
        if tier == REJECT:
            continue
        job.meta["tier"] = tier
        relevant.append(job)

    n_primary = sum(1 for j in relevant if j.meta["tier"] == PRIMARY)
    print(f"\n{len(collected)} collected -> {len(relevant)} relevant "
          f"({n_primary} primary, {len(relevant) - n_primary} stretch)")

    # Collapse duplicates; prefer the primary copy if a role arrives twice.
    unique: dict[str, Job] = {}
    for job in relevant:
        existing = unique.get(job.dedup_key)
        if existing is None or (existing.meta["tier"] == STRETCH
                                and job.meta["tier"] == PRIMARY):
            unique[job.dedup_key] = job

    already = db.known_keys(unique.keys())
    fresh = [j for k, j in unique.items() if k not in already]
    print(f"{len(unique)} unique -> {len(fresh)} not seen before")

    if config.SCORING_ENABLED and fresh:
        print(f"\nScoring {len(fresh)} job(s) with {config.LLM_MODEL} ...")
        for job in fresh:
            score_job(job)

    primary = [j for j in fresh if j.meta["tier"] == PRIMARY]
    stretch = [j for j in fresh if j.meta["tier"] == STRETCH]

    if config.SCORING_ENABLED:
        stretch_min = int(config.SCORING.get("stretch_min_score", 70))
        before = len(primary) + len(stretch)
        primary = [j for j in primary if (j.score or 0) >= config.MIN_SCORE]
        stretch = [j for j in stretch if (j.score or 0) >= stretch_min]
        held = before - len(primary) - len(stretch)
        if held:
            print(f"{held} below threshold - recorded, not sent")
    elif fresh:
        print("Scoring disabled (no ANTHROPIC_API_KEY) - sending everything that passed filters")

    # The stretch section must never swamp the digest.
    stretch_cap = int(config.CFG.get("delivery", {}).get("max_stretch_per_run", 10))
    stretch.sort(key=lambda j: (j.score is None, -(j.score or 0)))
    stretch = stretch[:stretch_cap]

    cap = int(config.CFG.get("delivery", {}).get("max_send_per_run", 25))
    held_for_later: List[Job] = []
    if cap and len(primary) > cap:
        primary.sort(key=lambda j: (j.score is None, -(j.score or 0)))
        held_for_later = primary[cap:]
        primary = primary[:cap]
        print(f"{len(held_for_later)} over the per-run cap of {cap} - they arrive next run")

    to_send = primary + stretch

    warnings = canary.check(stats)
    if state_lost:
        warnings.append(
            "Saved state was not restored (cache miss), so every job looks new. "
            "Expect this one digest to repeat things you have already seen; the "
            "next run will be back to new postings only."
        )
    if held_for_later:
        warnings.append(
            f"{len(held_for_later)} more matched but were held back by the "
            f"per-run cap of {cap}; they will arrive on the next run."
        )
    for err in errors[:10]:
        warnings.append(err)

    delivered = notify.deliver(primary, stretch, warnings, runner, stats)

    if config.DRY_RUN:
        print("  (dry run - nothing marked as seen)")
    elif delivered:
        held_keys = {j.dedup_key for j in held_for_later}
        for job in fresh:
            if job.dedup_key in held_keys:
                continue
            db.record_job(job, notified=job in to_send)
    else:
        print("  ! delivery failed - not marking jobs as seen; they retry next run")

    board.write()

    print(f"\n=== {runner} done: {len(primary)} primary + {len(stretch)} stretch sent ===\n")
    return len(to_send)
