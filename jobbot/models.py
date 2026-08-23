"""Normalised job record shared by every source."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Optional

_PUNCT = re.compile(r"[^a-z0-9 ]+")
_SPACE = re.compile(r"\s+")
# Noise that stops the same role matching across boards.
_TITLE_NOISE = re.compile(
    r"\b(senior|sr|junior|jr|staff|lead|principal|i{1,3}|iv|v|remote|hybrid|onsite|"
    r"full[- ]?time|part[- ]?time|contract|us|usa|new)\b"
)


def _norm(text: str) -> str:
    text = _PUNCT.sub(" ", (text or "").lower())
    return _SPACE.sub(" ", text).strip()


def normalise_title(title: str) -> str:
    """Aggressively normalised title, used only for cross-source dedup."""
    return _SPACE.sub(" ", _TITLE_NOISE.sub(" ", _norm(title))).strip()


@dataclass
class Job:
    title: str
    company: str
    url: str
    source: str
    location: str = ""
    description: str = ""
    # Filled in later by the scoring layer.
    score: Optional[int] = None
    fit: Optional[str] = None
    seniority: Optional[str] = None
    reason: Optional[str] = None
    hook: Optional[str] = None
    meta: dict = field(default_factory=dict)

    @property
    def dedup_key(self) -> str:
        """Stable across sources: the same role on Greenhouse and LinkedIn collapses.

        Deliberately excludes the URL, which differs per board for one job.
        """
        basis = f"{_norm(self.company)}|{normalise_title(self.title)}"
        return hashlib.sha1(basis.encode("utf-8")).hexdigest()

    def clean(self) -> "Job":
        self.title = (self.title or "").strip()
        self.company = (self.company or "").strip()
        self.url = (self.url or "").strip()
        self.location = (self.location or "").strip()
        self.description = (self.description or "").strip()[:4000]
        return self

    def is_valid(self) -> bool:
        return bool(self.title and self.company and self.url)
