"""Direct ATS polling - Greenhouse, Lever, Ashby.

The primary source. Public JSON, no auth, no rate limits worth worrying about,
no terms-of-service problem, and startups post here BEFORE anywhere else.
Its one requirement is a company list, which is what companies.yaml is for.
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

import requests

from ..models import Job

TIMEOUT = 25
HEADERS = {"User-Agent": "personal-job-search-bot/0.1"}
_TAGS = re.compile(r"<[^>]+>")


def _strip_html(raw: str) -> str:
    if not raw:
        return ""
    text = _TAGS.sub(" ", raw)
    text = (text.replace("&nbsp;", " ").replace("&amp;", "&")
                .replace("&lt;", "<").replace("&gt;", ">").replace("&#39;", "'")
                .replace("&quot;", '"'))
    return re.sub(r"\s+", " ", text).strip()


def _get(url: str) -> Optional[dict | list]:
    resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


def _greenhouse(name: str, slug: str) -> Optional[List[Job]]:
    data = _get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
    if data is None:
        return None
    jobs = []
    for item in data.get("jobs", []):
        jobs.append(Job(
            title=item.get("title", ""),
            company=name,
            url=item.get("absolute_url", ""),
            location=(item.get("location") or {}).get("name", ""),
            description=_strip_html(item.get("content", "")),
            source="greenhouse",
        ).clean())
    return jobs


def _lever(name: str, slug: str) -> Optional[List[Job]]:
    data = _get(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    if data is None:
        return None
    jobs = []
    for item in data:
        cats = item.get("categories") or {}
        jobs.append(Job(
            title=item.get("text", ""),
            company=name,
            url=item.get("hostedUrl", "") or item.get("applyUrl", ""),
            location=cats.get("location", "") or "",
            description=_strip_html(
                item.get("descriptionPlain") or item.get("description", "")
            ),
            source="lever",
        ).clean())
    return jobs


def _ashby(name: str, slug: str) -> Optional[List[Job]]:
    data = _get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    if data is None:
        return None
    jobs = []
    for item in data.get("jobs", []):
        jobs.append(Job(
            title=item.get("title", ""),
            company=name,
            url=item.get("jobUrl", "") or item.get("applyUrl", ""),
            location=item.get("location", "") or "",
            description=_strip_html(
                item.get("descriptionPlain") or item.get("descriptionHtml", "")
            ),
            source="ashby",
        ).clean())
    return jobs


_FETCHERS = {"greenhouse": _greenhouse, "lever": _lever, "ashby": _ashby}


def probe(company: dict) -> Tuple[bool, str]:
    """Used by --verify. Returns (works, message)."""
    ats = (company.get("ats") or "").lower()
    slug = company.get("slug", "")
    name = company.get("name", slug)
    fetcher = _FETCHERS.get(ats)
    if not fetcher:
        return False, f"unknown ats '{ats}'"
    try:
        jobs = fetcher(name, slug)
    except requests.RequestException as exc:
        return False, f"error: {exc}"
    if jobs is None:
        return False, "not found (404)"
    if not jobs:
        return False, "reachable but 0 postings - check the slug"
    return True, f"OK - {len(jobs)} postings"


def fetch_all(companies: List[dict]) -> Tuple[List[Job], List[str]]:
    """Poll every configured company board. Returns (jobs, error_messages)."""
    jobs: List[Job] = []
    errors: List[str] = []
    for company in companies:
        ats = (company.get("ats") or "").lower()
        slug = company.get("slug", "")
        name = company.get("name", slug)
        fetcher = _FETCHERS.get(ats)
        if not fetcher:
            errors.append(f"{name}: unknown ats '{ats}'")
            continue
        try:
            found = fetcher(name, slug)
        except requests.RequestException as exc:
            errors.append(f"{name}: {exc}")
            continue
        if found is None:
            errors.append(f"{name}: board not found (slug '{slug}')")
            continue
        jobs.extend(found)
    return jobs, errors
