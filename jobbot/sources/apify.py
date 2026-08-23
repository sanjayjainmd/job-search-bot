"""Wellfound + YC Work at a Startup via Apify. OPTIONAL, OFF BY DEFAULT.

Deliberately disabled until you supply real Actor IDs in .env. The Apify free
tier is $5 of credits per month, which two daily actors will exhaust in days,
not a month - so treat this as a supplement, never a backbone.

To enable: find current actors in the Apify Store, then set
APIFY_TOKEN, APIFY_WELLFOUND_ACTOR and APIFY_YC_ACTOR in .env.
"""
from __future__ import annotations

from typing import List, Tuple

from .. import config
from ..models import Job


def enabled() -> bool:
    return bool(config.APIFY_TOKEN and
                (config.APIFY_WELLFOUND_ACTOR or config.APIFY_YC_ACTOR))


def _run_actor(actor_id: str, run_input: dict, label: str) -> Tuple[List[Job], List[str]]:
    try:
        from apify_client import ApifyClient
    except ImportError:
        return [], [f"{label}: apify-client not installed"]

    client = ApifyClient(config.APIFY_TOKEN)
    jobs: List[Job] = []
    try:
        run = client.actor(actor_id).call(run_input=run_input)
        dataset_id = run.get("defaultDatasetId")
        if not dataset_id:
            return [], [f"{label}: actor returned no dataset"]
        for item in client.dataset(dataset_id).iterate_items():
            jobs.append(Job(
                title=str(item.get("title") or item.get("jobTitle") or ""),
                company=str(item.get("companyName") or item.get("company") or ""),
                url=str(item.get("url") or item.get("applyUrl") or ""),
                location=str(item.get("location") or ""),
                description=str(item.get("description") or ""),
                source=label,
            ).clean())
    except Exception as exc:
        return [], [f"{label}: {exc}"]
    return jobs, []


def fetch_all() -> Tuple[List[Job], List[str]]:
    if not enabled():
        return [], []

    query = (config.BOARDS.get("search_terms") or ["financial analyst"])[0]
    jobs: List[Job] = []
    errors: List[str] = []

    if config.APIFY_WELLFOUND_ACTOR:
        found, errs = _run_actor(
            config.APIFY_WELLFOUND_ACTOR,
            {"search": query, "maxItems": 20},
            "wellfound",
        )
        jobs.extend(found)
        errors.extend(errs)

    if config.APIFY_YC_ACTOR:
        found, errs = _run_actor(
            config.APIFY_YC_ACTOR,
            {"query": query, "maxItems": 20},
            "ycombinator",
        )
        jobs.extend(found)
        errors.extend(errs)

    return jobs, errors
