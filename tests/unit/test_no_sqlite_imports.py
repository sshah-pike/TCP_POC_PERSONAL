"""D-84: the MVP stores state in files only. No sqlite3 import may remain in src/ or tests/ (backup/ is not scanned)."""
import ast, os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _python_files():
    for top in ("src", "tests"):
        for d, dirs, names in os.walk(os.path.join(ROOT, top)):
            dirs[:] = [x for x in dirs if x != "__pycache__"]
            for n in names:
                if n.endswith(".py"): yield os.path.join(d, n)


def _imports_sqlite(path):
    with open(path, encoding="utf-8") as f: tree = ast.parse(f.read(), path)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(a.name.split(".")[0] == "sqlite3" for a in node.names): return True
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "sqlite3": return True
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "__import__" and node.args \
                and getattr(node.args[0], "value", "") == "sqlite3": return True
    return False


def test_no_sqlite3_import_in_src_or_tests():
    assert [os.path.relpath(p, ROOT) for p in _python_files() if _imports_sqlite(p)] == []


def test_no_sqlite_adapter_module_left_in_src():
    assert not os.path.exists(os.path.join(ROOT, "src", "tcp_planner", "storage", "sqlite_state.py"))
