"""jobspy: LinkedIn + Google Jobs. LOCAL RUNNER ONLY.

LinkedIn blocks datacenter IPs, so this must run from a residential
connection. If you ever move it to CI it will quietly return nothing -
which is exactly what jobbot.canary exists to catch.
"""
from __future__ import annotations

from typing import List, Tuple

from .. import config
from ..models import Job, normalise_date


def available() -> bool:
    try:
        import jobspy  # noqa: F401
        return True
    except ImportError:
        return False


def fetch_all() -> Tuple[List[Job], List[str]]:
    if not available():
        return [], ["jobspy not installed - pip install -r requirements-boards.txt"]

    from jobspy import scrape_jobs  # imported late so the cloud runner needn't have it

    terms = config.BOARDS.get("search_terms") or ["financial analyst"]
    sites = config.BOARDS.get("sites") or ["linkedin", "google"]
    locations = config.TARGETS.get("locations") or ["San Francisco"]
    location = locations[0]

    jobs: List[Job] = []
    errors: List[str] = []

    for term in terms:
        try:
            df = scrape_jobs(
                site_name=sites,
                search_term=term,
                google_search_term=term,
                location=location,
                results_wanted=int(config.BOARDS.get("results_wanted", 20)),
                hours_old=int(config.BOARDS.get("hours_old", 72)),
                is_remote=bool(config.TARGETS.get("remote_ok", True)),
                linkedin_fetch_description=False,  # far fewer requests = far less blocking
                verbose=0,
            )
        except Exception as exc:  # jobspy raises a wide variety of transport errors
            errors.append(f"jobspy '{term}': {exc}")
            continue

        if df is None or df.empty:
            continue

        for _, row in df.iterrows():
            def val(key: str) -> str:
                v = row.get(key)
                return "" if v is None or str(v) == "nan" else str(v)

            jobs.append(Job(
                title=val("title"),
                company=val("company"),
                url=val("job_url") or val("job_url_direct"),
                location=val("location"),
                description=val("description"),
                source=val("site") or "jobspy",
                posted_at=normalise_date(val("date_posted")),
            ).clean())

    return jobs, errors
