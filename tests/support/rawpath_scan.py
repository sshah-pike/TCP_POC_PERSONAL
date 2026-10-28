"""Find raw filesystem paths inside persisted JSON (S2 acceptance: no raw path in any persisted JSON).

A raw path is a string value (or a key) that looks like a Windows drive path, a UNC path, an absolute POSIX path
with at least two segments, or a path with a parent-directory step. Store-relative keys ("<run_id>/output/plan.json")
are allowed.
"""
import json, os, re

SEP = r"[\\/]"
RAW_PATH_RE = re.compile(r"^(?:[A-Za-z]:" + SEP + r"|\\\\|/[^/\s]+/[^\s]|~" + SEP + r")|(?:^|" + SEP + r")\.\.(?:" + SEP + r"|$)")
SCAN_SUFFIXES = (".json", ".jsonl")


def _walk(node, where):
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(k, str) and RAW_PATH_RE.search(k): yield f"{where}/<key {k!r}>", k
            yield from _walk(v, f"{where}/{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node): yield from _walk(v, f"{where}[{i}]")
    elif isinstance(node, str) and RAW_PATH_RE.search(node):
        yield where, node


def find_raw_paths(doc):
    """[(json pointer-ish location, offending string)] for one parsed JSON document."""
    return list(_walk(doc, ""))


def scan_tree(root):
    """{relative file: [(location, value)]} for every .json/.jsonl file under root that holds a raw path."""
    hits = {}
    for base, _dirs, names in os.walk(root):
        for n in sorted(names):
            if not n.endswith(SCAN_SUFFIXES): continue
            p = os.path.join(base, n); rel = os.path.relpath(p, root).replace("\\", "/")
            try:
                with open(p, encoding="utf-8") as f:
                    docs = [json.loads(ln) for ln in f if ln.strip()] if n.endswith(".jsonl") else [json.load(f)]
            except (OSError, ValueError):
                continue
            found = [h for d in docs for h in find_raw_paths(d)]
            if found: hits[rel] = found
    return hits
