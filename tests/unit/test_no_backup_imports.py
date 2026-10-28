"""Live code never reaches backup/, spikes/ or var/: no imports from them and no sys.path entries pointing at them."""
import ast, os, re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FORBIDDEN = ("backup", "spikes", "var")
LIVE = ("src", "tests", "scripts")
PATH_HACK = re.compile(r"sys\.path\.(insert|append)\([^)]*\b(backup|spikes|var)\b")


def live_files():
    for top in LIVE:
        for d, dirs, files in os.walk(os.path.join(ROOT, top)):
            dirs[:] = [x for x in dirs if x != "__pycache__"]
            for n in files:
                if n.endswith(".py"): yield os.path.join(d, n)


def test_live_code_does_not_import_backup_spikes_or_var():
    offenders = []
    for path in live_files():
        src = open(path, encoding="utf-8").read()
        for node in ast.walk(ast.parse(src)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                [node.module or ""] if isinstance(node, ast.ImportFrom) and not node.level else []
            for name in names:
                if name.split(".")[0] in FORBIDDEN: offenders.append((os.path.relpath(path, ROOT), name))
            if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "import_module" and node.args \
                    and isinstance(node.args[0], ast.Constant) and str(node.args[0].value).split(".")[0] in FORBIDDEN:
                offenders.append((os.path.relpath(path, ROOT), node.args[0].value))
        if PATH_HACK.search(src): offenders.append((os.path.relpath(path, ROOT), "sys.path"))
    assert not offenders, offenders
