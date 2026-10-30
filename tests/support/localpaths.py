"""Find local machine paths inside a rendered file (DXF header or DWG bytes): S3 one-time check that a renderer output does
not embed the folder it was written to, a temp folder or a user name."""
import getpass, os, re, tempfile

DRIVE_PATH = re.compile(rb"[A-Za-z]:[\\/]")                       # C:\... or C:/...
UNIX_HOME = re.compile(rb"/(?:Users|home)/[^/\s\"']+")


def dxf_header(data):
    """The HEADER section of an ASCII DXF (from 'SECTION' '2' 'HEADER' to its ENDSEC); the whole text when it has none."""
    m = re.search(rb"SECTION\s+2\s+HEADER(.*?)ENDSEC", data, re.S)
    return m.group(0) if m else data


def local_path_hits(data, extra=(), generic=True):
    """Strings of local-path kind found in data: this machine's temp folder, home folder and user name, the extra folders
    given (for example the output folder) and, with generic=True, any drive-letter path or Unix home path. Use generic=False
    for binary files (DWG): short patterns would match random bytes. Empty list = clean."""
    needles = {str(p) for p in extra} | {tempfile.gettempdir(), os.path.expanduser("~")}
    try: needles.add(getpass.getuser())
    except Exception: pass
    hits = []
    for n in sorted(x for x in needles if x and len(x) > 3):
        for variant in {n, n.replace("\\", "/"), n.replace("/", "\\")}:
            if variant.encode("utf-8", "ignore") in data: hits.append(variant)
    if generic:
        hits += [m.group(0).decode("utf-8", "ignore") for m in DRIVE_PATH.finditer(data)]
        hits += [m.group(0).decode("utf-8", "ignore") for m in UNIX_HOME.finditer(data)]
    return sorted(set(hits))
