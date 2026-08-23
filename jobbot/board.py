"""Generates board.html - every job ever found, with its status.

The Telegram digest is a delta: what changed today. This is the opposite -
nothing is ever removed from it, so you can always see the whole matching set
and what you have done with each one.

Status is changed with mark.py, not from the page, because a static file
cannot write back to the database and a server would be overkill.
"""
from __future__ import annotations

import html
from pathlib import Path
from typing import List

from . import db

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
  --stretch: #fff7ed; --stretch-fg: #9a3412;
}
:root:not([data-theme="light"]) { }
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #14161a; --fg: #e8e8e8; --muted: #9aa0a6; --line: #2c2f36;
    --card: #1b1e24; --accent: #7aa2f7; --badge: #232a45; --badge-fg: #a5b4fc;
    --stretch: #2d2114; --stretch-fg: #fbbf24;
  }
}
:root[data-theme="dark"] {
  --bg: #14161a; --fg: #e8e8e8; --muted: #9aa0a6; --line: #2c2f36;
  --card: #1b1e24; --accent: #7aa2f7; --badge: #232a45; --badge-fg: #a5b4fc;
  --stretch: #2d2114; --stretch-fg: #fbbf24;
}
* { box-sizing: border-box; }
body {
  background: var(--bg); color: var(--fg); margin: 0; padding: 2rem 1rem;
  font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}
.wrap { max-width: 60rem; margin: 0 auto; }
h1 { font-size: 1.4rem; margin: 0 0 .25rem; }
.sub { color: var(--muted); font-size: .875rem; margin-bottom: 1.5rem; }
.tabs { display: flex; flex-wrap: wrap; gap: .5rem; margin-bottom: 1.5rem; }
.tab {
  border: 1px solid var(--line); background: var(--card); color: var(--fg);
  padding: .4rem .8rem; border-radius: 999px; cursor: pointer; font-size: .875rem;
}
.tab[aria-selected="true"] { background: var(--accent); color: #fff; border-color: var(--accent); }
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
.ref {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .75rem;
  color: var(--muted); cursor: pointer; border: 1px dashed var(--line);
  padding: .1rem .35rem; border-radius: .25rem;
}
.reason { margin-top: .4rem; font-size: .875rem; }
.hook { margin-top: .3rem; font-size: .875rem; font-style: italic; color: var(--muted); }
.empty { color: var(--muted); padding: 2rem 0; }
footer { color: var(--muted); font-size: .8125rem; margin-top: 2rem;
         border-top: 1px solid var(--line); padding-top: 1rem; }
code { background: var(--badge); padding: .1rem .3rem; border-radius: .2rem; }
"""

JS = """
const tabs = document.querySelectorAll('.tab');
const jobs = document.querySelectorAll('.job');
function apply(filter) {
  tabs.forEach(t => t.setAttribute('aria-selected', String(t.dataset.filter === filter)));
  let shown = 0;
  jobs.forEach(j => {
    const match = filter === 'all' || j.dataset.status === filter;
    j.style.display = match ? '' : 'none';
    if (match) shown++;
  });
  document.getElementById('empty').style.display = shown ? 'none' : '';
}
tabs.forEach(t => t.addEventListener('click', () => apply(t.dataset.filter)));
document.querySelectorAll('.ref').forEach(r => r.addEventListener('click', () => {
  navigator.clipboard && navigator.clipboard.writeText(r.dataset.ref);
  const original = r.textContent; r.textContent = 'copied';
  setTimeout(() => { r.textContent = original; }, 900);
}));
apply('new');
"""


def _e(text) -> str:
    return html.escape(str(text or ""), quote=True)


def _job_card(job: dict) -> str:
    ref = job["dedup_key"][:8]
    tier = job.get("tier") or "primary"
    classes = "job stretch" if tier == "stretch" else "job"

    bits = []
    if job.get("score") is not None:
        label = f"{job['score']}/100"
        if job.get("fit"):
            label += f" {job['fit']}"
        bits.append(f'<span class="badge">{_e(label)}</span>')
    if tier == "stretch":
        bits.append('<span class="badge warm">worth a look</span>')
    bits.append(f'<span class="badge">{_e(STATUS_LABEL.get(job.get("status"), "New"))}</span>')
    bits.append(f'<span class="ref" data-ref="{_e(ref)}" title="click to copy">{_e(ref)}</span>')

    parts = [
        f'<article class="{classes}" data-status="{_e(job.get("status") or "new")}">',
        f'  <h2><a href="{_e(job["url"])}" target="_blank" rel="noopener">{_e(job["title"])}</a></h2>',
        f'  <div class="meta">{_e(job["company"])}'
        + (f' &middot; {_e(job["location"])}' if job.get("location") else "")
        + f' &middot; {_e(job.get("source"))} &middot; found {_e((job.get("first_seen") or "")[:10])}</div>',
        f'  <div class="row">{"".join(bits)}</div>',
    ]
    if job.get("reason"):
        parts.append(f'  <div class="reason">{_e(job["reason"])}</div>')
    if job.get("hook"):
        parts.append(f'  <div class="hook">{_e(job["hook"])}</div>')
    parts.append("</article>")
    return "\n".join(parts)


def render(jobs: List[dict], counts: dict[str, int]) -> str:
    total = len(jobs)
    tabs = [("new", f"New ({counts.get('new', 0)})"),
            ("seen", f"Seen ({counts.get('seen', 0)})"),
            ("applied", f"Applied ({counts.get('applied', 0)})"),
            ("dismissed", f"Dismissed ({counts.get('dismissed', 0)})"),
            ("all", f"All ({total})")]
    tab_html = "\n".join(
        f'<button class="tab" data-filter="{k}" aria-selected="false">{_e(v)}</button>'
        for k, v in tabs)
    cards = "\n".join(_job_card(j) for j in jobs) or ""

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
    the Telegram digest shows only what is new, this shows everything.</div>
  <div class="tabs">{tab_html}</div>
  {cards}
  <div class="empty" id="empty" style="display:none">Nothing in this category.</div>
  <footer>
    Change a status with the short reference:
    <code>py mark.py &lt;ref&gt; applied</code> &mdash; click a reference to copy it.
    Valid statuses: new, seen, applied, dismissed.
  </footer>
</div>
<script>{JS}</script>
</body>
</html>
"""


def write(path: Path | None = None) -> Path:
    target = Path(path) if path else Path(__file__).resolve().parent.parent / "board.html"
    jobs = db.all_jobs()
    target.write_text(render(jobs, db.status_counts()), encoding="utf-8")
    return target
