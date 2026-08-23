"""Company discovery from curated job newsletters.

This is the half of the plan that finds COMPANIES rather than POSTINGS, and it
feeds companies.yaml, which the ATS poller then mines continuously.

Taking the company name rather than the listing is deliberate. A newsletter
listing is a snapshot - stale within weeks, awkward to dedupe, and gone from
the archive eventually. A company name is permanent: once it is in
companies.yaml the ATS poller sees every finance role that company posts from
then on, with a real posted date and a real description to score.

Substack exposes a public RSS feed at /feed with full post content, so no
scraping, no auth, no paid seat - which is why this works where Seedtable
(403 to automated fetches) does not.

Cost control: posts already processed are recorded, so a daily run only reads
what is genuinely new. The first scan costs a few cents; later ones are
fractions of one.
"""
from __future__ import annotations

import concurrent.futures as cf
import html
import json
import re
from typing import List, Optional

import anthropic
import requests

from . import config, db
from .sources import ats

FEED_TIMEOUT = 30
UA = "Mozilla/5.0 (compatible; personal-job-search-bot)"

EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "companies": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Company name only."},
                    "infra_reason": {
                        "type": "string",
                        "description": (
                            "The specific infrastructure this company builds, in "
                            "at most 12 words. Must be concrete."
                        ),
                    },
                },
                "required": ["name", "infra_reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["companies"],
    "additionalProperties": False,
}

EXTRACT_SYSTEM = """You read curated startup job newsletters and pull out companies that build AI INFRASTRUCTURE.

Include only companies whose product is infrastructure other builders use:
model inference and serving, GPU or compute platforms, AI chips and hardware,
vector and data infrastructure, training and orchestration platforms, developer
tooling, evaluation and observability for AI systems, agent infrastructure, and
data labelling or curation platforms.

EXCLUDE applied AI companies, however impressive - a company that uses AI to
serve doctors, lawyers, insurers, recruiters, marketers, consumers or any other
end market is not infrastructure. Also exclude venture funds, the newsletter
itself, recruiters and job boards, and companies named only as an example.

When you are unsure, leave it out. A missed company costs one opportunity; a
wrong one is polled forever.

Set "infra_reason" to the specific infrastructure the company builds. If you
cannot name it concretely, the company does not belong in the list.

Return names exactly as written, with no descriptive suffix - "Baseten", not
"Baseten (inference platform)"."""


def _strip_html(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html.unescape(raw or ""))
    return re.sub(r"\s+", " ", text).strip()


def fetch_feed(slug: str) -> List[dict]:
    """Return [{guid, title, body}] for a Substack feed."""
    url = f"https://{slug}.substack.com/feed"
    try:
        resp = requests.get(url, headers={"User-Agent": UA}, timeout=FEED_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"    ! {slug}: {exc}")
        return []

    posts = []
    for item in re.findall(r"<item>(.*?)</item>", resp.text, re.DOTALL):
        guid = re.search(r"<guid[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</guid>", item, re.DOTALL)
        title = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", item, re.DOTALL)
        body = re.search(
            r"<content:encoded><!\[CDATA\[(.*?)\]\]></content:encoded>", item, re.DOTALL
        )
        if not guid:
            continue
        posts.append({
            "guid": guid.group(1).strip(),
            "feed": slug,
            "title": (title.group(1).strip() if title else "(untitled)"),
            "body": _strip_html(body.group(1)) if body else "",
        })
    return posts


def extract_companies(post: dict) -> List[dict]:
    """Ask the model which companies a post is presenting as hiring."""
    if not config.SCORING_ENABLED:
        return []
    body = post["body"][:12000]
    if len(body) < 200:
        return []

    try:
        response = anthropic.Anthropic(max_retries=3).messages.create(
            model=config.LLM_MODEL,
            max_tokens=2000,
            system=EXTRACT_SYSTEM,
            output_config={"format": {"type": "json_schema", "schema": EXTRACT_SCHEMA}},
            messages=[{
                "role": "user",
                "content": f"Newsletter post: {post['title']}\n\n{body}",
            }],
        )
    except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
        print(f"    ! extraction failed for {post['title'][:40]}: {exc}")
        return []

    if response.stop_reason in ("refusal", "max_tokens"):
        print(f"    ! extraction {response.stop_reason} for {post['title'][:40]}")
        return []
    try:
        text = next(b.text for b in response.content if b.type == "text")
        return json.loads(text).get("companies", [])
    except (StopIteration, json.JSONDecodeError, KeyError):
        return []


def _slug_variants(name: str) -> List[str]:
    """Plausible ATS slugs for a company name, most likely first."""
    low = name.lower().strip()
    bare = re.sub(r"[^a-z0-9]+", "", low)
    hyphen = re.sub(r"[^a-z0-9]+", "-", low).strip("-")
    stripped = re.sub(r"\b(ai|inc|labs|technologies|systems|hq)\b", "", low)
    stripped = re.sub(r"[^a-z0-9]+", "", stripped)
    out = []
    for cand in (bare, hyphen, stripped, bare + "ai", bare + "hq"):
        if cand and len(cand) > 1 and cand not in out:
            out.append(cand)
    return out


AMBIGUOUS = {
    "arbor", "arch", "arcade", "basis", "column", "ghost", "method", "moment",
    "monk", "pearl", "runway", "titan", "twenty", "vega", "warp", "alloy",
    "atoms", "august", "april", "delphi", "exa", "flint", "gamma", "granola",
    "handshake", "laurel", "lio", "odyssey", "orchard", "protege", "sable",
    "salient", "savvy", "scribe", "sela", "shelf", "stacks", "town", "usul",
}


def resolve_board(name: str) -> Optional[dict]:
    """Find a working ATS board for a company name, or None.

    A resolving slug proves *a* company owns it, not that it is the company the
    newsletter meant. Single generic words collide often enough that they are
    skipped rather than guessed at.
    """
    if re.sub(r"[^a-z0-9]", "", name.lower()) in AMBIGUOUS:
        return None
    for slug in _slug_variants(name):
        for kind in ("greenhouse", "lever", "ashby"):
            ok, message = ats.probe({"name": name, "ats": kind, "slug": slug})
            if ok:
                count = int(message.split()[2])
                return {"name": name, "ats": kind, "slug": slug, "roles": count}
    return None


def known_company_names() -> set[str]:
    return {re.sub(r"[^a-z0-9]", "", (c.get("name") or "").lower())
            for c in config.COMPANIES}


def append_to_companies_yaml(found: List[dict]) -> None:
    """Append verified boards, grouped under a dated heading."""
    from datetime import date
    path = config.ROOT / "companies.yaml"
    lines = [f"\n  # --- discovered from newsletters, {date.today().isoformat()} ---"]
    for c in found:
        lines.append(
            f'  - {{ name: "{c["name"]}", ats: {c["ats"]}, slug: {c["slug"]} }}'
            f'  # {c["roles"]} roles'
        )
    with path.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def run() -> List[dict]:
    """Scan configured feeds for companies with a working ATS board."""
    cfg = config.CFG.get("discovery", {}) or {}
    feeds = cfg.get("substacks", [])
    if not feeds:
        print("No discovery.substacks configured.")
        return []
    if not config.SCORING_ENABLED:
        print("Discovery needs ANTHROPIC_API_KEY (it reads the posts).")
        return []

    db.init_db()
    max_posts = int(cfg.get("max_posts_per_run", 15))

    fresh = []
    for slug in feeds:
        posts = fetch_feed(slug)
        new = [p for p in posts if not db.post_seen(p["guid"])]
        print(f"  {slug}: {len(posts)} posts, {len(new)} new")
        fresh.extend(new)

    if not fresh:
        print("Nothing new in any feed.")
        return []

    fresh = fresh[:max_posts]
    print(f"\nReading {len(fresh)} post(s) with {config.LLM_MODEL} ...")

    names: dict[str, str] = {}
    for post in fresh:
        for company in extract_companies(post):
            key = re.sub(r"[^a-z0-9]", "", company["name"].lower())
            if key:
                names.setdefault(key, company["name"])

    known = known_company_names()
    candidates = {k: v for k, v in names.items() if k not in known}
    print(f"{len(names)} companies mentioned, {len(candidates)} not already tracked")
    if not candidates:
        return []

    # Each name costs up to a dozen HTTP probes, so run them concurrently -
    # sequentially this dominates the whole run.
    print(f"\nProbing {len(candidates)} name(s) for public ATS boards ...", flush=True)
    found = []
    with cf.ThreadPoolExecutor(max_workers=12) as pool:
        for board in pool.map(resolve_board, sorted(candidates.values())):
            if board:
                found.append(board)
                print("  + %-24s %s/%s  (%s roles)" % (board["name"], board["ats"], board["slug"], board["roles"]), flush=True)
    found.sort(key=lambda b: b["roles"])

    cap = int(cfg.get("max_new_per_run", 25))
    if len(found) > cap:
        print("  %d found, capping at %d - review before raising the cap"
              % (len(found), cap), flush=True)
        found = found[:cap]

    if found and cfg.get("auto_add", True):
        append_to_companies_yaml(found)
        print(f"\nAdded {len(found)} company(ies) to companies.yaml")
    elif found:
        print(f"\n{len(found)} found; auto_add is off, so nothing was written")
    else:
        print("  none of them have a public ATS board")
    # Posts are marked read only here, after their companies have been
    # probed and written. Marking earlier means a crash loses the names but
    # keeps the posts marked, so a rerun silently skips them.
    for post in fresh:
        db.mark_post_seen(post["guid"], post["feed"], post["title"])

    return found
