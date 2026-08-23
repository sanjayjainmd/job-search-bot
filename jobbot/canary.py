"""Detects silent source failure.

The dangerous failure mode is not an exception - it is a scraper that gets
blocked and returns an empty list forever, which is indistinguishable from
"no new jobs" unless you track it.
"""
from __future__ import annotations

from typing import List

from . import config, db


def check(sources_run: dict[str, int]) -> List[str]:
    warnings: List[str] = []
    threshold = config.ZERO_STREAK_WARNING
    healthy = [s for s, n in sources_run.items() if n > 0]

    for source, count in sources_run.items():
        if count > 0:
            continue
        streak = db.zero_streak(source)
        if streak < threshold:
            continue
        detail = (
            f"{source} has returned 0 results {streak} runs in a row"
        )
        if healthy:
            detail += f" while {', '.join(healthy)} returned results - likely blocked or broken"
        else:
            detail += " (all sources quiet - could be network or config)"
        warnings.append(detail)
    return warnings
