# Deploying `discover` to GitHub Actions

Step by step. Everything happens either at **github.com** in a browser, or in a
terminal opened at `C:\Users\Sjain\Documents\job-search-bot`.

The goal: `discover` runs itself daily in the cloud, so nothing depends on your
machine being switched on.

---

## Step 1 - Create the repository

1. Go to **https://github.com/new**
2. **Repository name**: `job-search-bot` (any name is fine)
3. **Description**: optional
4. Select **Private**. This matters - a public repo announces to anyone
   looking that someone is job hunting, and exposes the target company list.
5. Leave **all three** "Initialize this repository with" boxes UNCHECKED
   (no README, no .gitignore, no licence). The repo already has these, and
   ticking them creates a conflicting first commit.
6. Click **Create repository**

GitHub then shows a "Quick setup" page. Copy the HTTPS URL at the top - it
looks like `https://github.com/yourname/job-search-bot.git`.

---

## Step 2 - Push

In the terminal, one line (substitute your URL):

    git remote add origin https://github.com/yourname/job-search-bot.git

Then:

    git push -u origin main

### What happens on first push

Git for Windows will open a browser window asking you to sign in to GitHub and
authorise Git Credential Manager. Approve it once and it is remembered.

If no browser opens, or you cannot use one, authenticate with a token instead:

1. github.com -> your avatar (top right) -> **Settings**
2. Scroll to the bottom -> **Developer settings**
3. **Personal access tokens** -> **Tokens (classic)** -> **Generate new token (classic)**
4. Note: `job-search-bot`; Expiration: your choice; tick the **`repo`** scope
5. **Generate token**, copy it (it is shown only once)
6. Run the push again. When prompted for **Username**, enter your GitHub
   username. When prompted for **Password**, paste the **token** - not your
   GitHub password, which will be rejected.

### If it says "remote origin already exists"

    git remote set-url origin https://github.com/yourname/job-search-bot.git

---

## Step 3 - Confirm no secrets were pushed

On the repo page, look at the file list. You should see `.env.example` but
**never `.env`**, and no `jobs.db` and no `.venv`.

If `.env` ever appears there, treat the bot token as compromised: message
@BotFather, `/revoke`, and issue a new one. Deleting the file afterwards is not
enough, because git history keeps it.

---

## Step 4 - Add the secrets

The token lives in your local `.env`, which is deliberately not pushed. The
cloud run needs its own copy.

1. In the repo: **Settings** (top bar of the repo, not your account settings)
2. Left sidebar: **Secrets and variables** -> **Actions**
3. Click **New repository secret** for each of these:

| Name | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | same as in your `.env` |
| `TELEGRAM_CHAT_ID` | same as in your `.env` |

Add these too, only if you are using them:

| Name | Value |
|---|---|
| `LLM_API_KEY` | your OpenAI-compatible key |
| `LLM_BASE_URL` | e.g. `https://api.openai.com/v1` |
| `LLM_MODEL` | e.g. `gpt-4o-mini` |
| `EMAIL_SENDER` / `EMAIL_PASSWORD` / `EMAIL_RECEIVER` | Gmail App Password, not your login password |
| `SMTP_SERVER` / `SMTP_PORT` | `smtp.gmail.com` / `587` |

Names must match exactly - they are case sensitive. A missing secret is not an
error; the bot just treats that channel as disabled and carries on.

---

## Step 5 - First cloud run

1. Repo -> **Actions** tab
2. If you see "Workflows aren't being run on this forked repository", click the
   green button to enable them
3. Left sidebar: **discover**
4. Right side: **Run workflow** -> green **Run workflow** button
5. Refresh after a few seconds; click the run to watch it

Open the **Run discover** step to see the log. Success looks like:

    -> ats ...
       3459 postings
    3459 collected -> 125 pass keyword filters
    120 unique -> 25 not seen before

and the digest arrives in Telegram.

After this, it runs by itself daily at 13:00 UTC (about 06:00 Pacific). To
change that, edit the `cron` line in `.github/workflows/discover.yml`. Cron is
always in UTC - it does not follow your timezone or daylight saving.

---

## Step 6 - Stop running `discover` locally

Once it runs in the cloud, running it on your machine as well means two copies
with two separate `jobs.db` files. Dedup state diverges and you get the same
jobs twice.

From here: **cloud owns `discover`, your machine owns `boards`.**

The cloud starts with an empty database, so its first run re-sends the jobs you
have already seen locally. One duplicate wave, then it is clean.

---

## Step 7 - Publish the board to the web (optional)

Puts `board.html` on a URL you can open from a phone. Only that one file is
published; the database, company list and config stay in the private repo.

### 7a. Create the public repo

1. **https://github.com/new**
2. Name it **`job-board`** (must match `BOARD_REPO` in the workflow)
3. Select **Public** - GitHub Pages on a free account only works from a public
   repo. Upgrading to Pro does NOT make a Pages site private; access-controlled
   Pages is Enterprise only.
4. Tick **Add a README file** so the repo is not empty (Pages needs a commit)
5. **Create repository**

### 7b. Turn on Pages

In `job-board`: **Settings** -> **Pages** -> Source: **Deploy from a branch**,
Branch: **main**, folder: **/ (root)** -> **Save**.

Your URL will be `https://<your-username>.github.io/job-board/`.

### 7c. Create a token the bot can publish with

The workflow runs in the private repo and needs permission to write to the
public one. Its built-in token cannot do that, so create a scoped token:

1. github.com -> avatar -> **Settings** -> **Developer settings**
2. **Personal access tokens** -> **Fine-grained tokens** -> **Generate new token**
3. Name: `board-deploy`; Expiration: your choice (you will need to renew it)
4. **Repository access**: *Only select repositories* -> pick **`job-board`** only
5. **Permissions** -> Repository permissions -> **Contents: Read and write**
6. **Generate token** and copy it

Scoping it to one repo matters: a classic token with `repo` scope would let the
bot write to everything you own.

### 7d. Add it as a secret

In the **private** repo: Settings -> Secrets and variables -> Actions ->
**New repository secret**, named exactly **`BOARD_DEPLOY_TOKEN`**.

Until this secret exists the publish step skips itself and prints a note, so
nothing breaks in the meantime.

### 7e. Run and check

Run the workflow. The log ends with the published URL. First deploy takes a
minute or two; after that updates appear within a few minutes of each run.

The page is public - anyone with the URL can read it. It holds only public job
listings and no personal details, but your applied/dismissed marks are visible.

---

## Ongoing

| Task | How often | Command / place |
|---|---|---|
| Check company boards still resolve | Monthly | `.venv\Scripts\python.exe run_discover.py --verify` |
| Add newly-funded companies | Whenever you spot one | edit `companies.yaml`, commit, push |
| Run the LinkedIn/Google half | Daily-ish, manually | `.venv\Scripts\python.exe run_boards.py` |
| Tune what gets through | After a week of digests | `filters.title_include` in `config.yaml` |

Changes to `config.yaml` or `companies.yaml` only affect the cloud run after you
commit and push them:

    git add -A && git commit -m "Update target companies" && git push
