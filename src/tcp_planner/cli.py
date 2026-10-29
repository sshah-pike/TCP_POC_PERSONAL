#!/usr/bin/env python3
"""Command-line entry point (Pipeline 2). Implementation lives in the tcp_planner package.

  python -m tcp_planner.cli --kml site.kml --road-type RURAL
  python -m tcp_planner.cli --lat 39.600762 --lon -82.960710 --road-type URBAN_LOW_SPEED
  tcp-planner --offline supported                   (installed script; synthetic self-test, no network)

Output is an AUTOMATED DRAFT - NOT APPROVED FOR FIELD USE. The original POC script (tcp_demo.py) is kept,
untracked, in backup/archive/legacy_code/tcp_demo_legacy_backup.py for reference only.
"""
import sys


def main(argv=None):
    """`cli.py project ...` runs a multi-point KML as a project (one run per zone); anything else is the single-location
    pipeline."""
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "project":
        from tcp_planner.orchestration.project_cli import main as project_main
        return project_main(argv[1:])
    from tcp_planner.orchestration.pipeline import main as pipeline_main
    return pipeline_main(argv)


if __name__ == "__main__":
    sys.exit(main())
