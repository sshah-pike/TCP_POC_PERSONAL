"""Root pytest configuration: the network is blocked for every test (CLAUDE.md, Tests).

Unit and integration tests make no live calls: any attempt to open a non-loopback socket (Azure Maps, OSM, Foundry...)
raises NetworkBlockedError. Loopback stays open because the web API tests talk to an in-process local server.
TCP_LIVE=1 lifts the block; only the S13 full-pipeline test and the user-run recorder use it.
Limit: the block is in-process. A test that starts a subprocess is not covered by it.
"""
import os
import socket

import pytest


class NetworkBlockedError(RuntimeError):
    pass


_LOOPBACK = ("127.", "::1", "localhost", "0.0.0.0")


def _is_local(address):
    if isinstance(address, (str, bytes)): return True      # AF_UNIX path
    host = address[0] if address else ""
    host = host.decode() if isinstance(host, bytes) else str(host)
    return host == "" or host.startswith(_LOOPBACK) or host == "::ffff:127.0.0.1"


def _guard(real):
    def wrapper(self, address, *args, **kwargs):
        if not _is_local(address):
            raise NetworkBlockedError(f"network blocked in tests: connect to {address!r}. Use a recorded fixture "
                                      "(tests/support) or a fake; live calls need TCP_LIVE=1 and are run by the user.")
        return real(self, address, *args, **kwargs)
    return wrapper


@pytest.fixture(scope="session", autouse=True)
def _block_network():
    if os.environ.get("TCP_LIVE") == "1":
        yield; return
    saved = socket.socket.connect, socket.socket.connect_ex
    socket.socket.connect = _guard(saved[0]); socket.socket.connect_ex = _guard(saved[1])
    try: yield
    finally: socket.socket.connect, socket.socket.connect_ex = saved
