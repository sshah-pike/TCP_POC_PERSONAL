"""Restore files moved to backup/orphans/<date>/ back to their original paths, using the MANIFEST.json there.

    python scripts/restore_backup.py backup/orphans/2026-10-28                 # list what would be restored
    python scripts/restore_backup.py backup/orphans/2026-10-28 --apply         # git mv every entry back
    python scripts/restore_backup.py backup/orphans/2026-10-28 --apply --only tcp_ui/check_usgs.py

Each entry is checked against its recorded git blob id (line-ending independent) before it is moved.
Nothing is deleted; a restore is a git mv, so it can itself be undone with git.
"""
import argparse, json, os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def git_blob(path):
    return subprocess.run(["git", "hash-object", path], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("backup_dir", help="backup/orphans/<date> folder holding MANIFEST.json")
    ap.add_argument("--apply", action="store_true", help="perform the git mv (default: list only)")
    ap.add_argument("--only", action="append", default=[], help="restore only this original path (repeatable)")
    args = ap.parse_args(argv)
    with open(os.path.join(ROOT, args.backup_dir, "MANIFEST.json"), encoding="utf-8") as f: manifest = json.load(f)
    entries = [e for e in manifest["entries"] if not args.only or e["original_path"] in args.only]
    if args.only and len(entries) != len(set(args.only)):
        sys.exit("some --only paths are not in the manifest")
    failed = 0
    for e in entries:
        src, dst = os.path.join(ROOT, e["new_path"]), os.path.join(ROOT, e["original_path"])
        if not os.path.isfile(src):
            print(f"MISSING   {e['new_path']}"); failed += 1; continue
        if git_blob(src) != e["git_blob"]:
            print(f"CHANGED   {e['new_path']} (content differs from the manifest; not restored)"); failed += 1; continue
        if os.path.exists(dst):
            print(f"OCCUPIED  {e['original_path']} already exists; not restored"); failed += 1; continue
        print(f"{'RESTORE' if args.apply else 'WOULD'}   {e['new_path']} -> {e['original_path']}")
        if args.apply:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            subprocess.run(["git", "mv", e["new_path"], e["original_path"]], cwd=ROOT, check=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
