#!/usr/bin/env python3
"""TCP POC command-line entry point (Pipeline 2). Implementation lives in the tcp_planner package.

  python tcp_demo.py --kml site.kml --road-type RURAL
  python tcp_demo.py --lat 39.600762 --lon -82.960710 --road-type URBAN_LOW_SPEED
  python tcp_demo.py --offline supported            (synthetic self-test, no network)

Output is an AUTOMATED DRAFT - NOT APPROVED FOR FIELD USE. The original script is kept in
archive/legacy_code/tcp_demo_legacy_backup.py for reference only.
"""
import sys
from tcp_planner.orchestration.pipeline import main

if __name__ == "__main__":
    sys.exit(main())
