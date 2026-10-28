"""The test network block, shared by the root conftest (this process) and sitecustomize (subprocesses).

Any attempt to open a non-loopback socket raises NetworkBlockedError. Loopback stays open because the web API
tests talk to an in-process local server. Subprocesses are covered when they inherit os.environ: the conftest
sets TCP_NETBLOCK=1 and puts SITE_DIR first on PYTHONPATH, and SITE_DIR/sitecustomize.py calls install().
Not covered: a subprocess started with an explicit env= that drops those variables (use subprocess_env()), and
python -I / -S, which ignore PYTHONPATH.
"""
import os
import socket

ENV_FLAG = "TCP_NETBLOCK"
SITE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "netblock_site")
_LOOPBACK = ("127.", "::1", "localhost", "0.0.0.0")
_saved = None


class NetworkBlockedError(RuntimeError):
    pass


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


def install():
    global _saved
    if _saved: return
    _saved = socket.socket.connect, socket.socket.connect_ex
    socket.socket.connect = _guard(_saved[0]); socket.socket.connect_ex = _guard(_saved[1])


def uninstall():
    global _saved
    if not _saved: return
    socket.socket.connect, socket.socket.connect_ex = _saved
    _saved = None


def subprocess_env(env):
    """Add the block to an explicit subprocess environment dict (a copy is returned). A no-op under TCP_LIVE=1."""
    env = dict(env)
    if os.environ.get(ENV_FLAG) == "1":
        env[ENV_FLAG] = "1"
        env["PYTHONPATH"] = os.pathsep.join(p for p in (SITE_DIR, env.get("PYTHONPATH")) if p)
    return env
