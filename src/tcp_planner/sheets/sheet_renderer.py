"""Plan sheet in the CADD house style, composed on the frame extracted from an approved CADD PDF
(see scripts/build_sheet_frame.py). Consumes the PlanModel and the aerial image only; no regulatory logic.
Symbol sizes (diamond callout, sign bar, work-zone box) are drawing symbols, not to scale."""
import json, math, os
from tcp_planner.config.settings import ASSETS_DIR
from tcp_planner.contracts import FT
from tcp_planner.geometry.local_frame import enu, signed_lateral, offset_point, at
from tcp_planner.sheets.debug_renderers import WATERMARK

ASSET_DIR = os.path.join(ASSETS_DIR, "sheet")
SCALES_FT_PER_IN = (20, 30, 40, 50, 60, 80, 100, 200)   # standard engineering plot scales
ORANGE = "#FF6A00"
DIAMOND_R_IN = 0.75      # callout half-diagonal on paper (inches) - drawing symbol
CALLOUT_OFFSET_IN = 1.9  # callout centre distance from the sign symbol (inches)


class SheetRenderer:
    def __init__(self, asset_dir=ASSET_DIR):
        self.dir = asset_dir

    def available(self):
        if os.environ.get("TCP_RENDER_SHEET", "1") == "0":
            return False
        return all(os.path.isfile(os.path.join(self.dir, f)) for f in ("sheet_frame.png", "sheet_layout.json"))

    def _load_layout(self):
        with open(os.path.join(self.dir, "sheet_layout.json"), encoding="utf-8") as f: return json.load(f)

    def view(self, plan):
        """Choose plot scale and view window (local metres about the plan imagery centre)."""
        R = self._load_layout()["regions_pt"]
        meta = plan["imagery"]; c = meta["center"]
        local = lambda p: enu(p["latitude"], p["longitude"], c["latitude"], c["longitude"])
        cl = [local(p) for p in plan["site_geometry"]["centerline"]]
        objs = plan["objects"]; signs = [o for o in objs if o["object_type"] == "SIGN"]
        work = next(o for o in objs if o["object_type"] == "WORK_LOCATION")
        pts = [local(o["placement"]) for o in objs]

        # ---- smallest standard scale where objects AND callouts fit, clear of the notes box ----
        vx0, vy0, vx1, vy1 = R["viewport"]; vw_in, vh_in = (vx1 - vx0) / 72, (vy1 - vy0) / 72
        nb = R["general_notes_box"]

        def outward(p):
            _, s, lat = signed_lateral(cl, p)
            _, (tx, ty) = at(cl, s)
            return ((-ty, tx) if lat >= 0 else (ty, -tx)), s, lat

        def drawn_points(u):
            out = list(pts)
            for o in signs:
                sp = local(o["placement"]); n, _, _ = outward(sp)
                dc = (sp[0] + n[0] * CALLOUT_OFFSET_IN * u, sp[1] + n[1] * CALLOUT_OFFSET_IN * u)
                rr = (DIAMOND_R_IN + 0.15) * u
                out += [(dc[0] + rr, dc[1] + rr), (dc[0] - rr, dc[1] - rr - 0.45 * u), (dc[0] - rr, dc[1] + rr), (dc[0] + rr, dc[1] - rr)]
            return out

        S = None
        for cand in SCALES_FT_PER_IN:
            u = cand * FT; dp = drawn_points(u)
            xs = [q[0] for q in dp]; ys = [q[1] for q in dp]; pad = 0.35 * u
            if (max(xs) - min(xs)) + 2 * pad > vw_in * u or (max(ys) - min(ys)) + 2 * pad > vh_in * u:
                continue
            cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
            # shift the view (within the slack) so nothing sits under the notes box
            ok = False
            slack_x = (vw_in * u - (max(xs) - min(xs)) - 2 * pad) / 2; slack_y = (vh_in * u - (max(ys) - min(ys)) - 2 * pad) / 2
            for fx in (0, -1, -0.5, 0.5, 1):
                for fy in (0, 1, 0.5, -0.5, -1):
                    ccx, ccy = cx + fx * slack_x, cy + fy * slack_y
                    left = ccx - vw_in * u / 2; top = ccy + vh_in * u / 2
                    to_pt = lambda q: (vx0 + (q[0] - left) / u * 72, vy0 + (top - q[1]) / u * 72)
                    if not any(nb[0] - 10 <= to_pt(q)[0] <= nb[2] + 10 and nb[1] - 10 <= to_pt(q)[1] <= nb[3] + 10 for q in dp):
                        ok = True; cx, cy = ccx, ccy; break
                if ok: break
            if ok:
                S = cand; break
        if S is None:
            S = SCALES_FT_PER_IN[-1]; u = S * FT; dp = drawn_points(u)
            cx = (max(q[0] for q in dp) + min(q[0] for q in dp)) / 2; cy = (max(q[1] for q in dp) + min(q[1] for q in dp)) / 2
        u = S * FT  # metres per drawing inch
        half_w, half_h = vw_in * u / 2, vh_in * u / 2

        return dict(S=S, u=u, cx=cx, cy=cy, half_w=half_w, half_h=half_h, local=local, cl=cl, objs=objs, signs=signs,
                    work=work, outward=outward, meta=meta, R=R)

    def view_half_extent_m(self, plan):
        """Half-size of a north-up square image (about the work reference) that covers the whole sheet view."""
        v = self.view(plan)
        return 1.03 * max(abs(v["cx"]) + v["half_w"], abs(v["cy"]) + v["half_h"])

    def render(self, plan, image, pdf_path, png_path, image_meta=None):
        import numpy as np
        import matplotlib; matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Polygon, Rectangle
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = None

        lay = self._load_layout()
        Wpt, Hpt = lay["page_size_pt"]; R = lay["regions_pt"]
        frame = np.asarray(Image.open(os.path.join(self.dir, "sheet_frame.png")).convert("RGB"))
        k = frame.shape[1] / Wpt

        v = self.view(plan)
        S, u, cx, cy, half_w, half_h = v["S"], v["u"], v["cx"], v["cy"], v["half_w"], v["half_h"]
        local, cl, objs, signs, work, outward, meta = (v[k] for k in ("local", "cl", "objs", "signs", "work", "outward", "meta"))
        vx0, vy0, vx1, vy1 = R["viewport"]; nb = R["general_notes_box"]; c = meta["center"]
        imeta = image_meta or meta
        fig = plt.figure(figsize=(Wpt / 72, Hpt / 72), dpi=72)
        base = fig.add_axes([0, 0, 1, 1]); base.axis("off")
        base.imshow(frame, extent=(0, Wpt, Hpt, 0), interpolation="lanczos")
        base.set_xlim(0, Wpt); base.set_ylim(Hpt, 0)

        # ---- viewport: the aerial as supplied (full colour, no wash), in local metres, north up ----
        vp = fig.add_axes([vx0 / Wpt, 1 - vy1 / Hpt, (vx1 - vx0) / Wpt, (vy1 - vy0) / Hpt]); vp.axis("off")
        gw, gh = imeta["ground_extent_m"]["width"], imeta["ground_extent_m"]["height"]
        ox, oy = enu(imeta["center"]["latitude"], imeta["center"]["longitude"], c["latitude"], c["longitude"])
        aerial = np.asarray(image.convert("RGB"))
        vp.imshow(aerial, extent=(ox - gw / 2, ox + gw / 2, oy - gh / 2, oy + gh / 2), interpolation="lanczos")
        vp.set_xlim(cx - half_w, cx + half_w); vp.set_ylim(cy - half_h, cy + half_h); vp.set_aspect("equal")

        # work location (legend: WORK ZONE) - symbol, not to scale
        wp = local(work["placement"]); n, s0, _ = outward(wp); _, (tx, ty) = at(cl, s0)
        L, D = 0.45 * u, 0.18 * u
        box = [(wp[0] + tx * a + n[0] * b, wp[1] + ty * a + n[1] * b)
               for a, b in ((-L / 2, -D / 2), (L / 2, -D / 2), (L / 2, D / 2), (-L / 2, D / 2))]
        vp.add_patch(Polygon(box, closed=True, fc=(1, 0, 0, 0.25), ec="red", lw=1.6, hatch="////", zorder=5))
        if work["placement"].get("path"):
            vp.plot(*zip(*[local(q) for q in work["placement"]["path"]]), color="red", lw=2.5, zorder=5)
        vp.annotate("WORK LOCATION", wp, xytext=(wp[0] + n[0] * 0.6 * u, wp[1] + n[1] * 0.6 * u), fontsize=9,
                    fontweight="bold", ha="center", va="center", zorder=7,
                    bbox=dict(boxstyle="square,pad=0.2", fc="white", ec="black", lw=0.6),
                    arrowprops=dict(arrowstyle="-", color="black", lw=0.7))

        # street name on the road
        road = plan["site_summary"].get("road_name") or ""
        if road:
            span = abs(signs[0]["placement"]["station_m"] - s0) if signs else 2 * u
            (lx, ly), (tx2, ty2) = at(cl, s0 - 0.45 * span)
            ang = math.degrees(math.atan2(ty2, tx2))
            ang = ang - 180 if ang > 90 else ang + 180 if ang < -90 else ang
            vp.text(lx, ly, road.upper(), rotation=ang, rotation_mode="anchor", ha="center", va="center", fontsize=13,
                    family="serif", zorder=6, bbox=dict(boxstyle="square,pad=0.1", fc=(1, 1, 1, 0.75), ec="none"))

        # signs: roadside symbol + callout diamond + dimension from the work location
        for o in signs:
            p = o["placement"]; sp = local(p); n, _, lat = outward(sp)
            az = math.radians(p["face_azimuth_deg"]); bar = (math.cos(az), -math.sin(az)); hb = 0.16 * u
            vp.plot([sp[0] - bar[0] * hb, sp[0] + bar[0] * hb], [sp[1] - bar[1] * hb, sp[1] + bar[1] * hb],
                    color="black", lw=2.6, zorder=8)
            vp.plot(*sp, "o", ms=6, color="black", zorder=9)
            vp.text(sp[0] - n[0] * 0.3 * u, sp[1] - n[1] * 0.3 * u, o["sign_code"], fontsize=8, ha="center", va="center",
                    zorder=9, bbox=dict(boxstyle="square,pad=0.15", fc="white", ec="none"))
            dc = (sp[0] + n[0] * CALLOUT_OFFSET_IN * u, sp[1] + n[1] * CALLOUT_OFFSET_IN * u)
            r1, r2 = DIAMOND_R_IN * u, (DIAMOND_R_IN - 0.05) * u
            dia = lambda rr: [(dc[0], dc[1] + rr), (dc[0] + rr, dc[1]), (dc[0], dc[1] - rr), (dc[0] - rr, dc[1])]
            vp.add_patch(Polygon(dia(r1), closed=True, fc=ORANGE, ec=ORANGE, lw=1, zorder=10))
            vp.add_patch(Polygon(dia(r2), closed=True, fc=ORANGE, ec="black", lw=2.2, zorder=11))
            vp.text(dc[0], dc[1], o["legend"].replace(" ", "\n"), fontsize=21, fontweight="bold", ha="center",
                    va="center", linespacing=0.95, zorder=12)
            vp.text(dc[0], dc[1] - r1 - 0.25 * u, o["sign_code"], fontsize=20, fontweight="bold", ha="center", va="center",
                    zorder=12, bbox=dict(boxstyle="square,pad=0.15", fc="white", ec="none"))
            vp.plot([sp[0], dc[0] - n[0] * r1], [sp[1], dc[1] - n[1] * r1], color="black", lw=0.7, zorder=7)
            side = 1 if lat >= 0 else -1; off = abs(lat) + 0.45 * u
            a0, _ = offset_point(cl, p["work_station_m"], side * off); a1, _ = offset_point(cl, p["station_m"], side * off)
            for q, src in ((a0, wp), (a1, sp)):
                vp.plot([src[0], q[0]], [src[1], q[1]], color="black", lw=0.6, zorder=6)
            vp.annotate("", a1, a0, arrowprops=dict(arrowstyle="<|-|>", color="black", lw=0.8, mutation_scale=12), zorder=6)
            vp.text((a0[0] + a1[0]) / 2, (a0[1] + a1[1]) / 2, f"{p['longitudinal_distance_ft']:g}'", fontsize=11,
                    ha="center", va="center", zorder=9, bbox=dict(boxstyle="square,pad=0.2", fc="white", ec="none"))
            if o.get("sme"):  # SME-changed object (revision plans only)
                from tcp_planner.sheets.sme_exception_text import object_tag, PURPLE
                vp.text(sp[0] + n[0] * 0.3 * u, sp[1] + n[1] * 0.3 * u, object_tag(o), fontsize=9, color="white",
                        ha="center", va="center", zorder=13, bbox=dict(boxstyle="square,pad=0.2", fc=PURPLE, ec="black"))

        for o in objs:  # SME-proposed objects (SME revision plans only): purple marker and label, never a TA-1 symbol
            if o["object_type"] != "SME_PROPOSED_OBJECT": continue
            from tcp_planner.sheets.sme_exception_text import PURPLE
            sp = local(o["placement"])
            if o["placement"].get("zone"):
                vp.plot(*zip(*[local(q) for q in o["placement"]["zone"]]), color=PURPLE, lw=4, alpha=0.8, zorder=8)
            vp.plot(*sp, "s", ms=9, color=PURPLE, zorder=9)
            vp.text(sp[0], sp[1] - 0.3 * u, f"{o['object_id']} SME PROPOSED {o.get('sme_category')}\n(UNSUPPORTED - EXCEPTION)",
                    fontsize=9, color="white", ha="center", va="top", zorder=13,
                    bbox=dict(boxstyle="square,pad=0.2", fc=PURPLE, ec="black"))

        # ---- overlay in page points: notes box back on top, border, title-block values ----
        ov = fig.add_axes([0, 0, 1, 1], facecolor="none"); ov.axis("off")
        # draft marking in the (empty) top margin of the template, not across the aerial
        ov.text((vx0 + vx1) / 2, vy0 / 2, f"{WATERMARK}   -   PLAN {plan['plan_id']}", fontsize=16, color="red",
                fontweight="bold", ha="center", va="center", zorder=4)
        ov.imshow(frame[int(nb[1] * k):int(nb[3] * k), int(nb[0] * k):int(nb[2] * k)],
                  extent=(nb[0], nb[2], nb[3], nb[1]), interpolation="lanczos", zorder=2)
        ov.add_patch(Rectangle((vx0, vy0), vx1 - vx0, vy1 - vy0, fill=False, ec="black", lw=1.2, zorder=3))
        ov.set_xlim(0, Wpt); ov.set_ylim(Hpt, 0)

        def put(region, text, fs=8.5, dx=2):
            x0, y0, x1, y1 = R[region]
            ov.text(x0 + dx, (y0 + y1) / 2, text, fontsize=fs, ha="left", va="center", zorder=4)

        rp = plan["rule_pack"]; ss = plan["site_summary"]; date = (plan.get("generated_at") or "")[:10]
        mmddyy = f"{date[5:7]}/{date[8:10]}/{date[2:4]}" if len(date) == 10 else "--"
        px0, py0, px1, py1 = R["phase_label"]
        ov.text((px0 + px1) / 2, (py0 + py1) / 2 + 3, "TA-1 DRAFT", fontsize=30, ha="center", va="center", zorder=4)
        x0, y0, x1, y1 = R["title_lines"]; xm = (x0 + x1) / 2; wref = work["placement"]
        ov.text(xm, y0 + 14, "TRAFFIC CONTROL PLAN - TA-1 (AUTOMATED DRAFT)", fontsize=10, ha="center", va="center", zorder=4)
        ov.text(xm, y0 + 30, (ss.get("road_name") or "UNNAMED ROAD").upper(), fontsize=9.5, ha="center", va="center", zorder=4)
        ov.text(xm, y0 + 43, f"WORK REF {wref['latitude']:.6f}, {wref['longitude']:.6f}", fontsize=8.5, ha="center",
                va="center", zorder=4)
        put("field_surveyed_by", "AERIAL ONLY"); put("field_print_no", "1   OF   1", dx=10)
        put("field_drawn_by", "TCP-POC (AUTO)"); put("field_scale", f'1"= {S}\'', dx=8)
        put("field_date", mmddyy); put("field_ewo", "--", dx=8)
        x0, y0, x1, y1 = R["project_notes"]
        notes = [f"-  {WATERMARK}.  PLAN {plan['plan_id']}  (HASH {plan['plan_hash'][:16]}...)",
                 f"-  RULE PACK {rp['id']} V{rp['version']}; TA-1 WORK BEYOND THE SHOULDER; ROAD TYPE {ss.get('road_type')}.",
                 "-  W20-1 ADVANCE WARNING SIGN PER MUTCD TABLE 6B-1 DIMENSION A, EACH APPROACH.  SYMBOLS NOT TO SCALE.",
                 f"-  IMAGERY: {imeta.get('attribution') or imeta['provider']}.  ROAD DATA (C) OPENSTREETMAP CONTRIBUTORS.",
                 "-  FIELD-VERIFY SIGN LOCATIONS; KEEP SIGNS OFF THE TRAVELED WAY AND SHOULDER; ALLOW DRIVEWAY ACCESS."]
        for i, t in enumerate(notes):
            ov.text(x0 + 7, y0 + 6 + i * 11, t, fontsize=7.6, ha="left", va="center", zorder=4)
        from tcp_planner.sheets.sme_exception_text import exception_lines, PURPLE  # SME revision plans only; empty for normal plans
        exl = exception_lines(plan)
        if exl:
            ov.text(vx0 + 10, vy0 + 14, "\n".join(exl), fontsize=8, color="white", ha="left", va="top", zorder=5,
                    bbox=dict(boxstyle="square,pad=0.4", fc=PURPLE, ec="black", lw=0.8))
        x0, y0, x1, y1 = R["scale_cell"]; bx = x0 + 105; by = y0 + 42
        ov.text(bx + 144, y0 + 18, f'1"=  {S}  FEET', fontsize=11, ha="center", va="center", color="#555", zorder=4)
        for i in range(4):
            ov.add_patch(Rectangle((bx + i * 72, by - (4 if i % 2 == 0 else 0)), 72, 4,
                                   fc="black" if i % 2 == 0 else "white", ec="black", lw=0.8, zorder=4))
        for i in range(5):
            ov.text(bx + i * 72, by + 12, f"{i * S}", fontsize=8.5, ha="center", va="center", color="#555", zorder=4)
        rx0, ry0 = R["revision_rows"][0], R["revision_rows"][1]
        ov.text(rx0 + 14, ry0 + 8, "0", fontsize=8, ha="center", va="center", zorder=4)
        ov.text(rx0 + 40, ry0 + 8, "AUTOMATED DRAFT (NOT FOR FIELD USE)", fontsize=6.5, ha="left", va="center", zorder=4)
        ov.text(rx0 + 255, ry0 + 8, mmddyy, fontsize=7, ha="center", va="center", zorder=4)
        fx0, fy0, fx1, fy1 = R["file_path_strip"]
        ov.text((fx0 + fx1) / 2, fy1 - 10, f"{plan['plan_id']}   PLAN SHA-256 {plan['plan_hash']}   {date}", rotation=90,
                fontsize=6.5, ha="center", va="bottom", zorder=4)

        fig.savefig(pdf_path, dpi=150, metadata={"CreationDate": None})
        fig.savefig(png_path, dpi=80)
        plt.close(fig)
        return {"scale_ft_per_in": S}
