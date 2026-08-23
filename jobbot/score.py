"""LLM relevance scoring against the profile in config.yaml.

Uses Claude Haiku 4.5 through the official Anthropic SDK. Haiku is the right
tier here: this is short-text classification, not reasoning, and it is the
cheapest current Claude model - roughly $0.22 to score the whole backlog.

Beyond a score, the model returns a cold-email hook. That exists because the
best roles at this stage are often not posted at all, so the digest needs to
tell you who to write to, not just what to click.
"""
from __future__ import annotations

import json
from typing import Optional

import anthropic

from . import config
from .models import Job

# Structured outputs guarantee a parseable reply - no regex, no retry loop.
# Schema limits worth knowing: no minimum/maximum on numbers, and every object
# needs additionalProperties: false. The score is clamped in code instead.
SCORE_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {
            "type": "integer",
            "description": "Fit for the candidate, 0-100.",
        },
        "fit": {"type": "string", "enum": ["High", "Medium", "Low"]},
        "seniority": {
            "type": "string",
            "enum": ["Below", "At", "Above"],
            "description": "Level of this role relative to the candidate.",
        },
        "reason": {
            "type": "string",
            "description": "One sentence, at most 25 words, on why this score.",
        },
        "hook": {
            "type": "string",
            "description": (
                "One sentence the candidate could open a cold email with, "
                "referencing something specific about this company or role. "
                "Empty string if nothing specific stands out."
            ),
        },
    },
    "required": ["score", "fit", "seniority", "reason", "hook"],
    "additionalProperties": False,
}


def _system_prompt() -> str:
    """Stable across every job in a run - only the posting varies."""
    return f"""You screen job postings for one specific candidate. You are blunt \
and calibrated: most postings are a poor fit and should score below 50. Reserve \
scores above 80 for genuinely strong matches.

Candidate profile:
{config.PROFILE.get("summary", "").strip()}

Seniority: {config.PROFILE.get("seniority", "").strip()}
Location preference: {", ".join(config.TARGETS.get("locations", []))} \
(remote acceptable: {config.TARGETS.get("remote_ok", True)})

Weigh heavily:
- Is this a FINANCE / strategy / business-operations role, not engineering?
- Is the company in AI inference, AI infrastructure, GPU/compute, or ML tooling?
- Does the work plausibly touch unit economics, compute cost, pricing or margin?

Judge SENIORITY from the DESCRIPTION, not the title. Titles mislead in both
directions: "Head of Finance" at a 20-person startup is a first finance hire,
while "Analyst" at a large firm can demand 8 years. Look for required years of
experience, who the role reports to, whether it manages a team, and phrases like
"first finance hire" or "founding". Report Below, At, or Above the candidate's
level, and score "Above" roles low unless the company is small enough that the
title overstates the actual job."""


_client: Optional[anthropic.Anthropic] = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        # Reads ANTHROPIC_API_KEY from the environment; config loads .env first.
        _client = anthropic.Anthropic(max_retries=3)
    return _client


def score_job(job: Job) -> Optional[dict]:
    """Populate job.score/fit/seniority/reason/hook in place."""
    if not config.SCORING_ENABLED:
        return None

    user_content = (
        f"Job title: {job.title}\n"
        f"Company: {job.company}\n"
        f"Location: {job.location or 'unspecified'}\n"
        f"Posted: {job.posted_at or 'unknown'}\n\n"
        f"Description (truncated):\n"
        f"{(job.description or '(no description available)')[:2500]}"
    )

    try:
        response = _get_client().messages.create(
            model=config.LLM_MODEL,
            max_tokens=int(config.SCORING.get("model_max_tokens", 512)),
            system=_system_prompt(),
            output_config={"format": {"type": "json_schema", "schema": SCORE_SCHEMA}},
            messages=[{"role": "user", "content": user_content}],
        )
    except anthropic.NotFoundError:
        print(f"    ! unknown model '{config.LLM_MODEL}' - check LLM_MODEL in .env")
        return None
    except anthropic.AuthenticationError:
        print("    ! ANTHROPIC_API_KEY rejected")
        return None
    except anthropic.RateLimitError:
        # The SDK already retried with backoff; skip this job rather than stall.
        print(f"    ! rate limited, skipping {job.company} / {job.title}")
        return None
    except anthropic.APIStatusError as exc:
        print(f"    ! API error {exc.status_code} for {job.company}: {exc.message}")
        return None
    except anthropic.APIConnectionError:
        print(f"    ! network error scoring {job.company} / {job.title}")
        return None

    if response.stop_reason == "refusal":
        print(f"    ! model declined to score {job.company} / {job.title}")
        return None
    if response.stop_reason == "max_tokens":
        print(f"    ! reply truncated for {job.company} - raise model_max_tokens")
        return None

    # output_config.format guarantees the first text block is valid JSON.
    try:
        text = next(b.text for b in response.content if b.type == "text")
        data = json.loads(text)
    except (StopIteration, json.JSONDecodeError) as exc:
        print(f"    ! unreadable reply for {job.company}: {exc}")
        return None

    job.score = max(0, min(100, int(data["score"])))
    job.fit = data["fit"]
    job.seniority = data["seniority"]
    job.reason = data["reason"].strip()
    job.hook = data["hook"].strip()
    return data
