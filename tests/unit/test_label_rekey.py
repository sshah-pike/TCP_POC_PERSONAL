"""S3: the one ground-truth label was re-keyed by hand to the lineage key of its zone (D-82); the old file was moved to
backup/orphans/2026-10-29/ with a manifest entry. See docs/reports/S3_label_rekey.md."""
import hashlib, json, os, re, subprocess

from tcp_planner.config.settings import PROJECT_ROOT
from tcp_planner.intake import kml_reader
from tcp_planner.intake.lineage import lineage_key, zone_geometry_hash
from tcp_planner.orchestration import projects as P

DEMO_KML = os.path.join(PROJECT_ROOT, "tests", "fixtures", "kml",
                        "demo) RI-91 Alton Bradford Rd - single point (demo, not a real pole).kml")
LABEL_POINT = [41.4151206, -71.741541]            # work_reference of the label (as written in the file)
OLD_KEY, NEW_KEY = "771bbc3d0913044a", "04bf2dc90e9c3cac"
BACKUP = os.path.join(PROJECT_ROOT, "backup", "orphans", "2026-10-29")


def test_the_demo_kml_point_is_the_label_point_and_gives_the_new_key():
    [loc] = kml_reader.parse_all(DEMO_KML, duplicate_distance_m=1.0)
    assert loc.usable and loc.geometry == {"type": "POINT", "coords": LABEL_POINT}
    pid, zh = P.project_id_for([loc]), zone_geometry_hash([loc])
    assert pid == "PRJ-f46419bbc77c92b5" and P.zone_id_for(zh) == "ZONE-c0690d642bc7"
    assert lineage_key(pid, zh) == NEW_KEY != OLD_KEY


def test_the_old_label_file_is_in_the_backup_and_listed_in_the_manifest():
    with open(os.path.join(BACKUP, "MANIFEST.json"), encoding="utf-8") as f: manifest = json.load(f)
    [e] = manifest["entries"]
    assert manifest["slice"] == "S3" and manifest["date"] == "2026-10-29"
    assert e["original_path"] == f"var/labels/{OLD_KEY}.json"
    assert e["new_path"] == f"backup/orphans/2026-10-29/var/labels/{OLD_KEY}.json"
    assert e["reason"] and e["evidence"] and e["moved_in_commit"] and "commit_before_move" in e
    assert e["restore_command"] == (f'python scripts/restore_backup.py backup/orphans/2026-10-29 --apply --only "{e["original_path"]}"')
    path = os.path.join(PROJECT_ROOT, *e["new_path"].split("/"))
    data = open(path, "rb").read()
    assert hashlib.sha256(data).hexdigest() == e["sha256"] and len(data) == e["size"]
    blob = subprocess.run(["git", "hash-object", path], cwd=PROJECT_ROOT, capture_output=True, text=True, check=True).stdout.strip()
    assert blob == e["git_blob"]                                              # what scripts/restore_backup.py verifies
    old = json.loads(data.decode("utf-8"))
    assert old["site_id"] == OLD_KEY and old["work_reference"] == {"latitude": LABEL_POINT[0], "longitude": LABEL_POINT[1]}
    assert old["status"] == "DRAFT" and len(old["history"]) == 1               # the pre-S3 file is untouched


def test_the_before_and_after_record_names_both_keys():
    with open(os.path.join(PROJECT_ROOT, "docs", "reports", "S3_label_rekey.md"), encoding="utf-8") as f: text = f.read()
    assert OLD_KEY in text and NEW_KEY in text and re.search(r'"action": "rekey"', text) and "## Before" in text and "## After" in text
