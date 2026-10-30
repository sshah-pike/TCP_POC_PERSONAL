"""Installs the test network block in a subprocess that inherited TCP_NETBLOCK=1 (see tests/support/netblock.py)."""
import os
import sys

if os.environ.get("TCP_NETBLOCK") == "1" and os.environ.get("TCP_LIVE") != "1":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
    from tests.support import netblock
    netblock.install()
