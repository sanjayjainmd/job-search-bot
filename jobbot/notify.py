"""Delivery: one batched digest per run, in two tiers."""
from __future__ import annotations

import html
import smtplib
from email.message import EmailMessage
from typing import List

import requests

from . import config
from .models import Job

TELEGRAM_LIMIT = 3900  # 4096 hard cap, with headroom


def _esc(text: str) -> str:
    return html.escape(text or "", quote=False)


def _chunk(text: str, limit: int = TELEGRAM_LIMIT) -> List[str]:
    """Split on blank lines so a job block is never cut in half."""
    blocks = text.split("\n\n")
    chunks, current = [], ""
    for block in blocks:
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) > limit and current:
            chunks.append(current)
            current = block
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def _sorted(jobs: List[Job]) -> List[Job]:
    return sorted(jobs, key=lambda j: (j.score is None, -(j.score or 0)))


def _detail_line(job: Job) -> str:
    parts = [f"{job.score}/100"]
    if job.fit:
        parts.append(job.fit)
    if job.seniority:
        parts.append(f"level: {job.seniority}")
    return " | ".join(parts)


def _job_html(job: Job) -> str:
    lines = [f"\n<b><a href=\"{_esc(job.url)}\">{_esc(job.title)}</a></b>",
             f"\U0001F3E2 {_esc(job.company)}"]
    if job.location:
        lines.append(f"\U0001F4CD {_esc(job.location)}")
    if job.score is not None:
        lines.append(f"\U0001F3AF {_esc(_detail_line(job))} - {_esc(job.reason or '')}")
    if job.hook:
        lines.append(f"✉️ <i>{_esc(job.hook)}</i>")
    tail = job.source + (f" | posted {job.posted_at}" if job.posted_at else "")
    lines.append(f"<i>{_esc(tail)}</i>")
    return "\n".join(lines)


def _job_text(job: Job) -> str:
    lines = [f"\n{job.title}", f"  Company : {job.company}"]
    if job.location:
        lines.append(f"  Location: {job.location}")
    if job.score is not None:
        lines.append(f"  Score   : {_detail_line(job)} - {job.reason or ''}")
    if job.hook:
        lines.append(f"  Hook    : {job.hook}")
    lines.append(f"  Source  : {job.source}")
    if job.posted_at:
        lines.append(f"  Posted  : {job.posted_at}")
    lines.append(f"  Link    : {job.url}")
    return "\n".join(lines)


STRETCH_NOTE = ("Senior-sounding titles at larger companies. Kept rather than "
                "dropped, so nothing is lost silently.")


def build_digest(primary: List[Job], stretch: List[Job], warnings: List[str],
                 runner: str, stats: dict[str, int]) -> tuple[str, str]:
    """Returns (html_for_telegram, plaintext_for_email)."""
    primary, stretch = _sorted(primary), _sorted(stretch)

    counts = ", ".join(f"{s}={n}" for s, n in sorted(stats.items())) or "no sources ran"
    header = f"[{runner}] {len(primary)} match(es)"
    if stretch:
        header += f" + {len(stretch)} worth a look"
    header += f" - {counts}"

    h = [f"<b>{_esc(header)}</b>"]
    t = [header, "=" * len(header)]

    for w in warnings:
        h.append(f"\n⚠️ <i>{_esc(w)}</i>")
        t.append(f"\n[WARNING] {w}")

    if primary:
        for job in primary:
            h.append(_job_html(job))
            t.append(_job_text(job))
    else:
        h.append("\n<i>No new matches.</i>")
        t.append("\nNo new matches.")

    if stretch:
        h.append(f"\n<b>WORTH A LOOK</b>\n<i>{_esc(STRETCH_NOTE)}</i>")
        t.append(f"\n{'-' * 40}\nWORTH A LOOK\n{STRETCH_NOTE}")
        for job in stretch:
            h.append(_job_html(job))
            t.append(_job_text(job))

    return "\n\n".join(h), "\n".join(t)


def send_telegram(html_body: str) -> bool:
    if not (config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID):
        return False
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    ok = True
    for part in _chunk(html_body):
        try:
            resp = requests.post(url, json={
                "chat_id": config.TELEGRAM_CHAT_ID,
                "text": part,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as exc:
            print(f"  ! telegram send failed: {exc}")
            ok = False
    return ok


def send_email(subject: str, body: str) -> bool:
    if not (config.EMAIL_SENDER and config.EMAIL_PASSWORD and config.EMAIL_RECEIVER):
        return False
    msg = EmailMessage()
    msg["From"] = config.EMAIL_SENDER
    msg["To"] = config.EMAIL_RECEIVER
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(config.SMTP_SERVER, config.SMTP_PORT, timeout=45) as server:
            server.starttls()
            server.login(config.EMAIL_SENDER, config.EMAIL_PASSWORD)
            server.send_message(msg)
        return True
    except (smtplib.SMTPException, OSError) as exc:
        print(f"  ! email send failed: {exc}")
        return False


def _draft_opener(job: Job) -> str:
    """First line of a cold email. The user reviews and sends it - never the bot."""
    if job.hook:
        return job.hook
    return (f"I saw the {job.title} opening at {job.company} and wanted to reach out"
            f" - my background is finance with a focus on AI infrastructure.")


def send_highlights(jobs: List[Job]) -> int:
    """Strongest matches as individual messages with a one-tap button.

    URL buttons only. A button that acts *inside* Telegram (mark applied,
    snooze) needs a bot that listens for callbacks, which means a persistent
    process - see README.
    """
    if not (config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID):
        return 0

    delivery = config.CFG.get("delivery", {})
    top_n = int(delivery.get("highlight_top", 3))
    min_score = int(delivery.get("highlight_min_score", 75))
    if top_n <= 0:
        return 0

    ranked = _sorted([j for j in jobs if (j.score or 0) >= min_score])[:top_n]
    if not ranked:
        return 0

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    sent = 0
    for job in ranked:
        lines = [f"⭐ <b>{_esc(job.title)}</b>", f"\U0001F3E2 {_esc(job.company)}"]
        if job.location:
            lines.append(f"\U0001F4CD {_esc(job.location)}")
        if job.score is not None:
            lines.append(f"\U0001F3AF {job.score}/100 - {_esc(job.reason or '')}")
        lines.append("\n<i>Tap to copy an opening line:</i>")
        lines.append(f"<code>{_esc(_draft_opener(job))}</code>")
        try:
            resp = requests.post(url, json={
                "chat_id": config.TELEGRAM_CHAT_ID,
                "text": "\n".join(lines),
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
                "reply_markup": {"inline_keyboard": [[
                    {"text": "\U0001F4C4 Open posting", "url": job.url},
                ]]},
            }, timeout=30)
            resp.raise_for_status()
            sent += 1
        except requests.RequestException as exc:
            print(f"  ! highlight send failed for {job.company}: {exc}")
    return sent


def deliver(primary: List[Job], stretch: List[Job], warnings: List[str],
            runner: str, stats: dict[str, int]) -> bool:
    """Send the digest. Returns True if it reached at least one channel."""
    html_body, text_body = build_digest(primary, stretch, warnings, runner, stats)

    if config.DRY_RUN:
        print("\n----- DRY RUN: digest would be sent -----")
        print(text_body)
        print("----- end digest -----\n")
        return True

    if not config.notifications_configured():
        print("  ! no notification channel configured - printing instead")
        print(text_body)
        return False

    subject = f"[{runner}] {len(primary)} match(es)"
    if stretch:
        subject += f" + {len(stretch)} worth a look"
    if warnings:
        subject = "[!] " + subject

    sent_tg = send_telegram(html_body)
    if sent_tg:
        n = send_highlights(primary)   # highlights come from primary only
        if n:
            print(f"  {n} highlight message(s) sent with Open buttons")
    sent_email = send_email(subject, text_body)
    return sent_tg or sent_email
