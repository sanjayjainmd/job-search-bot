"""Generates board.html - every job ever found, with its status.

The Telegram digest is a delta: what changed today. This is the opposite -
nothing is ever removed from it, so you can always see the whole matching set
and what you have done with each one.

Status can be changed two ways:

- From the page, on any device, if `board.status_api` is set in config.yaml.
  A static page cannot write to the database, so marks go to a small Vercel
  function backed by Redis (see vercel/README.md). That is what makes a mark
  on the phone show up on the laptop.
- From the command line with mark.py, which writes to jobs.db.

The two are deliberately separate: jobs.db records what was *sent*, the API
records your reading state on top of it. When both exist the API wins in the
page, because it is the one you can update from anywhere.
"""
from __future__ import annotations

import html
import json
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional

from . import config, db

STATUS_LABEL = {
    "new": "New",
    "seen": "Seen",
    "applied": "Applied",
    "dismissed": "Dismissed",
}

CSS = """
:root {
  --bg: #ffffff; --fg: #1a1a1a; --muted: #666; --line: #e2e2e2;
  --card: #fafafa; --accent: #1a56db; --badge: #eef2ff; --badge-fg: #3730a3;
  --stretch: #fff7ed; --stretch-fg: #9a3412; --stale: #b91c1c;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #14161a; --fg: #e8e8e8; --muted: #9aa0a6; --line: #2c2f36;
    --card: #1b1e24; --accent: #7aa2f7; --badge: #232a45; --badge-fg: #a5b4fc;
    --stretch: #2d2114; --stretch-fg: #fbbf24; --stale: #f87171;
  }
}
:root[data-theme="dark"] {
  --bg: #14161a; --fg: #e8e8e8; --muted: #9aa0a6; --line: #2c2f36;
  --card: #1b1e24; --accent: #7aa2f7; --badge: #232a45; --badge-fg: #a5b4fc;
  --stretch: #2d2114; --stretch-fg: #fbbf24; --stale: #f87171;
}
* { box-sizing: border-box; }
body {
  background: var(--bg); color: var(--fg); margin: 0; padding: 2rem 1rem;
  font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}
.wrap { max-width: 60rem; margin: 0 auto; }
h1 { font-size: 1.4rem; margin: 0 0 .25rem; }
.sub { color: var(--muted); font-size: .875rem; margin-bottom: 1.25rem; }
.controls { display: flex; flex-wrap: wrap; gap: 1rem; align-items: center;
            margin-bottom: 1.5rem; }
.tabs { display: flex; flex-wrap: wrap; gap: .5rem; }
.tab {
  border: 1px solid var(--line); background: var(--card); color: var(--fg);
  padding: .4rem .8rem; border-radius: 999px; cursor: pointer; font-size: .875rem;
}
.tab[aria-selected="true"] { background: var(--accent); color: #fff; border-color: var(--accent); }
.sortbox { margin-left: auto; font-size: .875rem; color: var(--muted); }
select {
  background: var(--card); color: var(--fg); border: 1px solid var(--line);
  border-radius: .35rem; padding: .35rem .5rem; font-size: .875rem;
}
.job {
  border: 1px solid var(--line); background: var(--card); border-radius: .5rem;
  padding: .9rem 1rem; margin-bottom: .75rem;
}
.job.stretch { background: var(--stretch); }
.job h2 { font-size: 1rem; margin: 0 0 .3rem; }
.job a { color: var(--accent); text-decoration: none; }
.job a:hover { text-decoration: underline; }
.meta { color: var(--muted); font-size: .8125rem; }
.row { display: flex; flex-wrap: wrap; gap: .5rem; align-items: center; margin-top: .4rem; }
.badge {
  background: var(--badge); color: var(--badge-fg); border-radius: .25rem;
  padding: .1rem .45rem; font-size: .75rem; font-weight: 600;
}
.badge.warm { background: var(--stretch); color: var(--stretch-fg); }
.stale { color: var(--stale); font-weight: 600; }
.ref {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .75rem;
  color: var(--muted); cursor: pointer; border: 1px dashed var(--line);
  padding: .1rem .35rem; border-radius: .25rem;
}
.reason { margin-top: .4rem; font-size: .875rem; }
.hook { margin-top: .3rem; font-size: .875rem; font-style: italic; color: var(--muted); }
.marks { display: flex; flex-wrap: wrap; gap: .35rem; margin-top: .6rem; }
.mark {
  border: 1px solid var(--line); background: transparent; color: var(--muted);
  border-radius: .35rem; padding: .3rem .6rem; font-size: .8125rem; cursor: pointer;
  min-height: 2rem;
}
.mark:hover { border-color: var(--accent); color: var(--fg); }
.mark[aria-pressed="true"] {
  background: var(--accent); color: #fff; border-color: var(--accent); font-weight: 600;
}
.empty { color: var(--muted); padding: 2rem 0; }
footer { color: var(--muted); font-size: .8125rem; margin-top: 2rem;
         border-top: 1px solid var(--line); padding-top: 1rem; }
code { background: var(--badge); padding: .1rem .3rem; border-radius: .2rem; }
#sync {
  font-size: .8125rem; color: var(--muted); margin-bottom: 1rem; min-height: 1.2em;
  display: flex; flex-wrap: wrap; gap: .5rem; align-items: center;
}
#sync.bad { color: var(--stale); }
#sync input {
  background: var(--bg); color: var(--fg); border: 1px solid var(--line);
  border-radius: .35rem; padding: .35rem .5rem; font-size: .8125rem;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace; min-width: 22rem;
  max-width: 100%;
}
#sync button {
  background: var(--accent); color: #fff; border: 0; border-radius: .35rem;
  padding: .4rem .8rem; font-size: .8125rem; cursor: pointer;
}
#sync a { color: var(--accent); cursor: pointer; text-decoration: underline; }
"""

JS_CORE = """
const list = document.getElementById('list');
const tabs = document.querySelectorAll('.tab');
const sortSel = document.getElementById('sort');
let filter = 'new';

function num(el, key, fallback) {
  const v = el.dataset[key];
  return (v === undefined || v === '') ? fallback : Number(v);
}

function counts() {
  const c = {new: 0, seen: 0, applied: 0, dismissed: 0};
  Array.from(list.children).forEach(j => { c[j.dataset.status] = (c[j.dataset.status] || 0) + 1; });
  tabs.forEach(t => {
    const f = t.dataset.filter;
    const n = f === 'all' ? list.children.length : (c[f] || 0);
    t.textContent = t.dataset.label + ' (' + n + ')';
  });
}

function render() {
  tabs.forEach(t => t.setAttribute('aria-selected', String(t.dataset.filter === filter)));
  const jobs = Array.from(list.children);
  const mode = sortSel.value;
  jobs.sort((a, b) => {
    if (mode === 'score') return num(b, 'score', -1) - num(a, 'score', -1);
    if (mode === 'found') return num(b, 'found', 0) - num(a, 'found', 0);
    if (mode === 'oldest') return num(a, 'posted', 9e15) - num(b, 'posted', 9e15);
    return num(b, 'posted', -1) - num(a, 'posted', -1);
  });
  let shown = 0;
  jobs.forEach(j => {
    const match = filter === 'all' || j.dataset.status === filter;
    j.style.display = match ? '' : 'none';
    if (match) shown++;
    list.appendChild(j);
  });
  document.getElementById('empty').style.display = shown ? 'none' : '';
  counts();
}

tabs.forEach(t => t.addEventListener('click', () => { filter = t.dataset.filter; render(); }));
sortSel.addEventListener('change', render);
document.querySelectorAll('.ref').forEach(r => r.addEventListener('click', () => {
  navigator.clipboard && navigator.clipboard.writeText(r.dataset.ref);
  const original = r.textContent; r.textContent = 'copied';
  setTimeout(() => { r.textContent = original; }, 900);
}));
"""

JS_SYNC = """
const API = %(api)s;
const sync = document.getElementById('sync');

function setCardStatus(card, status) {
  card.dataset.status = status;
  card.querySelectorAll('.mark').forEach(b =>
    b.setAttribute('aria-pressed', String(b.dataset.set === status)));
}

function storedKey() {
  return (localStorage.getItem('board_key') || '').trim();
}

// A ?key=... parameter lets one link configure a new device, so handing the
// board to someone else is a URL rather than a URL plus a 40-character string.
// It is consumed on arrival: saved to local storage, then stripped from the
// address bar with replaceState so it does not sit in the visible URL or get
// copied onward when someone shares the page from their address bar.
(function adoptKeyFromUrl() {
  const params = new URLSearchParams(window.location.search);
  const fromUrl = (params.get('key') || '').trim();
  if (!fromUrl) return;
  localStorage.setItem('board_key', fromUrl);
  params.delete('key');
  const rest = params.toString();
  history.replaceState(null, '', window.location.pathname + (rest ? '?' + rest : ''));
})();

function showKeyForm(message) {
  sync.className = 'bad';
  sync.innerHTML = '';
  const label = document.createElement('span');
  label.textContent = message || 'Enter your board key to sync marks across devices:';
  const input = document.createElement('input');
  input.type = 'text';
  input.placeholder = 'board key';
  input.autocapitalize = 'off';
  input.autocomplete = 'off';
  input.spellcheck = false;
  const save = document.createElement('button');
  save.textContent = 'Save';
  const submit = () => {
    const v = input.value.trim();
    if (!v) { input.focus(); return; }
    localStorage.setItem('board_key', v);
    loadStatuses();
  };
  save.addEventListener('click', submit);
  input.addEventListener('keydown', e => { if (e.key === 'Enter') submit(); });
  sync.append(label, input, save);
  input.focus();
}

function showSynced(text) {
  sync.className = '';
  sync.innerHTML = '';
  const msg = document.createElement('span');
  msg.textContent = text;
  const change = document.createElement('a');
  change.textContent = 'change key';
  change.addEventListener('click', () => {
    localStorage.removeItem('board_key');
    showKeyForm('Enter your board key:');
  });
  sync.append(msg, change);
}

async function api(method, body) {
  const key = storedKey();
  if (!key) throw new Error('no key');
  const resp = await fetch(API, {
    method,
    headers: {'Content-Type': 'application/json', 'X-Board-Key': key},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (resp.status === 401) { localStorage.removeItem('board_key'); throw new Error('key rejected'); }
  if (!resp.ok) throw new Error('HTTP ' + resp.status);
  return resp.json();
}

async function loadStatuses() {
  if (!storedKey()) { showKeyForm(); render(); return; }
  sync.className = ''; sync.textContent = 'Syncing statuses...';
  try {
    const data = await api('GET');
    Array.from(list.children).forEach(card => {
      setCardStatus(card, data[card.dataset.ref] || 'new');
    });
    render();
    showSynced('Synced - marks are shared across your devices.');
  } catch (err) {
    if (err.message === 'key rejected') {
      showKeyForm('That key was rejected. Try again:');
    } else {
      sync.className = 'bad';
      sync.textContent = 'Not synced (' + err.message + '). Marks below are from the last run.';
    }
    render();
  }
}

list.addEventListener('click', async (ev) => {
  const btn = ev.target.closest('.mark');
  if (!btn) return;
  const card = btn.closest('.job');
  const prev = card.dataset.status;
  const next = btn.dataset.set;
  setCardStatus(card, next);          // optimistic
  counts();
  try {
    await api('POST', {ref: card.dataset.ref, status: next});
    sync.className = ''; sync.textContent = 'Saved.';
  } catch (err) {
    setCardStatus(card, prev);        // roll back so the page never lies
    counts();
    if (err.message === 'key rejected') showKeyForm('That key was rejected. Try again:');
    else { sync.className = 'bad'; sync.textContent = 'Could not save (' + err.message + ').'; }
  }
});

loadStatuses();
"""


def _e(text) -> str:
    return html.escape(str(text or ""), quote=True)


def _epoch(day: Optional[str]) -> str:
    """Sortable integer for a YYYY-MM-DD string; empty when unknown."""
    if not day:
        return ""
    try:
        return str(int(datetime.strptime(day[:10], "%Y-%m-%d").timestamp()))
    except ValueError:
        return ""


def _age_label(posted: Optional[str]) -> str:
    """Human age, flagged when a req has clearly been open a long time."""
    if not posted:
        return ""
    try:
        days = (date.today() - datetime.strptime(posted[:10], "%Y-%m-%d").date()).days
    except ValueError:
        return ""
    if days < 0:
        return ""
    if days == 0:
        return "posted today"
    if days == 1:
        return "posted yesterday"
    if days < 31:
        return f"posted {days}d ago"
    months = days // 30
    label = f"posted {months}mo ago"
    # A req open this long is usually evergreen rather than a live opening.
    return f'<span class="stale">{label}</span>' if days >= 180 else label


def _marks(current: str) -> str:
    buttons = "".join(
        f'<button class="mark" data-set="{key}" '
        f'aria-pressed="{"true" if key == current else "false"}">{_e(label)}</button>'
        for key, label in STATUS_LABEL.items()
    )
    return f'<div class="marks">{buttons}</div>'


def _job_card(job: dict, marking: bool) -> str:
    ref = job["dedup_key"][:8]
    tier = job.get("tier") or "primary"
    classes = "job stretch" if tier == "stretch" else "job"
    posted = job.get("posted_at")
    status = job.get("status") or "new"

    bits = []
    if job.get("score") is not None:
        label = f"{job['score']}/100"
        if job.get("fit"):
            label += f" {job['fit']}"
        bits.append(f'<span class="badge">{_e(label)}</span>')
    if tier == "stretch":
        bits.append('<span class="badge warm">worth a look</span>')
    if not marking:
        bits.append(f'<span class="badge">{_e(STATUS_LABEL.get(status, "New"))}</span>')
    bits.append(f'<span class="ref" data-ref="{_e(ref)}" title="click to copy">{_e(ref)}</span>')

    meta = [_e(job["company"])]
    if job.get("location"):
        meta.append(_e(job["location"]))
    meta.append(_e(job.get("source")))
    age = _age_label(posted)
    if age:
        meta.append(age)
    elif job.get("first_seen"):
        meta.append(f'found {_e(job["first_seen"][:10])}')

    attrs = (f'data-ref="{_e(ref)}"'
             f' data-status="{_e(status)}"'
             f' data-posted="{_epoch(posted)}"'
             f' data-found="{_epoch(job.get("first_seen"))}"'
             f' data-score="{job["score"] if job.get("score") is not None else ""}"')

    parts = [
        f'<article class="{classes}" {attrs}>',
        f'  <h2><a href="{_e(job["url"])}" target="_blank" rel="noopener">{_e(job["title"])}</a></h2>',
        f'  <div class="meta">{" &middot; ".join(meta)}</div>',
        f'  <div class="row">{"".join(bits)}</div>',
    ]
    if job.get("reason"):
        parts.append(f'  <div class="reason">{_e(job["reason"])}</div>')
    if job.get("hook"):
        parts.append(f'  <div class="hook">{_e(job["hook"])}</div>')
    if marking:
        parts.append("  " + _marks(status))
    parts.append("</article>")
    return "\n".join(parts)


def render(jobs: List[dict], counts: dict[str, int]) -> str:
    api = (config.CFG.get("board", {}) or {}).get("status_api", "") or ""
    marking = bool(api)
    total = len(jobs)

    tab_defs = [("new", "New"), ("seen", "Seen"), ("applied", "Applied"),
                ("dismissed", "Dismissed"), ("all", "All")]
    tab_html = "\n".join(
        f'<button class="tab" data-filter="{k}" data-label="{_e(label)}" '
        f'aria-selected="false">{_e(label)} '
        f'({total if k == "all" else counts.get(k, 0)})</button>'
        for k, label in tab_defs)

    cards = "\n".join(_job_card(j, marking) for j in jobs)
    dated = sum(1 for j in jobs if j.get("posted_at"))

    sync_bar = '<div id="sync"></div>' if marking else ""
    js = JS_CORE + ("\nrender();\n" if not marking else "")
    if marking:
        js += JS_SYNC % {"api": json.dumps(api)}

    if marking:
        footer = ("Tap <b>New / Seen / Applied / Dismissed</b> on any job. Marks are "
                  "stored centrally, so a change on your phone shows up on either "
                  "laptop. The board asks for the key once per device.")
    else:
        footer = ("Change a status with the short reference: "
                  "<code>py mark.py &lt;ref&gt; applied</code> &mdash; click a reference "
                  "to copy it. Set <code>board.status_api</code> in config.yaml to mark "
                  "from the page instead.")

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Job Board</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
  <h1>Job Board</h1>
  <div class="sub">Every job the bot has ever matched. Nothing is removed here -
    the Telegram digest shows only what is new, this shows everything.
    Posting dates known for {dated} of {total}.</div>
  {sync_bar}
  <div class="controls">
    <div class="tabs">{tab_html}</div>
    <label class="sortbox">Sort
      <select id="sort">
        <option value="posted">newest posted</option>
        <option value="oldest">oldest posted</option>
        <option value="score">best score</option>
        <option value="found">recently found</option>
      </select>
    </label>
  </div>
  <div id="list">
{cards}
  </div>
  <div class="empty" id="empty" style="display:none">Nothing in this category.</div>
  <footer>
    {footer}
    Roles open 6 months or more are flagged in red: usually evergreen reqs
    rather than live openings.
  </footer>
</div>
<script>{js}</script>
</body>
</html>
"""


def write(path: Path | None = None) -> Path:
    target = Path(path) if path else Path(__file__).resolve().parent.parent / "board.html"
    jobs = db.all_jobs()
    target.write_text(render(jobs, db.status_counts()), encoding="utf-8")
    return target
