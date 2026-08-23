#!/usr/bin/env python
"""Cloud runner: direct ATS polling (+ optional Apify). Safe on GitHub Actions.

    py run_discover.py            # normal run
    py run_discover.py --verify   # check which companies.yaml slugs actually work
"""
from __future__ import annotations

import sys

from jobbot import config
from jobbot.pipeline import run
from jobbot.sources import apify, ats, directories


def verify() -> int:
    print(f"Verifying {len(config.COMPANIES)} company board(s) from companies.yaml\n")
    good, bad = [], []
    for company in config.COMPANIES:
        ok, message = ats.probe(company)
        label = f"{company.get('name', '?'):<20} {company.get('ats', '?'):<11} {company.get('slug', '?')}"
        print(f"  [{'OK ' if ok else 'BAD'}] {label:<50} {message}")
        (good if ok else bad).append(company.get("name", "?"))
    print(f"\n{len(good)} working, {len(bad)} to fix or remove.")
    if bad:
        print("Broken: " + ", ".join(bad))
        print("\nFind the right slug from the company's careers page URL, then edit companies.yaml.")
    return 0


def main() -> int:
    if "--verify" in sys.argv:
        return verify()

    sources = [
        ("ats", lambda: ats.fetch_all(config.COMPANIES)),
        ("directories", directories.fetch_all),
    ]
    if apify.enabled():
        sources.append(("apify", apify.fetch_all))

    run("discover", sources)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
