#!/usr/bin/env python3
"""Command-line entry point (Pipeline 2). Implementation lives in the tcp_planner package.

  python -m tcp_planner.cli --kml site.kml --road-type RURAL
  python -m tcp_planner.cli --lat 39.600762 --lon -82.960710 --road-type URBAN_LOW_SPEED
  tcp-planner --offline supported                   (installed script; synthetic self-test, no network)

Output is an AUTOMATED DRAFT - NOT APPROVED FOR FIELD USE. The original POC script (tcp_demo.py) is kept,
untracked, in backup/archive/legacy_code/tcp_demo_legacy_backup.py for reference only.
"""
import sys
from tcp_planner.orchestration.pipeline import main

if __name__ == "__main__":
    sys.exit(main())
