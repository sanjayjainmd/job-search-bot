#!/usr/bin/env python
"""Local runner: LinkedIn + Google via jobspy.

Run this from your own machine on a residential connection. LinkedIn blocks
datacenter IPs, so this does NOT belong in GitHub Actions.

    py run_boards.py
"""
from __future__ import annotations

from jobbot.pipeline import run
from jobbot.sources import boards


def main() -> int:
    if not boards.available():
        print("jobspy is not installed. Run:")
        print("    py -m pip install -r requirements-boards.txt")
        return 1
    run("boards", [("jobspy", boards.fetch_all)])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
