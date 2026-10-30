"""Root pytest configuration: the network is blocked for every test (CLAUDE.md, Tests).

Unit and integration tests make no live calls: any attempt to open a non-loopback socket (Azure Maps, OSM, Foundry...)
raises NetworkBlockedError. Loopback stays open because the web API tests talk to an in-process local server.
TCP_LIVE=1 lifts the block; only the S13 full-pipeline test and the user-run recorder use it.
Subprocesses: the block also reaches any subprocess that inherits os.environ (TCP_NETBLOCK and PYTHONPATH are set
for the session). See tests/support/netblock.py for the limits.
"""
import os

import pytest

from tests.support import netblock
from tests.support.netblock import NetworkBlockedError  # noqa: F401  (re-exported for tests)


@pytest.fixture(scope="session", autouse=True)
def _block_network():
    if os.environ.get("TCP_LIVE") == "1":
        yield; return
    saved = {k: os.environ.get(k) for k in (netblock.ENV_FLAG, "PYTHONPATH")}
    netblock.install()
    os.environ[netblock.ENV_FLAG] = "1"
    os.environ["PYTHONPATH"] = os.pathsep.join(p for p in (netblock.SITE_DIR, saved["PYTHONPATH"]) if p)
    try: yield
    finally:
        netblock.uninstall()
        for k, v in saved.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v
