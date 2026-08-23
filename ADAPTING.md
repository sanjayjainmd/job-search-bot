# Adapting this to a different subject

This repo is a job search, but almost none of the machinery is about jobs. The
reusable idea is narrower and more useful than "job bot":

> Watch a curated set of sources. Only ever tell me what changed. Score what
> changed against a written profile. Accumulate everything somewhere I can
> triage from any device. And grow the source list from places humans already
> curate, accepting new entries only when they pass an objective check.

That fits grant deadlines, funding or policy catalysts, competitor releases,
literature watch, RFPs, property listings - anything where the work is
*noticing*, and the enemy is a daily flood you stop reading.

---

## Engine vs domain

**Engine - reuse unchanged.** None of these know what a "job" is:

| File | What it does |
|---|---|
| `jobbot/pipeline.py` | collect -> classify -> dedupe -> score -> deliver |
| `jobbot/db.py` | seen-items state, per-source health, status |
| `jobbot/notify.py` | batched two-tier digest, Telegram + email |
| `jobbot/board.py` | the accumulating board, cross-device status |
| `jobbot/canary.py` | notices a source that silently stopped returning anything |
| `jobbot/discovery.py` | curated feeds -> LLM extraction -> objective check -> watchlist |
| `vercel/` | status endpoint and short link |
| `.github/workflows/discover.yml` | the schedule, state commit, publish |

**Domain - replace these.** Roughly 30% of the code:

| File | Job-specific because |
|---|---|
| `jobbot/sources/ats.py` | Greenhouse / Lever / Ashby are hiring systems |
| `jobbot/sources/boards.py` | jobspy scrapes job boards |
| `companies.yaml` | a watchlist of employers |
| `jobbot/score.py` | the prompt describes a candidate and a role |
| `jobbot/models.py` | `Job` has `title`, `company`, `posted_at` |
| `config.yaml` filters | title keywords, seniority tiers, locations |

---

## The five things to change

**1. What an item is.** `models.py` defines `Job`. For a grants tracker it
becomes `Grant(title, funder, deadline, url)`. Keep `dedup_key` - a stable hash
of the fields that identify the thing regardless of where you found it. Getting
this wrong is the one mistake that ruins everything downstream: too loose and
you re-send the same item forever, too tight and duplicates slip through.

**2. Where items come from.** Add a module under `jobbot/sources/` exposing
`fetch_all() -> (items, errors)`. Prefer structured public endpoints over
scraping - the ATS JSON APIs here are free, unlimited, and never break, while
every directory we tried returned 403 to automated fetches.

**3. The cheap filter.** `pipeline.classify()` gates on keywords before the LLM
so scoring cost stays proportionate - 4,600 postings become ~110 scored. Keep
that shape: a free filter first, a paid judgement second.

**4. The profile and prompt.** `config.yaml`'s `profile` block plus
`score.py`'s system prompt. Write the profile as prose about what you want and
why; the model uses it for both scoring and the "hook" it drafts.

**5. What "worth a look" means.** The PRIMARY / STRETCH / REJECT split exists
because a filter that *drops* things loses them silently and you never find
out. Decide what your borderline tier is rather than removing it.

---

## Things learned the hard way

Each of these came from something breaking. They are cheap to keep and
expensive to rediscover.

**A silent-failure canary.** A blocked scraper returns an empty list, which is
indistinguishable from "nothing new" - for weeks. Track per-source counts and
warn when one source returns zero while others are healthy. And **never leave a
permanent false alarm running**: a stub that always returns zero trains you to
ignore the warning that eventually matters.

**Mark items seen only after delivery succeeds.** Marking on send means a
failed send silently swallows the item forever.

**A dry run must not consume state.** Testing should not mark things seen, or
your first real run arrives empty with no visible reason.

**A cold-start cap.** The first run against an empty database wants to send
everything. Cap it, and let the overflow arrive next run.

**A cap on anything that writes to config.** Discovery once added 271 companies
in one run because the prompt asked "who is hiring" and never "is this the
right kind of company". A cap plus a log line turns a flood into a reviewable
batch.

**Verify mechanically, not by plausibility.** An LLM will happily name a
company that does not exist. Requiring a working public board before anything
is written means hallucinations fail closed. But note what that check does
*not* prove: a resolving slug shows *a* company owns it, not the right one -
generic single words are skipped rather than guessed.

**Mark source posts read only after their output is written.** Marking earlier
means an interrupted run loses the extracted data but keeps the posts marked,
so a retry silently skips them.

**Binary state files cannot merge.** `jobs.db` is SQLite; a line-based merge
produces a corrupt database rather than a conflict. `.gitattributes` marks it
`binary -merge` so git raises an honest conflict instead.

**Two runtimes, one codebase.** Anything that gets blocked from datacenter IPs
(LinkedIn) runs locally; everything else runs in CI. Split by *where code runs*,
not by product - and don't put credentials in a page just because it needs
them, put them behind a function.

---

## Reusing it

Mark the repo as a template (Settings -> Template repository), then
"Use this template" for each new subject. Replace the six domain files, rewrite
`config.yaml`, and keep everything else.

Do not extract a shared library yet. You learn which seams are real by building
the next one; a framework derived from a single instance usually abstracts the
wrong things. If a third subject changes the same files again, that is the
signal - and by then you will know exactly what to pull out.
