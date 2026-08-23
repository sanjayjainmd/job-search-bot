#!/usr/bin/env python
"""Cloud runner: direct ATS polling (+ optional Apify). Safe on GitHub Actions.

    py run_discover.py            # normal run
    py run_discover.py --verify   # check which companies.yaml slugs actually work
    py run_discover.py --stats    # is dedup working? how many new jobs per day?
    py run_discover.py --find-companies   # scan job newsletters for new companies
"""
from __future__ import annotations

import sys

from jobbot import config, db, discovery
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


def show_stats() -> int:
    """Answers: is it only sending new things, or repeating itself?"""
    db.init_db()
    s = db.stats()

    print(f"Jobs remembered : {s['total']}  ({s['notified']} of them were sent)")
    if not s["total"]:
        print()
        print("The database is empty, so the next run will treat every job as new.")
        print("On GitHub Actions that means the cache did not restore.")
        return 0

    print(f"First recorded  : {s['first']}")
    print(f"Last recorded   : {s['last']}")
    print()
    print("New jobs recorded per day. This is the number to watch: it should")
    print("fall to a trickle once the initial backlog has cleared. If it stays")
    print("high every day, dedup is not working.")
    for day, count in s["by_day"]:
        print(f"  {day}  {'#' * min(count, 50)} {count}")

    print()
    print("Recent source runs (postings fetched, before any filtering):")
    for ts, runner, source, count in s["runs"]:
        print(f"  {ts}  {runner:<9} {source:<12} {count}")
    return 0


def main() -> int:
    if "--verify" in sys.argv:
        return verify()
    if "--stats" in sys.argv:
        return show_stats()
    if "--find-companies" in sys.argv:
        discovery.run()
        return 0

    sources = [
        ("ats", lambda: ats.fetch_all(config.COMPANIES)),
    ]
    # directories.fetch_all is a stub and always returns nothing, which makes
    # the canary warn on every run. A permanent false alarm teaches you to
    # ignore warnings, so it is not registered until it actually does something.
    _ = directories
    if apify.enabled():
        sources.append(("apify", apify.fetch_all))

    run("discover", sources)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
