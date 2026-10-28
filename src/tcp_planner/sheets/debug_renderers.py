"""Renderers consume a validated PlanModel only. They make no regulatory decisions."""
import hashlib, json, os
from tcp_planner.contracts import DwtRenderError, FT
from tcp_planner.geometry.local_frame import enu, cum, at

WATERMARK = "AUTOMATED DRAFT - NOT APPROVED FOR FIELD USE"


class DebugRenderer:
    """Matplotlib PNG/PDF for POC debugging."""

    def render(self, plan, image, png_path, pdf_path):
        import matplotlib; matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        meta = plan["imagery"]; mpp = meta["metres_per_pixel"]
        W, H = meta["width_pixels"], meta["height_pixels"]
        c_lat, c_lon = meta["center"]["latitude"], meta["center"]["longitude"]
        to_local = lambda p: enu(p["latitude"], p["longitude"], c_lat, c_lon)
        px = lambda xy: (W / 2 + xy[0] / mpp, H / 2 - xy[1] / mpp)

        geo = plan["site_geometry"]
        cl = [to_local(p) for p in geo["centerline"]]
        fig = plt.figure(figsize=(16, 9), dpi=110); gs = fig.add_gridspec(1, 2, width_ratios=[3.2, 1.35], wspace=0.02)
        ax = fig.add_subplot(gs[0]); ax.imshow(image)
        ax.plot(*zip(*[px(p) for p in cl]), color="cyan", lw=1, ls="--", label="road centerline (OSM)")
        for k in ("left", "right"):
            if geo["road_edges"].get(k):
                ax.plot(*zip(*[px(to_local(p)) for p in geo["road_edges"][k]]), color="white", lw=0.8, alpha=0.8,
                        label="derived traveled-way edge" if k == "left" else None)

        pts = []
        for o in plan["objects"]:
            p = o["placement"]; xy = px(to_local(p)); pts.append(xy)
            if o["object_type"] == "SME_PROPOSED_OBJECT":  # SME revision plans only
                from tcp_planner.sheets.sme_exception_text import PURPLE
                if p.get("zone"): ax.plot(*zip(*[px(to_local(q)) for q in p["zone"]]), color=PURPLE, lw=4, alpha=0.8)
                ax.plot(*xy, "s", ms=10, mfc=PURPLE, mec="white", zorder=7)
                ax.annotate(f"{o['object_id']} SME {o.get('sme_category')} (UNSUPPORTED)", xy, xytext=(6, -14),
                            textcoords="offset points", fontsize=8, color="white",
                            bbox=dict(boxstyle="round,pad=0.12", fc=PURPLE, alpha=0.85, lw=0))
                continue
            if o["object_type"] == "WORK_LOCATION":
                if p.get("path"):
                    ax.plot(*zip(*[px(to_local(q)) for q in p["path"]]), color="orange", lw=3, label="work path")
                ax.plot(*xy, "*", ms=16, mfc="orange", mec="black", zorder=7, label="work location")
                continue
            ax.plot(*xy, "D", ms=11, mfc="gold", mec="black", zorder=6)
            import math
            az = math.radians(p["face_azimuth_deg"]); L = 12
            ax.annotate("", (xy[0] + L * math.sin(az), xy[1] - L * math.cos(az)), xy,
                        arrowprops=dict(arrowstyle="-|>", color="gold", lw=1.4))
            ax.annotate(f"{o['object_id']} {o['sign_code']}", xy, xytext=(6, 8), textcoords="offset points", fontsize=9,
                        fontweight="bold", color="white", bbox=dict(boxstyle="round,pad=0.12", fc="black", alpha=0.65, lw=0))
            # dimension along the centerline, work station -> sign station
            s_a, s_b = sorted((p["work_station_m"], p["station_m"]))
            seg = [px(at(cl, s_a + (s_b - s_a) * i / 30)[0]) for i in range(31)]
            ax.plot(*zip(*seg), color="white", lw=1.6, alpha=0.9)
            mid = seg[15]
            ax.text(mid[0], mid[1] - 10, f"{p['longitudinal_distance_ft']:g} ft ({o['generated_by']['source_table']} A)",
                    color="white", fontsize=8, ha="center", bbox=dict(boxstyle="round,pad=0.15", fc="navy", alpha=0.8, lw=0))

        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]; m = 40 / mpp
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        hw = max((max(xs) - min(xs)) / 2 + m, (max(ys) - min(ys)) / 2 + m, 60 / mpp)
        ax.set_xlim(max(0, cx - hw * 1.2), min(W, cx + hw * 1.2)); ax.set_ylim(min(H, cy + hw * 0.7), max(0, cy - hw * 0.7))
        ax.set_aspect("equal"); ax.axis("off")
        x0, _ = ax.get_xlim(); y0 = ax.get_ylim()[0]; bar = 100 * FT / mpp
        ax.plot([x0 + 30, x0 + 30 + bar], [y0 - 30, y0 - 30], color="white", lw=4)
        ax.text(x0 + 30 + bar / 2, y0 - 45, "100 ft", color="white", ha="center", fontsize=9)
        x1 = ax.get_xlim()[1]; ytop = ax.get_ylim()[1]
        ax.annotate("N", (x1 - 40, ytop + 30), (x1 - 40, ytop + 110), color="white", fontsize=14, fontweight="bold",
                    ha="center", arrowprops=dict(arrowstyle="-|>", color="white", lw=2))
        ax.text(0.5, 0.5, WATERMARK, transform=ax.transAxes, rotation=22, fontsize=22, color="white", alpha=0.25,
                ha="center", va="center")
        ax.legend(loc="lower right", fontsize=8, facecolor="black", labelcolor="white", framealpha=0.6)

        ax2 = fig.add_subplot(gs[1]); ax2.axis("off")
        s = plan["site_summary"]; rp = plan["rule_pack"]
        sched = "\n".join(
            f" {o['object_id']:<3}{o['sign_code']:<7}{o['approach'][:3]:<4}{o['placement']['longitudinal_distance_ft']:>6g} ft"
            f"  face {o['placement']['face_azimuth_deg']:>5.1f}"
            for o in plan["objects"] if o["object_type"] == "SIGN") or " (none - documented option applied)"
        opts = "".join(f" * {a['rule_id']}\n" for a in plan["options_applied"]) or " none\n"
        txt = (f"{WATERMARK}\n{'-' * 44}\nPlan : {plan['plan_id']}  v{plan['version']}\n"
               f"Site : {plan['site_model']['id']}\nRoad : {s['road_name'] or '(unnamed)'}\n"
               f"Type : {s['road_type']}  lanes {s['lane_count']}  {s['traffic_direction']}\n"
               f"Work : {s['work_location']}, {s['work_side']} of centerline\n"
               f"TA   : {plan['template']['id']} ({plan['template'].get('title')})\n"
               f"Pack : {rp['id']}\n       v{rp['version']}  {rp['hash'][:16]}...\n"
               f"Scale: 1 px = {mpp / FT:.2f} ft  ({meta['provider']})\n\n"
               f"SIGNS (distance upstream of work)\n{sched}\n\nOptions applied:\n{opts}\n"
               f"Validation: rule {plan['validation']['rule']}  geometry {plan['validation']['geometry']}\n"
               f"Not generated: taper, lane closure, channelizing\n devices, termination sign, flagger,\n"
               f" police, arrow panel, pedestrian items.\n\nPlan hash: {plan['plan_hash'][:24]}...")
        ax2.text(0.02, 0.98, txt, va="top", ha="left", family="monospace", fontsize=8.2, bbox=dict(fc="#f4f4f4", ec="black"))
        from tcp_planner.sheets.sme_exception_text import exception_lines, PURPLE  # SME revision plans only; empty for normal plans
        exl = exception_lines(plan)
        if exl:
            ax.text(0.01, 0.99, "\n".join(exl), transform=ax.transAxes, va="top", ha="left", fontsize=7.5, color="white",
                    bbox=dict(boxstyle="round,pad=0.3", fc=PURPLE, alpha=0.85, lw=0), zorder=20)
        fig.savefig(png_path, bbox_inches="tight"); fig.savefig(pdf_path, bbox_inches="tight", metadata={"CreationDate": None})
        plt.close(fig)
