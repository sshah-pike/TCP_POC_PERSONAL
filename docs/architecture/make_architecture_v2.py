import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
import sys
OUT = sys.argv[1]
C = {"data": "#1f6fb2", "det": "#13807f", "ai": "#6b3fa0", "gate": "#f0b23a", "imm": "#0b2e59", "panel": "#eef4fb"}
fig = plt.figure(figsize=(24, 17.5)); ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, 240); ax.set_ylim(0, 175); ax.axis("off")


def box(x, y, w, h, text, kind, new=False, fs=8.6):
    fc = C[kind]; tc = "#1b1b1b" if kind == "gate" else "white"
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.25,rounding_size=1.2", fc=fc,
                                ec="#d62828" if new else fc, lw=2.6 if new else 0.8, ls="--" if new else "-", zorder=2))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs, color=tc, zorder=3, linespacing=1.25,
            fontweight="bold" if kind == "imm" else "normal")
    if kind == "ai":
        ax.text(x + 1.0, y + h - 0.8, "AI", fontsize=7.5, color="#6b3fa0", fontweight="bold", va="top", zorder=4,
                bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none"))
    if new:
        ax.text(x + w - 0.4, y + h + 0.3, "NEW", fontsize=7, color="white", fontweight="bold", ha="right", va="center",
                zorder=5, bbox=dict(boxstyle="round,pad=0.2", fc="#d62828", ec="none"))


def arrow(x1, y1, x2, y2, color="#2b3a4a", ls="-"):
    ax.annotate("", (x2, y2), (x1, y1), arrowprops=dict(arrowstyle="-|>", color=color, lw=1.4, ls=ls, shrinkA=0, shrinkB=0),
                zorder=1)


def path(pts, color="#2b3a4a", ls="-"):
    for a, b in zip(pts[:-2], pts[1:-1]):
        ax.plot([a[0], b[0]], [a[1], b[1]], color=color, lw=1.4, ls=ls, zorder=1)
    arrow(*pts[-2], *pts[-1], color=color, ls=ls)


def band(y0, y1, title):
    ax.add_patch(FancyBboxPatch((2, y0), 236, y1 - y0, boxstyle="round,pad=0.2,rounding_size=1.5", fc="#f7fafd",
                                ec="#9fb6cf", lw=1.2, zorder=0))
    ax.add_patch(FancyBboxPatch((2, y1 - 4.5), 236, 4.5, boxstyle="round,pad=0.2,rounding_size=1.5", fc=C["imm"],
                                ec=C["imm"], zorder=0))
    ax.text(4, y1 - 2.25, title, color="white", fontsize=12.5, fontweight="bold", va="center")


ax.text(120, 171.5, "Traffic Control Plan Automation - Two-Pipeline Architecture v2 (updated after POC)", ha="center",
        fontsize=20, fontweight="bold", color=C["imm"])
ax.text(120, 167.6, "Same principles: AI proposes or observes, the deterministic engine decides, SMEs approve.   "
        "Red dashed boxes = additions from POC lessons.   AI is used in 4 places only.", ha="center", fontsize=10.5, color="#333")

# legend
x = 6
for k, t in [("data", "data / services"), ("det", "deterministic"), ("ai", "AI step"), ("gate", "review gate"),
             ("imm", "immutable / versioned output")]:
    ax.add_patch(FancyBboxPatch((x, 160.6), 4, 2.2, boxstyle="round,pad=0.1", fc=C[k], ec=C[k], zorder=3))
    ax.text(x + 5, 161.7, t, fontsize=9.5, va="center", zorder=3); x += 30
ax.add_patch(FancyBboxPatch((x, 160.6), 4, 2.2, boxstyle="round,pad=0.1", fc="white", ec="#d62828", ls="--", lw=2, zorder=3))
ax.text(x + 5, 161.7, "new / changed after POC", fontsize=9.5, va="center", zorder=3)

# ---------------- PIPELINE 1 ----------------
band(119, 158, "PIPELINE 1 - RULE MANAGEMENT  (offline, runs when regulations or standards change)")
p1 = [("Regulatory sources\nMUTCD, State DOT,\nCounty/City, Client", "data"),
      ("Document registry\n+ SHA-256\nchange check", "det"),
      ("Structure parsing\n+ section hashing", "det"),
      ("Changed sections\nonly", "det"),
      ("Rule extraction &\nclassification\n(candidate only)", "ai"),
      ("Canonical rules,\nformulas, tables,\nTAs, exceptions", "det"),
      ("Automated\nvalidation", "det"),
      ("SME review\n& approval", "gate"),
      ("PostgreSQL versions\n+ dependencies +\njurisdiction overrides", "data"),
      ("Immutable\napproved\nrule pack", "imm")]
w, gap, y = 20.6, 2.9, 135
X = [4 + i * (w + gap) for i in range(len(p1))]
for i, (t, k) in enumerate(p1):
    box(X[i], y, w, 15, t, k)
    if i:
        arrow(X[i] - gap, y + 7.5, X[i], y + 7.5)
add1 = [(X[5] - 10, "More Typical Applications\n(lane closure, flagger, police,\nmulti-lane, state signs e.g. MA)", X[5] + 10),
        (X[6] + 6, "Rule-pack consistency check\n(unreachable / conflicting options,\ne.g. TA1-SIGN-01)", X[6] + 10),
        (X[8] - 3, "Approved implementation parameters\n(sign lateral offset from shoulder,\nclearances, speed -> road-type table)", X[7] + 10)]
for x0, t, tx in add1:
    box(x0, 121.5, 36, 10, t, "det", new=True, fs=8)
    sx = min(max(tx, x0 + 2), x0 + 34)
    arrow(sx, 131.5, tx, y)

# ---------------- PIPELINE 2 ----------------
band(37, 115, "PIPELINE 2 - DRAFT TCP GENERATION  (per project: one fixed deterministic workflow, no agents)")
yA = 93; h = 15
box(4, yA, 18, h, "KML or\ncoordinates", "data")
box(26, yA, 24, h, "Input validation\n+ project geometry\n(multi-point: split per\npole / work zone)", "det", new=True)
box(54, yA + 7.8, 26, 7.2, "Azure Maps imagery\n(interim: USGS NAIP)", "data", fs=8)
box(54, yA, 26, 7.2, "OSM road network\n(TLS via OS trust store)", "data", fs=8)
box(84, yA, 32, h, "Vision observation\nversioned prompt, zoomed crops,\nroad-edge pixel positions,\nfeatures with coordinates", "ai", new=True)
box(120, yA, 32, h, "Evidence fusion +\nper-field confidence\n+ OSM vs image centerline\ncross-check", "det", new=True)
box(156, yA, 22, h, "Critical fields\ntrusted?", "gate")
box(184, yA, 26, h, "Canonical\nSite Model\n(versioned)", "imm")
box(156, 79.5, 22, 8.5, "Human map review\n& correction", "gate", fs=8)
arrow(22, yA + 8, 26, yA + 8); arrow(50, yA + 8, 54, yA + 12.3); arrow(50, yA + 8, 54, yA + 3.7)
arrow(80, yA + 12.3, 84, yA + 8); arrow(80, yA + 3.7, 84, yA + 8)
arrow(116, yA + 8, 120, yA + 8); arrow(152, yA + 8, 156, yA + 8)
arrow(178, yA + 8, 184, yA + 8); ax.text(179, yA + 9.6, "YES", fontsize=8, color="#1b7f3b", fontweight="bold")
arrow(167, yA, 167, 88.0); ax.text(168, 90.2, "NO", fontsize=8, color="#c0392b", fontweight="bold")
path([(178, 83.7), (204, 83.7), (204, yA)])
# pinned rule pack from Pipeline 1 to TA selection / rule engine
path([(X[9] + 10, y), (X[9] + 10, 117), (229, 117), (229, 77.5)], color=C["imm"])
ax.text(230, 100, "pinned\napproved\nrule pack", fontsize=8.5, color=C["imm"], fontweight="bold")

# row B: deterministic generation
yB = 60; h = 13
rowB = [("Eligibility +\njurisdiction resolver\nSUPPORTED / REVIEW /\nUNSUPPORTED", "det", False),
        ("TA / pattern\nselection", "det", False),
        ("Deterministic rule\nengine (WHAT)\nsigns, tapers, devices", "det", False),
        ("Geometric layout (WHERE)\noffset from shoulder edge,\napproved value", "det", True),
        ("Canonical\nPlan JSON\n+ prompt/model ids", "imm", True),
        ("Independent validator\nseparate geometry source\n(image edges, not OSM only)", "det", True),
        ("Pass?", "gate", False),
        ("Correction loop\n(back to plan)", "gate", False)]
xs = [4, 40, 64, 94, 128, 152, 186, 204]; ws = [32, 20, 26, 30, 20, 30, 12, 20]
for (t, k, n), x0, ww in zip(rowB, xs, ws):
    box(x0, yB, ww, h, t, k, new=n, fs=8.2)
for i in range(1, 7):
    arrow(xs[i - 1] + ws[i - 1], yB + 6.5, xs[i], yB + 6.5)
arrow(198, yB + 6.5, 204, yB + 6.5); ax.text(198.3, yB + 8.2, "FAIL", fontsize=7.5, color="#c0392b", fontweight="bold")
path([(214, yB), (214, yB - 1.6), (138, yB - 1.6), (138, yB)], color="#c0392b", ls="--")
# site model -> eligibility ; rule pack -> TA/rule engine
path([(190, yA), (190, 90.5), (2.8, 90.5), (2.8, yB + 6.5), (4, yB + 6.5)])
path([(229, 77.5), (77, 77.5), (77, yB + h)], color=C["imm"])
path([(77, 77.5), (50, 77.5), (50, yB + h)], color=C["imm"])

# row C: render, QA, approve
yC = 40.5; h = 13
rowC = [("Debug render\n(matplotlib)\nfast check / tests", "det", False),
        ("CAD render: AutoCAD\nDWT template + approved\nsign blocks, aerial, title\n(template cached, async)", "det", True),
        ("Plot sheet\nPDF / DWG", "det", True),
        ("Visual QA\nAI checks plotted sheet:\nsign on lane? overlaps?", "ai", True),
        ("SME review + edit assistant\n(AI: request -> structured\nchange -> re-validate)", "gate", False),
        ("Approval +\nplan SHA-256", "det", False),
        ("Immutable\naudit", "imm", False)]
xs = [12, 40, 72, 92, 122, 160, 184]; ws = [24, 28, 16, 26, 34, 20, 16]
for (t, k, n), x0, ww in zip(rowC, xs, ws):
    box(x0, yC, ww, h, t, k, new=n, fs=8.2)
for i in range(1, len(xs)):
    arrow(xs[i - 1] + ws[i - 1], yC + 6.5, xs[i], yC + 6.5)
path([(192, yB), (192, 56.0), (6, 56.0), (6, yC + 6.5), (12, yC + 6.5)])
ax.text(193, 57.0, "PASS", fontsize=7.5, color="#1b7f3b", fontweight="bold")
ax.text(123.2, yC + h - 1.0, "AI", fontsize=7.5, color="#6b3fa0", fontweight="bold", va="top",
        bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="#6b3fa0"))
path([(105, yC), (105, 38.6), (139, 38.6), (139, yC)], color="#c0392b", ls="--")
ax.text(141, 38.6, "QA issue -> REVIEW_REQUIRED", fontsize=7.5, color="#c0392b", va="center")


# ---------------- bottom panels ----------------
def panel(x0, y0, ww, hh, title, lines, color):
    ax.add_patch(FancyBboxPatch((x0, y0), ww, hh, boxstyle="round,pad=0.2,rounding_size=1.5", fc=C["panel"], ec=color, lw=1.6))
    ax.text(x0 + 1.5, y0 + hh - 2.2, title, fontsize=11.5, fontweight="bold", color=color, va="center")
    ax.text(x0 + 1.5, y0 + hh - 5.0, "\n".join(lines), fontsize=10.2, va="top", linespacing=1.42, color="#1b1b1b")


panel(2, 1.0, 74, 34, "Where AI is used (4 places) - it never decides", [
    "1  Pipeline 1 - rule extraction & classification",
    "    -> candidates only; SME approves before publishing",
    "2  Pipeline 2 - site observation from imagery (lanes,",
    "    edges, work side, driveways) -> evidence, then gated",
    "3  Pipeline 2 - visual QA of the plotted sheet -> flags only",
    "4  Pipeline 2 - SME edit assistant: request -> structured",
    "    change, re-validated by the deterministic engine",
    "",
    "AI NEVER chooses: rules, TA, signs, distances, coordinates,",
    "eligibility, validation result or approval.",
    "No agents in the core flow; prompts and models are versioned."], C["ai"])
panel(78, 1.0, 82, 34, "Lessons learned from the POC runs", [
    "- Real KMLs are multi-point (5 poles); POC accepted only one point",
    "- Real urban sites (4 lanes, sidewalks, signals) fall outside TA-1",
    "- OSM centerline ~2.4 m off -> a sign landed on the lane line, and the",
    "  validator passed because it used the same OSM geometry",
    "- Sign lateral offset is not in the rule pack (2 m config guess)",
    "- Table 6B-1 is keyed by road type; no approved speed mapping",
    "- Rule-pack gaps: SHOULDER WORK option unreachable; 'approaching",
    "  traffic' read as both directions needs SME confirmation",
    "- Most driveways are unmapped in OSM; vision needs zoomed crops",
    "- Corporate TLS proxy blocked OSM; AI credits ran out (failed closed)",
    "- CAD: DWG TrueView cannot automate; need AutoCAD/ODA + block library"], "#c0392b")
panel(162, 1.0, 76, 34, "Additions (cross-cutting)", [
    "- Prompt & model registry: pinned versions + hashes",
    "  recorded on every Site Model and Plan",
    "- Evaluation set of SME-labelled real sites; regression",
    "  gate before promoting any prompt or model",
    "- Imagery: Azure Maps (target); USGS NAIP interim (US)",
    "- CAD: AutoCAD Core Console / Autodesk cloud automation,",
    "  cached template, block + title-field mapping",
    "- Ops: AI budget alerts, proxy/TLS config, Key Vault",
    "  secrets, OpenTelemetry dashboards",
    "- SME corrections captured as labelled data",
    "- Multi-point: group poles into work zones or per-pole runs"], C["det"])

fig.savefig(OUT + ".png", dpi=110)
fig.savefig(OUT + ".svg")
