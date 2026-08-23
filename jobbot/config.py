"""Loads .env (secrets) and config.yaml / companies.yaml (behaviour)."""
from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _env(key: str, default: str = "") -> str:
    return (os.getenv(key) or default).strip()


def _env_bool(key: str, default: bool = False) -> bool:
    raw = _env(key)
    if not raw:
        return default
    return raw.lower() in ("1", "true", "yes", "on")


def _load_yaml(name: str) -> dict:
    path = ROOT / name
    if not path.exists():
        raise FileNotFoundError(f"Missing {name} - copy it from the repo root.")
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


CFG = _load_yaml("config.yaml")
COMPANIES = _load_yaml("companies.yaml").get("companies", [])

# --- secrets / runtime ---
TELEGRAM_BOT_TOKEN = _env("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = _env("TELEGRAM_CHAT_ID")

EMAIL_SENDER = _env("EMAIL_SENDER")
EMAIL_PASSWORD = _env("EMAIL_PASSWORD")
EMAIL_RECEIVER = _env("EMAIL_RECEIVER")
SMTP_SERVER = _env("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(_env("SMTP_PORT", "587"))

ANTHROPIC_API_KEY = _env("ANTHROPIC_API_KEY")
LLM_MODEL = _env("LLM_MODEL", "claude-haiku-4-5")

APIFY_TOKEN = _env("APIFY_TOKEN")
APIFY_WELLFOUND_ACTOR = _env("APIFY_WELLFOUND_ACTOR")
APIFY_YC_ACTOR = _env("APIFY_YC_ACTOR")

DRY_RUN = _env_bool("DRY_RUN", True)

DB_PATH = ROOT / "jobs.db"

# --- behaviour ---
PROFILE = CFG.get("profile", {})
TARGETS = CFG.get("targets", {})
FILTERS = CFG.get("filters", {})
SCORING = CFG.get("scoring", {})
BOARDS = CFG.get("boards", {})
CANARY = CFG.get("canary", {})

SCORING_ENABLED = bool(SCORING.get("enabled", True)) and bool(ANTHROPIC_API_KEY)
MIN_SCORE = int(SCORING.get("min_score", 60))
ZERO_STREAK_WARNING = int(CANARY.get("zero_streak_warning", 3))


def notifications_configured() -> bool:
    return bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID) or bool(
        EMAIL_SENDER and EMAIL_PASSWORD and EMAIL_RECEIVER
    )
