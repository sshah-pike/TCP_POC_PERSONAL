"""Find raw filesystem paths inside JSON-like data (S2: no raw path in any persisted JSON, D-77).

A raw path is a string value (or a key) that looks like a Windows drive path, a UNC path, an absolute POSIX path with at
least two segments, a home path, or a path with a parent-directory step. Store-relative keys ("<run_id>/output/plan.json")
are allowed.
"""
import re

SEP = r"[\\/]"
RAW_PATH_RE = re.compile(r"^(?:[A-Za-z]:" + SEP + r"|\\\\|/[^/\s]+/[^\s]|~" + SEP + r")|(?:^|" + SEP + r")\.\.(?:" + SEP + r"|$)")


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
    """[(location in the document, offending string)] for one parsed JSON document."""
    return list(_walk(doc, ""))
