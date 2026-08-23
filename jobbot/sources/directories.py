"""Company discovery - NOT YET IMPLEMENTED. Deliberate stub with a real interface.

This is the half of the plan that finds COMPANIES rather than POSTINGS:
Seedtable, VCBacked, Growthlist, YC's company directory, VC portfolio pages,
and companies publishing about their own inference economics.

Its output is not jobs - it is new entries for companies.yaml, which the ATS
poller then turns into a free, reliable, unblockable job feed. That is the
pipeline: discovery feeds ATS.

It is stubbed rather than half-built because each of those sites needs either a
paid seat or bespoke scraping, and a fragile scraper that fails silently is
worse than an honest gap. For now, add companies by hand - it is the highest-
leverage ten minutes you can spend on this bot.
"""
from __future__ import annotations

from typing import List, Tuple

from ..models import Job


def fetch_all() -> Tuple[List[Job], List[str]]:
    return [], []


def suggest_companies() -> List[dict]:
    """Future: return [{name, ats, slug, source, why}] to append to companies.yaml."""
    return []
