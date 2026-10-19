import os
# Plan sheets are slow to render; routine UI tests skip them (same switch as tcp_poc/tests). One test re-enables it.
os.environ.setdefault("TCP_RENDER_SHEET", "0")
