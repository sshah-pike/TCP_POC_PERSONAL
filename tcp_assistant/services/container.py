"""Service container: one JsonStore, audit service and tool registry per data directory (created on first use)."""
import threading

from .. import flags
from ..core.audit import AuditService
from ..core.tools import ToolRegistry
from ..repositories.json_store import JsonStore

_LOCK = threading.Lock()
_C = {}


class Container:
    def __init__(self, root):
        self.root = root
        self.store = JsonStore(root)
        self.audit = AuditService(root)
        self.tools = ToolRegistry()
        from . import registry
        registry.register_all(self)


def container():
    root = flags.data_dir()
    with _LOCK:
        if root not in _C: _C[root] = Container(root)
        return _C[root]


def reset():
    with _LOCK: _C.clear()
