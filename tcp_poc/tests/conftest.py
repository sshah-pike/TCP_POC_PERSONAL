import os
# Plan sheets are slow to render (~20-40 s); routine tests skip them. test_plan_sheet re-enables it.
os.environ.setdefault("TCP_RENDER_SHEET", "0")
