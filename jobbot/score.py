"""LLM relevance scoring against the profile in config.yaml.

Any OpenAI-compatible endpoint works (OpenAI, xAI/Grok, Together, a local
gateway) - it's a plain HTTPS POST, so there is no vendor SDK to keep in sync.
Returns a score, a one-line reason, AND a cold-email hook: the hook is what
makes this useful for companies that have not posted a role.
"""
from __future__ import annotations

import json
import re
from typing import Optional

import requests

from . import config
from .models import Job

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)

SYSTEM = (
    "You screen job postings for a specific candidate. "
    "You are blunt and calibrated: most postings are a poor fit and should score "
    "below 50. Reserve scores above 80 for genuinely strong matches. "
    "Reply with JSON only, no prose, no code fences."
)

TEMPLATE = """Candidate profile:
{summary}

Seniority: {seniority}
Location preference: {locations} (remote acceptable: {remote_ok})

Score this job posting 0-100 for fit with the candidate.

Weigh heavily:
- Is this a FINANCE / strategy / business-operations role (not engineering)?
- Is the company in AI inference, AI infrastructure, GPU/compute, or ML tooling?
- Does the work plausibly touch unit economics, compute cost, pricing or margin?

Judge SENIORITY from the DESCRIPTION, not the title. Titles mislead in both
directions: "Head of Finance" at a 20-person startup is a first finance hire,
while "Analyst" at a large firm can demand 8 years. Look for the required years
of experience, who the role reports to, whether it manages a team, and phrases
like "first finance hire" or "founding". Report it as:
  Below  - clearly junior to the candidate
  At     - matches the candidate's level
  Above  - clearly beyond the candidate (e.g. 8+ years required, runs a team,
           true executive scope)
Score "Above" roles low unless the company is small enough that the title
overstates the actual job.

Return JSON with exactly these keys:
{{"score": <int 0-100>,
  "fit": "<High|Medium|Low>",
  "seniority": "<Below|At|Above>",
  "reason": "<one sentence, max 25 words>",
  "hook": "<one sentence the candidate could open a cold email with, referencing
            something specific about this company or role; empty string if nothing specific>"}}

Job title: {title}
Company: {company}
Location: {location}
Description (truncated):
{description}
"""


def _build_prompt(job: Job) -> str:
    return TEMPLATE.format(
        summary=config.PROFILE.get("summary", "").strip(),
        seniority=config.PROFILE.get("seniority", "").strip(),
        locations=", ".join(config.TARGETS.get("locations", [])),
        remote_ok=config.TARGETS.get("remote_ok", True),
        title=job.title,
        company=job.company,
        location=job.location or "unspecified",
        description=(job.description or "(no description available)")[:2500],
    )


def _parse(content: str) -> Optional[dict]:
    match = _JSON_BLOCK.search(content or "")
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    try:
        score = int(float(data.get("score", 0)))
    except (TypeError, ValueError):
        return None
    return {
        "score": max(0, min(100, score)),
        "fit": str(data.get("fit", "")).strip() or "Unknown",
        "seniority": str(data.get("seniority", "")).strip() or "",
        "reason": str(data.get("reason", "")).strip(),
        "hook": str(data.get("hook", "")).strip(),
    }


def score_job(job: Job, timeout: int = 45) -> Optional[dict]:
    """Populate job.score/fit/reason/hook in place. Returns the parsed dict."""
    if not config.SCORING_ENABLED:
        return None

    payload = {
        "model": config.LLM_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": _build_prompt(job)},
        ],
        "temperature": 0.2,
        "max_tokens": int(config.SCORING.get("model_max_tokens", 400)),
    }
    try:
        resp = requests.post(
            f"{config.LLM_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {config.LLM_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=timeout,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
    except (requests.RequestException, KeyError, IndexError, ValueError) as exc:
        print(f"    ! scoring failed for {job.company} / {job.title}: {exc}")
        return None

    parsed = _parse(content)
    if not parsed:
        print(f"    ! unparseable scoring reply for {job.company} / {job.title}")
        return None

    job.score = parsed["score"]
    job.fit = parsed["fit"]
    job.seniority = parsed["seniority"]
    job.reason = parsed["reason"]
    job.hook = parsed["hook"]
    return parsed
