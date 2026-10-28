"""DWT/CAD renderer: places the generated aerial image (and, in PLAN mode, the approved plan blocks)
inside the approved DWT template.

Toolchain: ezdxf edits the drawing; the free ODA File Converter converts DWT/DWG <-> DXF.
A .dxf template is also accepted (no converter needed). Nothing is faked: every prerequisite is
verified first and any missing asset raises a structured DwtRenderError (fail closed).

Modes
  PLAN        aerial + centerline/edges + work location + approved sign blocks + title fields.
              Requires every block referenced by the plan to exist (rule pack 19: render_block_if_missing_asset).
  AERIAL_BASE aerial + centerline/edges + work location marker + title fields, no TTC devices.
              Produces the georeferenced CAD base used by the manual drafting workflow.

Drawing frame: local ENU in drawing units, origin = work reference (image centre), +Y = north.
"""
import hashlib, json, math, os, shutil, tempfile
from tcp_planner.contracts import DwtRenderError, FT, r
from tcp_planner.geometry.local_frame import enu

UNIT_CODES = {"FEET": 2, "US_SURVEY_FEET": 21, "METERS": 6}
UNIT_METRES = {"FEET": FT, "US_SURVEY_FEET": 1200 / 3937, "METERS": 1.0}
RASTER_UNITS = {"FEET": "ft", "US_SURVEY_FEET": "ft", "METERS": "m"}
MODES = ("PLAN", "AERIAL_BASE")
DRAFT_MARKING = "AUTOMATED DRAFT - NOT APPROVED FOR FIELD USE"


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""): h.update(chunk)
    return h.hexdigest()


def _dwg_header_version(path):
    with open(path, "rb") as f: head = f.read(6)
    return head.decode("ascii", "replace") if head.startswith(b"AC") else None


class DwtRenderer:
    """Consumes PlanModel + georeferenced aerial image + DWT config + approved block catalog."""

    def __init__(self, config_path, rule_pack, mode="PLAN"):
        if mode not in MODES: raise DwtRenderError("DWT_MODE_INVALID", f"mode must be one of {MODES}")
        self.config_path = config_path; self.rule_pack = rule_pack; self.mode = mode

    # ---------------- configuration / toolchain ----------------
    def _load_config(self):
        if not self.config_path or not os.path.isfile(self.config_path):
            raise DwtRenderError("DWT_CONFIG_MISSING", "DWT configuration file not found")
        with open(self.config_path, encoding="utf-8") as f: cfg = json.load(f)
        if cfg.get("regulatory_status") != "NON_MUTCD_RENDERER_CONFIGURATION":
            raise DwtRenderError("DWT_CONFIG_INVALID", "DWT config must be marked NON_MUTCD_RENDERER_CONFIGURATION")
        self.base = os.path.dirname(os.path.abspath(self.config_path))
        return cfg

    def _path(self, rel):
        return rel if not rel or os.path.isabs(rel) else os.path.normpath(os.path.join(self.base, rel))

    def _converter(self, cfg):
        import ezdxf
        from ezdxf.addons import odafc
        exe = os.environ.get("TCP_ODA_FILE_CONVERTER") or cfg.get("oda_file_converter")
        if exe: ezdxf.options.set("odafc-addon", "win_exec_path", exe)
        return odafc if odafc.is_installed() else None

    def _open_template(self, cfg, tpl, errors):
        import ezdxf
        ext = os.path.splitext(tpl)[1].lower()
        if ext == ".dxf":
            return ezdxf.readfile(tpl)
        conv = self._converter(cfg)
        if conv is None:
            errors.append({"code": "DWT_TOOLCHAIN_MISSING",
                           "detail": "ODA File Converter not found; install it or set TCP_ODA_FILE_CONVERTER"})
            return None
        with tempfile.TemporaryDirectory(prefix="tcp_dwt_") as tmp:
            src = os.path.join(tmp, "template.dwg")  # DWT is DWG-format; converter filters on .dwg
            shutil.copyfile(tpl, src)
            try:
                return conv.readfile(src)
            except Exception as e:
                errors.append({"code": "DWT_TEMPLATE_UNREADABLE", "detail": type(e).__name__}); return None

    # ---------------- verification ----------------
    def verify(self, plan, aerial_path, georef):
        """Verify DWT version/hash, layers, blocks, units and aerial georeferencing. Returns (doc, cfg, info)."""
        cfg = self._load_config(); errors = []
        tpl = self._path(cfg.get("dwt_path"))
        info = {"mode": self.mode, "dwt_version": cfg.get("dwt_version"), "dwt_sha256": cfg.get("dwt_sha256"),
                "units": cfg.get("drawing_units")}
        if not tpl or not os.path.isfile(tpl):
            raise DwtRenderError("DWT_TEMPLATE_MISSING", "DWT template not found", {"errors": [{"code": "DWT_TEMPLATE_MISSING"}]})
        if not cfg.get("dwt_sha256") or _sha256_file(tpl) != cfg["dwt_sha256"]:
            errors.append({"code": "DWT_HASH_MISMATCH"})
        header = _dwg_header_version(tpl)
        if not cfg.get("dwt_version"): errors.append({"code": "DWT_VERSION_MISSING"})
        elif header and cfg.get("dwt_format") and header != cfg["dwt_format"]:
            errors.append({"code": "DWT_VERSION_MISMATCH", "expected": cfg["dwt_format"], "actual": header})
        units = cfg.get("drawing_units")
        if units not in UNIT_CODES: errors.append({"code": "DWT_UNITS_INVALID", "value": units})
        for k in ("bounding_box", "metres_per_pixel", "width_pixels", "height_pixels", "center", "orientation"):
            if not georef.get(k): errors.append({"code": "AERIAL_GEOREFERENCE_INCOMPLETE", "field": k})
        if georef.get("orientation") not in (None, "NORTH_UP"):
            errors.append({"code": "AERIAL_GEOREFERENCE_INCOMPLETE", "field": "orientation"})
        if not aerial_path or not os.path.isfile(aerial_path): errors.append({"code": "AERIAL_IMAGE_MISSING"})

        doc = None
        if not errors:
            doc = self._open_template(cfg, tpl, errors)
        if doc is not None:
            if units in UNIT_CODES and doc.header.get("$INSUNITS", 0) != UNIT_CODES[units]:
                errors.append({"code": "DWT_UNITS_MISMATCH", "expected": units, "template_insunits": doc.header.get("$INSUNITS")})
            have_layers = {l.dxf.name.upper() for l in doc.layers}
            needed_layers = self._needed_layers(plan)
            lmap = cfg.get("layer_map", {})
            missing = sorted(l for l in needed_layers if lmap.get(l, l).upper() not in have_layers)
            if missing:
                errors.append({"code": "DWT_LAYER_MISSING", "layers": missing,
                               "template_layers": sorted(have_layers)[:200]})
            if self.mode == "PLAN":
                missing_blocks = [b for b in sorted({o["dwt_block"] for o in plan["objects"] if o.get("dwt_block")})
                                  if not self._block_available(doc, cfg, b)]
                if missing_blocks:
                    errors.append({"code": "DWT_BLOCK_MISSING", "blocks": missing_blocks,
                                   "template_blocks": sorted(b.name for b in doc.blocks if not b.name.startswith("*"))[:200]})
        if errors:
            raise DwtRenderError(errors[0]["code"], "DWT rendering prerequisites failed", {"errors": errors})
        info["template_header_version"] = header
        return doc, cfg, info

    def _needed_layers(self, plan):
        layers = self.rule_pack.section("19_dwt_block_mapping")["layers"]
        keys = ["aerial", "road_centerline", "road_edges", "work_area", "notes"]
        if self.mode == "PLAN": keys += ["signs", "dimensions"]
        return sorted({layers[k] for k in keys})

    def _block_available(self, doc, cfg, logical):
        entry = cfg.get("block_map", {}).get(logical) or {}
        name = entry.get("template_block")
        if name and name in doc.blocks: return True
        f = self._path(entry.get("file"))
        return bool(f and os.path.isfile(f) and entry.get("sha256") and _sha256_file(f) == entry["sha256"])

    def _resolve_block(self, doc, cfg, logical):
        entry = cfg["block_map"][logical]
        if entry.get("template_block") and entry["template_block"] in doc.blocks:
            return entry["template_block"]
        import ezdxf
        from ezdxf.addons import Importer
        f = self._path(entry["file"])
        src = ezdxf.readfile(f) if f.lower().endswith(".dxf") else self._converter(cfg).readfile(f)
        name = entry.get("block_name") or os.path.splitext(os.path.basename(f))[0]
        if name not in doc.blocks:
            blk = doc.blocks.new(name)
            imp = Importer(src, doc); imp.import_entities(src.modelspace(), blk); imp.finalize()
        return name

    # ---------------- rendering ----------------
    def render(self, plan, aerial_path, georef, out_dir, basename="plan"):
        doc, cfg, info = self.verify(plan, aerial_path, georef)
        units = cfg["drawing_units"]; u = UNIT_METRES[units]
        lmap = cfg.get("layer_map", {}); L = self.rule_pack.section("19_dwt_block_mapping")["layers"]
        layer = lambda k: lmap.get(L[k], L[k])
        c_lat, c_lon = georef["center"]["latitude"], georef["center"]["longitude"]
        to_dwg = lambda lat, lon: tuple(v / u for v in enu(lat, lon, c_lat, c_lon))
        msp = doc.modelspace()

        # aerial image, georeferenced: image centre = work reference = drawing origin
        img_name = cfg.get("image_filename", "aerial_image.jpg")
        img_dst = os.path.join(out_dir, img_name)
        if os.path.abspath(aerial_path) != os.path.abspath(img_dst): shutil.copyfile(aerial_path, img_dst)
        W, H, mpp = georef["width_pixels"], georef["height_pixels"], georef["metres_per_pixel"]
        doc.set_raster_variables(frame=0, quality=1, units=RASTER_UNITS[units])
        img_def = doc.add_image_def(filename=img_name, size_in_pixel=(W, H))
        size = (W * mpp / u, H * mpp / u)
        msp.add_image(img_def, insert=(-size[0] / 2, -size[1] / 2), size_in_units=size,
                      dxfattribs={"layer": layer("aerial")})

        geo = plan["site_geometry"]
        msp.add_lwpolyline([to_dwg(p["latitude"], p["longitude"]) for p in geo["centerline"]],
                           dxfattribs={"layer": layer("road_centerline")})
        for side in ("left", "right"):
            if geo["road_edges"].get(side):
                msp.add_lwpolyline([to_dwg(p["latitude"], p["longitude"]) for p in geo["road_edges"][side]],
                                   dxfattribs={"layer": layer("road_edges")})
        corr = float(cfg.get("rotation_correction_deg", 0.0))
        text_h = float(cfg.get("note_text_height", 4.0))
        for o in plan["objects"]:
            p = o["placement"]; xy = to_dwg(p["latitude"], p["longitude"])
            if o["object_type"] == "WORK_LOCATION":
                if self.mode == "PLAN":
                    msp.add_blockref(self._resolve_block(doc, cfg, o["dwt_block"]), xy, dxfattribs={"layer": layer("work_area")})
                else:
                    msp.add_circle(xy, radius=1.0 / u, dxfattribs={"layer": layer("work_area")})  # 1 m marker
                if p.get("path"):
                    msp.add_lwpolyline([to_dwg(q["latitude"], q["longitude"]) for q in p["path"]],
                                       dxfattribs={"layer": layer("work_area")})
            elif self.mode == "PLAN" and o["object_type"] == "SIGN":
                rot = (90.0 - p["face_azimuth_deg"] + corr) % 360.0  # CAD angle: CCW from +X
                msp.add_blockref(self._resolve_block(doc, cfg, o["dwt_block"]), xy,
                                 dxfattribs={"layer": layer("signs"), "rotation": rot})
                msp.add_text(f"{o['object_id']} {o['sign_code']} {p['longitudinal_distance_ft']:g} FT",
                             height=text_h, dxfattribs={"layer": layer("dimensions"),
                                                        "insert": (xy[0] + text_h, xy[1] + text_h)})
            elif o["object_type"] == "SME_PROPOSED_OBJECT":  # SME revision plans only: marker + label, no approved block
                msp.add_circle(xy, radius=1.0 / u, dxfattribs={"layer": layer("signs")})
                msp.add_text(f"{o['object_id']} SME PROPOSED {o.get('sme_category')} - NOT AN APPROVED TA-1 OBJECT",
                             height=text_h, dxfattribs={"layer": layer("dimensions"),
                                                        "insert": (xy[0] + text_h, xy[1] + text_h)})

        title = self._title_fields(plan, cfg, info)
        required = self.rule_pack.section("19_dwt_block_mapping")["required_title_fields"]
        missing = [k for k in required if title.get(k) in (None, "")]
        if missing: raise DwtRenderError("DWT_TITLE_FIELD_MISSING", "required title fields missing", {"fields": missing})
        for k, v in title.items(): doc.header.custom_vars.append(k, str(v))
        self._fill_title_attributes(doc, cfg.get("title_attribute_map", {}), title)
        notes = [DRAFT_MARKING, f"MODE: {self.mode}" + (" - AERIAL BASE ONLY, NO TTC DEVICES" if self.mode == "AERIAL_BASE" else ""),
                 f"PLAN {title['plan_id']} V{title['plan_version']}  RULE PACK {title['rule_pack_id']} V{title['rule_pack_version']}",
                 f"COORDINATES: LOCAL ENU {units}, ORIGIN = WORK REFERENCE, +Y = NORTH"]
        y = -size[1] / 2 - text_h * 2
        for line in notes:
            msp.add_text(line, height=text_h, dxfattribs={"layer": layer("notes"), "insert": (-size[0] / 2, y)}); y -= text_h * 1.6

        dxf_path = os.path.join(out_dir, f"{basename}.dxf"); doc.saveas(dxf_path)
        outputs = [os.path.basename(dxf_path), img_name]
        conv = self._converter(cfg)
        if conv is not None:
            conv.export_dwg(doc, os.path.join(out_dir, f"{basename}.dwg"), version=cfg.get("output_dwg_version", "R2018"), replace=True)
            outputs.append(f"{basename}.dwg")
        else:
            info["dwg_export"] = "SKIPPED_NO_ODA_FILE_CONVERTER (DXF written)"
        info.update(status="RENDERED", outputs=outputs, title_fields=title)
        return info

    def _title_fields(self, plan, cfg, info):
        rp = plan["rule_pack"]
        return {"plan_id": plan["plan_id"], "plan_version": plan["version"], "rule_pack_id": rp["id"],
                "rule_pack_version": rp["version"], "rule_pack_hash": rp["hash"], "TA_id": plan["template"]["id"],
                "site_model_id": plan["site_model"]["id"], "DWT_version": cfg["dwt_version"],
                "generated_timestamp": plan.get("generated_at")}

    @staticmethod
    def _fill_title_attributes(doc, tag_map, values):
        if not tag_map: return
        for layout in doc.layouts:
            for ins in layout.query("INSERT"):
                for att in ins.attribs:
                    for field, tag in tag_map.items():
                        if att.dxf.tag.upper() == str(tag).upper() and field in values:
                            att.dxf.text = str(values[field])
