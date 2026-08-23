# Operations — everything to remember

The one-page reference. Architecture is in `README.md`, deployment steps in
`DEPLOY.md`, reusing the pattern in `ADAPTING.md`.

---

## Addresses

| What | Where |
|---|---|
| Board (set up a device) | `job-search-bot-rho.vercel.app` |
| Board (direct) | https://sanjayjainmd.github.io/job-board/ |
| Private repo | https://github.com/sanjayjainmd/job-search-bot |
| Public board repo | https://github.com/sanjayjainmd/job-board |
| Actions | https://github.com/sanjayjainmd/job-search-bot/actions |
| Repo secrets | https://github.com/sanjayjainmd/job-search-bot/settings/secrets/actions |
| Vercel project | `job-search-bot` under the DxFlow team |
| Local checkout | `C:\Users\Sjain\Documents\job-search-bot` |

**Setting up a phone or laptop:** type the short address, land on the board
already configured, bookmark what is in the address bar. That device is done.
If it ever asks for a key again — Safari drops storage after ~7 idle days —
type the short address once more.

---

## What runs, and where

**Daily, 13:00 UTC (~6am Pacific), on GitHub Actions:** scan job newsletters
for new companies → poll every ATS board → filter → score with Claude Haiku →
send the delta to Telegram and email → regenerate the board → commit state.

**Never runs on your machine.** There is no scheduled task locally. Local
commands only run when you type them, and `.env` has `DRY_RUN=true`, so they
print instead of sending and do not consume state.

**`run_boards.py` (LinkedIn + Google) has never been run.** It must stay local —
LinkedIn blocks datacenter IPs — and needs `pip install -r requirements-boards.txt`.

---

## Commands

From `C:\Users\Sjain\Documents\job-search-bot`:

| Command | Does |
|---|---|
| `.venv\Scripts\python.exe run_discover.py --verify` | Check every company board still resolves |
| `.venv\Scripts\python.exe run_discover.py --stats` | Is dedup working? New items per day |
| `.venv\Scripts\python.exe run_discover.py --find-companies` | Scan newsletters for new companies |
| `.venv\Scripts\python.exe run_discover.py` | Full run (prints, does not send) |
| `.venv\Scripts\python.exe mark.py` | List items still marked new |
| `.venv\Scripts\python.exe get_chat_id.py` | Recover a Telegram chat ID |

Local runs re-score everything each time, because a dry run deliberately does
not mark anything seen. That costs a few cents per run — the cloud run is the
one that advances state.

---

## Where each thing lives

Four stores, deliberately separate:

| Store | Holds | Written by |
|---|---|---|
| `jobs.db` in the repo | Every job found, its score, whether it was sent | The daily run |
| Redis (via Vercel) | Your New / Seen / Applied / Dismissed marks | You, tapping the board |
| `companies.yaml` | The watchlist — 72 boards | Discovery, and by hand |
| `.env` (local) / repo secrets (cloud) | Credentials | You |

`jobs.db` is what was *sent*; Redis is your *reading state*. `mark.py` writes to
the database, the board writes to Redis — they do not sync, which is by design
but easy to forget.

---

## Tuning

All in `config.yaml`; commit and push and the cloud picks it up.

| Setting | Now | Effect |
|---|---|---|
| `scoring.min_score` | 60 | Below this, recorded but not sent |
| `targets.locations` | Bay Area cities | Companies write it many ways — list cities, not the metro |
| `targets.location_is_hard_filter` | true | Off means location never drops anything |
| `targets.remote_ok` | true | Includes remote roles |
| `targets.small_company_max_postings` | 40 | Under this, senior titles count as first-hire |
| `filters.title_include` / `_exclude` | — | Whole-word matched |
| `filters.title_stretch` | senior, director… | Demoted to "worth a look", never dropped |
| `delivery.max_send_per_run` | 25 | Cold-start valve |
| `discovery.auto_add` | true | Writes verified companies automatically |
| `discovery.max_new_per_run` | 25 | Ceiling on additions |

To re-send everything against changed filters, delete `jobs.db`. One large
digest, then back to normal.

---

## When something looks wrong

**Empty digest.** Usually correct — nothing new was posted. Confirm with
`--stats`: postings fetched should be ~5,000. If a source returns zero while
others are healthy, the canary says so in the digest.

**Board says "Not synced".** The message names the reason. A rejected key
re-shows the entry field. Check the endpoint directly:
`curl -s <vercel-url>/api/status -H "x-board-key: <key>"` — `{}` is correct,
401 is a key mismatch, 500 means Redis variables are missing or you deployed
before setting them.

**No scores in the digest.** `ANTHROPIC_API_KEY` missing from repo secrets, or
credit exhausted at console.anthropic.com.

**`jobs.db` conflict on pull.** SQLite cannot merge. Take one side whole,
normally the cloud's:
`git checkout --ours jobs.db && git add jobs.db && git rebase --continue`

**Vercel changes not taking effect.** Environment variables are baked in at
build time — redeploy after changing any of them.

---

## Costs

| | |
|---|---|
| Claude Haiku scoring | ~$0.0017 per job; ~$0.22 for the first 130 |
| Newsletter discovery | Pennies a month — read posts are remembered |
| GitHub Actions | Free (2,000 min/month; this uses ~150) |
| Vercel + Upstash Redis | Free tier |
| ATS polling, Telegram, email | Free |

Realistically a few dollars a month, dominated by scoring.

---

## Maintenance

| Task | When |
|---|---|
| `--verify` the company list | Monthly — slugs change when companies migrate ATS |
| Skim discovery additions in the daily commit | Weekly |
| Prune off-target companies | When you notice one |
| Rotate the `BOARD_DEPLOY_TOKEN` | Before it expires — publishing goes quiet, and the log says so |
| Watch `--stats` per-day counts | Should be a trickle, not a flood |
