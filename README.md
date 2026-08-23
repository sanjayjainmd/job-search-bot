# Job Search Bot

A personal job-search bot for a **financial analyst with private equity experience**
targeting finance roles at **AI inference / AI infrastructure** startups.

One codebase, **two runners**, split by runtime environment rather than by product:

| Runner | Sources | Runs where | Why |
|---|---|---|---|
| `discover` | Direct ATS polling (Greenhouse / Lever / Ashby) | GitHub Actions | Public JSON, no blocking, no ToS problem |
| `boards` | LinkedIn + Google via jobspy | Your own machine | LinkedIn blocks datacenter IPs |

Both share one database, one filter chain, one scorer and one digest.

---

## Why ATS polling is the primary source

Series A/B startups post to their own Greenhouse/Lever/Ashby board **before**
LinkedIn. Those boards expose public JSON with no auth, no rate limits worth
worrying about and no terms-of-service problem. The only thing they need is a
list of companies — which is `companies.yaml`, and which is the one file worth
maintaining by hand.

Verified on first run: 21 company boards, ~3,459 live postings, 120 of which
cleared the finance keyword filters.

---

## Setup

```bash
py -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-core.txt
copy .env.example .env
```

Then edit `.env`. Everything is optional except what you want to use — with no
keys at all it runs in `DRY_RUN` mode and prints the digest to the console.

### Check the company list works

```bash
.venv\Scripts\python.exe run_discover.py --verify
```

Reports OK / BAD per company. Slugs change when companies migrate ATS, so re-run
this occasionally — a silently-dead board is the easiest way to miss a job.

### Run it

```bash
.venv\Scripts\python.exe run_discover.py
```

For the local board scraper (needs the extra dependency):

```bash
.venv\Scripts\python.exe -m pip install -r requirements-boards.txt
.venv\Scripts\python.exe run_boards.py
```

---

## Configuration

| File | Holds | Commit it? |
|---|---|---|
| `.env` | Secrets: API keys, tokens, passwords | **Never** — it is gitignored |
| `config.yaml` | Profile, search terms, filters, thresholds | Yes |
| `companies.yaml` | ATS target list | Yes |
| `jobs.db` | Seen-jobs state | No — gitignored |

Retargeting the bot at a different person is a `config.yaml` edit, not a code
change. The profile text there feeds both the relevance score and the cold-email
hook.

### Telegram (2 minutes)

1. Message [@BotFather](https://t.me/botfather) -> `/newbot` -> copy the token.
2. Put the token in `.env` as `TELEGRAM_BOT_TOKEN`.
3. Message your new bot once (a bot cannot start a conversation).
4. Run `.venv\Scripts\python.exe get_chat_id.py` - it validates the token and
   prints the chat ID for you. No browser needed.
5. Put the chat ID in `.env`, set `DRY_RUN=false`.

### Email

Gmail needs an **App Password** (with 2FA enabled), not your normal password.

### LLM scoring (optional, recommended)

Claude Haiku 4.5 via the official Anthropic SDK. Set `ANTHROPIC_API_KEY` (from
console.anthropic.com); `LLM_MODEL` defaults to `claude-haiku-4-5`. Without a
key the bot still runs; it just sends everything that passes the keyword
filters instead of ranking it. With a key, anything scoring under
`scoring.min_score` is recorded but not sent.

Haiku is the right tier here — this is short-text classification, not
reasoning, and it is the cheapest current Claude model. Each job costs roughly
1,050 input and 120 output tokens, so at $1/$5 per million the whole starting
backlog is about **$0.22** and ongoing use is pennies a month.

Replies use **structured outputs** (a JSON schema enforced by the API), so
there is no regex extraction and no retry-on-parse loop.

The scorer returns a score, a one-line reason, **and a cold-email hook** — the
hook exists because the best roles at this stage are often not posted at all.

---

## Deploying `discover` to GitHub Actions

1. Create a **private** repo and push. (Public would broadcast that someone is
   job hunting.)
2. Settings → Secrets and variables → Actions → add:
   `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `EMAIL_SENDER`, `EMAIL_PASSWORD`,
   `EMAIL_RECEIVER`, `SMTP_SERVER`, `SMTP_PORT`, `ANTHROPIC_API_KEY`,
   `LLM_MODEL`.
3. Actions tab → **discover** → *Run workflow* to test.

Runs daily at 13:00 UTC (~06:00 Pacific); edit the cron in
`.github/workflows/discover.yml`. A private repo gets 2,000 free Actions
minutes/month and this uses roughly 100–150.

State persists between runs via `actions/cache`. Caches are evicted after 7 days
unused, which a daily schedule avoids; if the cache is ever lost, the worst case
is some already-seen jobs resend once.

`boards` is deliberately **not** in CI. Running it there would get LinkedIn
blocked, and the failure would be silent.

---

## The board

The Telegram digest is a delta - what changed today. `board.html` is the
opposite: every job ever matched, grouped by status, nothing ever removed.

It is regenerated on every run and committed to the repo, so `git pull` and
open it in a browser - or read it from a phone once published to GitHub Pages
(see DEPLOY.md step 7). Filter tabs: New / Seen / Applied / Dismissed / All.
Stretch-tier ("worth a look") jobs are tinted.

Sort by **newest posted**, **oldest posted**, **best score** or **recently
found**. Posted dates are the real ones from the ATS - Greenhouse
`first_published`, Lever `createdAt`, Ashby `publishedAt`, jobspy
`date_posted` - not the date the bot happened to notice the job.

Anything open 6 months or more is flagged in red. Those are usually evergreen
reqs a company leaves permanently open, not live openings, and they are worth
treating differently from something posted last week.

Status can be changed **from the page on any device** once `board.status_api`
is set in config.yaml - tap New / Seen / Applied / Dismissed and the mark is
stored centrally, so a change on your phone shows up on either laptop. That
needs the small Vercel function in `vercel/` (see its README); a static page
cannot write to a database on its own.

Without it the board is read-only and status is changed from the command line:

    py mark.py                    # list everything still "new", with refs
    py mark.py 3f9a21bc applied   # set one job (click a ref on the board to copy it)
    py mark.py --all-seen         # clear the "new" pile in one go
    py mark.py --counts

## State lives in the repo

`jobs.db` is committed rather than kept in a CI cache. Caches expire after
7 days unused and are invisible from your machine; a committed database is
durable, versioned, and can be inspected locally after a `git pull`. The repo
is private, which is what makes this safe.

Two trade-offs worth knowing.

Each run commits the whole database file, so repo size grows slowly. A few MB
a year at this scale.

And SQLite is binary, so if the cloud and your machine both write to `jobs.db`
between pulls, git cannot merge them - you get a conflict, not a silent
corruption (`.gitattributes` marks the file `binary -merge` to guarantee that).
Resolve by taking one side wholesale, normally the cloud's:

    git checkout --ours jobs.db && git add jobs.db && git rebase --continue

You avoid it entirely by pulling before a local `run_boards.py` and pushing
after.

## Checking it is not repeating itself

    .venv\Scripts\python.exe run_discover.py --stats

Shows how many jobs are remembered, and a per-day histogram of newly recorded
jobs. That histogram is the number to watch: it should fall to a trickle once
the backlog clears. If it stays high every day, dedup is broken.

Dedup works on a key of company + normalised title, so the same role collapses
across boards, and a job is only marked seen after delivery actually succeeds.

The one real way this breaks in the cloud is the Actions cache failing to
restore, which empties the database and makes every job look new. The workflow
passes the cache-hit result in as STATE_RESTORED, so when that happens the
digest says so explicitly instead of just looking like a flood of duplicates.
The Actions run also prints --stats after every run.

## The canary

The dangerous failure is not a crash — it is a scraper that gets blocked and
returns an empty list forever, which looks exactly like "no new jobs."

Every run records per-source result counts. If a source returns zero
`canary.zero_streak_warning` runs in a row **while other sources are healthy**,
the digest leads with a warning naming it. This covers LinkedIn blocking, dead
Apify actors, and ATS slugs that silently change.

---

## What is real and what is not

**Working and tested:**
ATS polling across 21 verified boards · cross-source dedup · keyword filters ·
LLM scoring · batched digest (Telegram + email) · canary · cold-start cap ·
GitHub Actions workflow.

## Company discovery

The ATS poller is only as good as `companies.yaml`, so `jobbot/discovery.py`
grows that list from curated job newsletters:

    py run_discover.py --find-companies

It takes **company names, not listings**. A listing is a snapshot - stale in
weeks and eventually gone from the archive. A company name is permanent: once
added, the ATS poller sees every finance role that company posts from then on,
with a real posted date and a full description to score.

Substack serves full post content at `/feed` with no auth and no paid seat,
which is why this works where the funding directories do not - Seedtable
returns 403 to automated fetches, which is what kept this stubbed for so long.

Three gates stand between a newsletter mention and `companies.yaml`:

1. **Relevance.** The model must name the specific infrastructure a company
   builds. Applied AI is excluded however good it is - a company using AI to
   serve doctors or lawyers is not infrastructure. Without this gate one run
   added 271 companies including hospitals, law firms and consumer apps.
2. **A working public ATS board.** Unresolvable names are dropped. Generic
   single words (`arbor`, `runway`, `method`, `ghost`) are skipped outright,
   because a resolving slug proves *a* company owns it, not the right one.
3. **A cap per run** (`discovery.max_new_per_run`), logged when it bites, so a
   prompt change that suddenly matches everything is a reviewable batch rather
   than a silent flood. Results are sorted smallest-board-first, which favours
   the Series A/B companies the strategy targets.

Posts already read are recorded in `seen_posts`, so a daily scan only pays for
new ones - and they are marked read only *after* their companies are written,
so a crash costs a re-read rather than losing the names.

Set `discovery.auto_add: false` to have runs report candidates without writing
them. Every addition is a git commit either way.

## Sharing the board with someone else

The short way - the Vercel project's bare domain redirects to the board with
the key attached, which is what you give someone typing it on a phone:

    job-search-bot-rho.vercel.app

The long way, equivalent, if you would rather send a direct link:

    https://<you>.github.io/job-board/?key=<BOARD_KEY>

The page saves the key to that browser's local storage and strips it from the
address bar, so it is not left in the visible URL or copied onward when someone
shares the page. After that the device is set up permanently and the plain URL
works.

The trade-off: the key sits in whatever channel the link was sent through, and
in browser history until that entry ages out. Acceptable for a shared secret
guarding public job listings and your own status marks - not a pattern to reuse
for anything sensitive.

**Off by default — `jobbot/sources/apify.py`:**
Wellfound and YC Work at a Startup. Needs real Actor IDs from the Apify Store in
`.env`. Note the free tier is $5 of credits per *month*, which two daily actors
exhaust in days — treat it as a supplement, never a backbone.

**Not automatable at all:**
The FinOps Foundation community, and cold outreach itself. No bot does these.
The digest's job is to tell you *who to email*; sending it is still you.

---

## Telegram: what a tap can and cannot do

The digest makes the **job title itself a link** - one tap opens the real
posting. In email the raw URL is printed instead.

Anything scoring at or above `delivery.highlight_min_score` (top 3 by default)
is *also* sent as its own message carrying:

- a **"Open posting"** button - one tap, straight to the application page
- a **tap-to-copy opening line** for a cold email, taken from the LLM's `hook`

That is the boundary of what a send-only bot can do. Telegram buttons come in
two kinds: **URL buttons**, which just open a link and need nothing running,
and **callback buttons** ("Mark applied", "Snooze", "More like this"), which
send an event back and therefore need a bot that is *listening* - a webhook or
a long-running poller. That means a persistent process, which GitHub Actions
cannot host (jobs cap at 6 hours) and which would need a server.

So: one-tap open and one-tap copy work today, free. One-tap *state changes*
need infrastructure - worth adding only if the digest proves itself first.

Nothing is ever sent on your behalf. The opening line is a draft you copy,
edit and send yourself.

## Deliberate design choices

- **Dedup key is company + normalised title, not URL** — so the same role on
  Greenhouse and LinkedIn collapses to one entry.
- **Jobs are marked seen only after delivery succeeds.** A failed send retries
  next run rather than silently swallowing the job.
- **Keyword filter runs before the LLM**, so scoring cost stays proportionate
  (3,459 postings → 125 scored).
- **One batched digest per run**, not one message per job.
- **Send-only Telegram over plain HTTPS.** No `aiogram`, so no async framework
  for something that only ever posts.

---

## Open decisions

- **SF vs. remote.** `config.yaml` currently lists Bay Area locations with
  `remote_ok: true` and `location_is_hard_filter: false` — i.e. remote is
  allowed and location never drops a job. Flip the hard filter to tighten.
- **Exact title list.** `filters.title_include` is a first pass. Watch a week of
  digests and prune.
