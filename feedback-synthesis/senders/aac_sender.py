#!/usr/bin/env python3
"""AAC sender — RETIRED 2026-05-23.

The AAC pillar was retired per NATRIX directive on 2026-05-23. This
sender is a no-op stub that exits with code 1 so any cron/launchd
caller fails visibly instead of silently sending nothing.
"""

from __future__ import annotations

import sys


if __name__ == "__main__":
    sys.stderr.write("aac_sender.py: AAC pillar was retired 2026-05-23. Aborting.\n")
    sys.exit(1)
