#!/usr/bin/env python
"""Print your Telegram chat ID without needing a browser.

    py get_chat_id.py

Requires TELEGRAM_BOT_TOKEN in .env, and that you have sent your bot at least
one message first (a bot cannot start a conversation).
"""
from __future__ import annotations

import requests

from jobbot import config


def main() -> int:
    token = config.TELEGRAM_BOT_TOKEN
    if not token:
        print("TELEGRAM_BOT_TOKEN is not set in .env.")
        print("Get one from @BotFather (/newbot), paste it into .env, then re-run.")
        return 1

    try:
        me = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=20).json()
    except requests.RequestException as exc:
        print(f"Could not reach Telegram: {exc}")
        return 1

    if not me.get("ok"):
        print(f"Telegram rejected the token: {me.get('description', me)}")
        return 1
    print(f"Bot OK: @{me['result'].get('username', '?')}\n")

    try:
        data = requests.get(
            f"https://api.telegram.org/bot{token}/getUpdates", timeout=20
        ).json()
    except requests.RequestException as exc:
        print(f"Could not reach Telegram: {exc}")
        return 1

    if not data.get("ok"):
        print(f"getUpdates failed: {data.get('description', data)}")
        return 1

    chats = {}
    for update in data.get("result", []):
        msg = (update.get("message") or update.get("channel_post")
               or update.get("edited_message") or {})
        chat = msg.get("chat")
        if chat:
            chats[chat["id"]] = chat

    if not chats:
        print("No messages found yet.")
        print(f"Open Telegram, find @{me['result'].get('username', 'your bot')},")
        print("send it any message (e.g. 'hello'), then run this again.")
        return 1

    print("Found these chats:\n")
    for chat_id, chat in chats.items():
        label = (chat.get("title")
                 or " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")]))
                 or chat.get("username", ""))
        print(f"  TELEGRAM_CHAT_ID={chat_id}    ({chat.get('type')}: {label})")

    print("\nCopy the line above into .env, then set DRY_RUN=false.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
