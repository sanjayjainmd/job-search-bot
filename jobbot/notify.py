"""Delivery: one batched digest per run, not one message per job."""
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


def build_digest(jobs: List[Job], warnings: List[str], runner: str,
                 stats: dict[str, int]) -> tuple[str, str]:
    """Returns (html_for_telegram, plaintext_for_email)."""
    hjobs = sorted(jobs, key=lambda j: (j.score is None, -(j.score or 0)))

    counts = ", ".join(f"{src}={n}" for src, n in sorted(stats.items())) or "no sources ran"
    header_txt = f"[{runner}] {len(hjobs)} new job(s) - {counts}"
    h = [f"<b>{_esc(header_txt)}</b>"]
    t = [header_txt, "=" * len(header_txt)]

    for w in warnings:
        h.append(f"\n⚠️ <i>{_esc(w)}</i>")
        t.append(f"\n[WARNING] {w}")

    for job in hjobs:
        score_line = ""
        if job.score is not None:
            score_line = f"{job.score}/100 {job.fit}"

        block_h = [f"\n<b><a href=\"{_esc(job.url)}\">{_esc(job.title)}</a></b>",
                   f"🏢 {_esc(job.company)}"]
        if job.location:
            block_h.append(f"📍 {_esc(job.location)}")
        if score_line:
            block_h.append(f"🎯 {_esc(score_line)} - {_esc(job.reason or '')}")
        if job.hook:
            block_h.append(f"✉️ <i>{_esc(job.hook)}</i>")
        block_h.append(f"<i>{_esc(job.source)}</i>")
        h.append("\n".join(block_h))

        block_t = [f"\n{job.title}", f"  Company : {job.company}"]
        if job.location:
            block_t.append(f"  Location: {job.location}")
        if score_line:
            block_t.append(f"  Score   : {score_line} - {job.reason or ''}")
        if job.hook:
            block_t.append(f"  Hook    : {job.hook}")
        block_t.append(f"  Source  : {job.source}")
        block_t.append(f"  Link    : {job.url}")
        t.append("\n".join(block_t))

    if not hjobs:
        h.append("\n<i>Nothing new that cleared the filters.</i>")
        t.append("\nNothing new that cleared the filters.")

    return "\n\n".join(h), "\n".join(t)


def send_telegram(html_body: str) -> bool:
    if not (config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID):
        return False
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    ok = True
    for part in _chunk(html_body):
        try:
            resp = requests.post(
                url,
                json={
                    "chat_id": config.TELEGRAM_CHAT_ID,
                    "text": part,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=30,
            )
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
    """Send the strongest matches as individual messages with a one-tap button.

    Deliberately URL buttons only. A button that does something *inside*
    Telegram (mark applied, snooze, thumbs up) needs a bot that listens for
    callbacks, which means a persistent process - see README.
    """
    if not (config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID):
        return 0

    delivery = config.CFG.get("delivery", {})
    top_n = int(delivery.get("highlight_top", 3))
    min_score = int(delivery.get("highlight_min_score", 75))
    if top_n <= 0:
        return 0

    ranked = sorted((j for j in jobs if (j.score or 0) >= min_score),
                    key=lambda j: -(j.score or 0))[:top_n]
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


def deliver(jobs: List[Job], warnings: List[str], runner: str,
            stats: dict[str, int]) -> bool:
    """Send the digest. Returns True if it reached at least one channel.

    In DRY_RUN, prints to console and reports success so the run still
    marks jobs as seen only when the caller wants it to.
    """
    html_body, text_body = build_digest(jobs, warnings, runner, stats)

    if config.DRY_RUN:
        print("\n----- DRY RUN: digest would be sent -----")
        print(text_body)
        print("----- end digest -----\n")
        return True

    if not config.notifications_configured():
        print("  ! no notification channel configured - printing instead")
        print(text_body)
        return False

    subject = f"[{runner}] {len(jobs)} new job(s)"
    if warnings:
        subject = "⚠️ " + subject

    sent_tg = send_telegram(html_body)
    if sent_tg:
        n = send_highlights(jobs)
        if n:
            print(f"  {n} highlight message(s) sent with Open buttons")
    sent_email = send_email(subject, text_body)
    return sent_tg or sent_email
