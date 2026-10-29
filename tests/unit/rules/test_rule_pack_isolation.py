"""The engine reads no rule-pack file directly: only rule_pack_store.py (v1) and the legacy POC loader touch rule_pack/.

The POC loader stays allowlisted until the pipeline switch-over to pack v1 is approved. src/ never imports the
dev-time PDF tools used by spikes/rule_pack_extract/.
"""
import ast, os, re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SRC = os.path.join(ROOT, "src", "tcp_planner")
ALLOWED = {"rules/rule_pack_store.py", "rules/rule_pack_loader.py", "config/settings.py"}
DIRECT = re.compile(r"RULE_PACK_DIR|[\"']rule_pack[/\\\\]|[\"']pack\.json[\"']|APPROVED_TWO_LANE_POC_RULE_PACK")
PDF_TOOLS = {"fitz", "pymupdf", "pdfplumber", "pdfminer", "pypdf"}


def _py_files():
    for d, dirs, files in os.walk(SRC):
        dirs[:] = [x for x in dirs if x != "__pycache__"]
        for n in files:
            if n.endswith(".py"): yield os.path.relpath(os.path.join(d, n), SRC).replace(os.sep, "/")


def test_no_module_reads_rule_pack_files_directly():
    offenders = [rel for rel in _py_files() if rel not in ALLOWED
                 and DIRECT.search(open(os.path.join(SRC, rel), encoding="utf-8").read())]
    assert not offenders, offenders


def test_src_never_imports_pdf_tools():
    offenders = []
    for rel in _py_files():
        for node in ast.walk(ast.parse(open(os.path.join(SRC, rel), encoding="utf-8").read())):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            offenders += [(rel, n) for n in names if n.split(".")[0] in PDF_TOOLS]
    assert not offenders, offenders
