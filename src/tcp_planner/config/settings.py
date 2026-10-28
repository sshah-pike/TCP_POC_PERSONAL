"""Repository locations. Every data, config and asset path is resolved from the repository root here."""
import os

PACKAGE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # src/tcp_planner
SRC_DIR = os.path.dirname(PACKAGE_DIR)
PROJECT_ROOT = os.path.dirname(SRC_DIR)
CONFIG_DIR = os.path.join(PROJECT_ROOT, "config")
RULE_PACK_DIR = os.path.join(PROJECT_ROOT, "rule_pack")
ASSETS_DIR = os.path.join(PROJECT_ROOT, "assets")
VAR_DIR = os.path.join(PROJECT_ROOT, "var")  # run outputs, labels, assistant data, debug dumps (gitignored)
