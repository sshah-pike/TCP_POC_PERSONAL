"""Device catalog (S5): the one loader of assets/symbols/device_catalog.json and the symbol files it points to.

The catalog says which devices exist, what they are called, how a drafting code maps to them and which symbol file draws
them. It holds no regulatory number: sign sizes are sourced rows in the rule pack (read through RulePackStore). "Used by
TA" is derived from the pack's ta_device_use rows, never stored here.

Persistence (CLAUDE.md, Storage): the catalog carries `schema_version`; every asset is an artifact-style reference
{uri, sha256, size, media_type} plus a status. `uri` is a key relative to the assets folder ("symbols/svg/W20-1.svg"),
never a raw path; only this module turns it into a path, through config/settings.py.

Hashing: `catalog_hash` is the SHA-256 of canonical JSON of schema_version and every entry (asset sha256 included), so
key order and line endings do not matter, and swapping one symbol changes that entry's asset sha256 and the hash only.
"""
import json, os, re
from enum import Enum
from pydantic import BaseModel, ConfigDict, field_validator, model_validator
from tcp_planner.config.settings import ASSETS_DIR, DEVICE_CATALOG_PATH
from tcp_planner.contracts import TcpError, canonical_json, sha256_hex

SCHEMA_VERSION = "1"
_URI_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*(/[A-Za-z0-9][A-Za-z0-9._+-]*)+$")
MEDIA_TYPES = {".svg": "image/svg+xml", ".png": "image/png"}


class DeviceCatalogError(TcpError): pass


class CodeStatus(str, Enum):
    MUTCD = "MUTCD"
    CLIENT_CODE = "CLIENT_CODE"
    STATE_CODE = "STATE_CODE"
    DEVICE = "DEVICE"


class SizeSource(str, Enum):
    PACK = "PACK"                                    # sourced rows in the rule pack (read through RulePackStore)
    TEXT_ONLY = "TEXT_ONLY"                          # non-sign device; size_text is informational, no validator reads it
    SOURCE_REVIEW_REQUIRED = "SOURCE_REVIEW_REQUIRED"  # no source exists; any plan placing it is REVIEW_REQUIRED
    NOT_IN_MVP_PACK = "NOT_IN_MVP_PACK"              # a MUTCD sign no in-scope TA uses; no size row yet


class AssetStatus(str, Enum):
    PLACEHOLDER_ASSET = "PLACEHOLDER_ASSET"
    CLIENT_ASSET = "CLIENT_ASSET"


class AliasStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Asset(_Frozen):
    uri: str
    sha256: str
    size: int
    media_type: str
    status: AssetStatus

    @field_validator("uri")
    @classmethod
    def _uri(cls, v):
        if not _URI_RE.match(v) or ".." in v.split("/"): raise ValueError(f"asset uri must be a relative key: {v!r}")
        return v

    @field_validator("sha256")
    @classmethod
    def _sha(cls, v):
        if not re.fullmatch(r"[0-9a-f]{64}", v): raise ValueError("sha256 must be 64 lowercase hex characters")
        return v

    @model_validator(mode="after")
    def _media(self):
        if MEDIA_TYPES.get(os.path.splitext(self.uri)[1].lower()) != self.media_type:
            raise ValueError(f"media_type {self.media_type} does not match {self.uri}")
        return self


class PrintedAs(_Frozen):
    """A code a client draft prints for this device. Comparison only: it never selects a device for placement."""
    code: str
    status: AliasStatus


class Entry(_Frozen):
    device_id: str
    mutcd_code: str | None
    printed_as: tuple[PrintedAs, ...]
    code_status: CodeStatus
    name: str
    category: str
    size_source: SizeSource
    size_text: str          # informational text for TEXT_ONLY devices, empty otherwise
    source: str             # where the device comes from, as text; the size's own source is its pack row
    asset: Asset
    notes: str
    observed_in_drafts: tuple[str, ...]

    @model_validator(mode="after")
    def _consistent(self):
        is_device = self.code_status == CodeStatus.DEVICE
        if (self.size_source == SizeSource.TEXT_ONLY) != is_device:
            raise ValueError(f"{self.device_id}: TEXT_ONLY is for DEVICE entries only")
        if not is_device and self.size_text: raise ValueError(f"{self.device_id}: size_text only for TEXT_ONLY devices")
        if self.code_status in (CodeStatus.CLIENT_CODE, CodeStatus.STATE_CODE):
            if self.size_source != SizeSource.SOURCE_REVIEW_REQUIRED or self.mutcd_code:
                raise ValueError(f"{self.device_id}: a client or state code has no MUTCD code and no sourced size")
        elif self.size_source == SizeSource.SOURCE_REVIEW_REQUIRED:
            raise ValueError(f"{self.device_id}: SOURCE_REVIEW_REQUIRED is for client and state codes only")
        if self.code_status == CodeStatus.MUTCD and not self.mutcd_code:
            raise ValueError(f"{self.device_id}: MUTCD entry without a code")
        return self


class Catalog(_Frozen):
    schema_version: str
    catalog_version: str
    status: str
    sources: tuple[str, ...]
    catalog_hash: str
    entries: tuple[Entry, ...]


class Resolution(_Frozen):
    entry: Entry
    via: str                              # DEVICE_ID, MUTCD_CODE or ALIAS
    alias_status: AliasStatus | None = None


def compute_catalog_hash(doc):
    """Hash over schema_version and the entries of a catalog document (the hash field itself is not covered)."""
    return sha256_hex(canonical_json({"schema_version": doc.get("schema_version"), "entries": doc.get("entries")}))


def asset_file_path(uri):
    """The file an asset uri names. The only place a uri becomes a path."""
    if not isinstance(uri, str) or not _URI_RE.match(uri) or ".." in uri.split("/"):
        raise DeviceCatalogError("ASSET_URI_INVALID", f"asset uri must be a relative key: {uri!r}", {"uri": uri})
    return os.path.join(ASSETS_DIR, *uri.split("/"))


def file_ref(uri):
    """sha256 and size of the file behind an asset uri."""
    p = asset_file_path(uri)
    if not os.path.isfile(p): raise DeviceCatalogError("ASSET_MISSING", f"asset file missing for {uri}", {"uri": uri})
    with open(p, "rb") as f: data = f.read()
    return {"sha256": sha256_hex(data), "size": len(data)}


def _need(cond, code, msg, **details):
    if not cond: raise DeviceCatalogError(code, msg, details)


def _read_doc(path):
    _need(os.path.isfile(path), "CATALOG_MISSING", "device catalog not found")
    try:
        with open(path, "rb") as f: return json.loads(f.read().decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise DeviceCatalogError("CATALOG_PARSE_FAILED", f"device catalog is not valid JSON: {e}")


class DeviceCatalog:
    """A loaded, hash-checked catalog. Lookups by device id or by a printed code."""

    def __init__(self, catalog):
        self.catalog = catalog
        self._by_id = {e.device_id: e for e in catalog.entries}
        _need(len(self._by_id) == len(catalog.entries), "CATALOG_DUPLICATE_ID", "device ids are not unique")
        self._codes = {}
        for e in catalog.entries:
            if e.mutcd_code: self._add_code(e.mutcd_code, e, "MUTCD_CODE", None)
        for e in catalog.entries:
            for p in e.printed_as: self._add_code(p.code, e, "ALIAS", p.status)

    def _add_code(self, code, entry, via, status):
        old = self._codes.get(code)
        _need(old is None or old[0] is entry, "CATALOG_CODE_CLASH", f"code {code} names two devices", printed_code=code)
        _need(code not in self._by_id or self._by_id[code] is entry, "CATALOG_CODE_CLASH",
              f"code {code} is also another device's id", printed_code=code)
        if old is None: self._codes[code] = (entry, via, status)

    @property
    def version(self): return self.catalog.catalog_version

    @property
    def hash(self): return self.catalog.catalog_hash

    @property
    def ref(self): return {"schema_version": self.catalog.schema_version, "version": self.version, "hash": self.hash}

    @property
    def entries(self): return list(self.catalog.entries)

    def has(self, device_id): return device_id in self._by_id

    def get(self, device_id):
        _need(device_id in self._by_id, "DEVICE_UNKNOWN", f"no device {device_id!r} in the catalog", device_id=device_id)
        return self._by_id[device_id]

    def resolve(self, code):
        """A device id, a MUTCD code or a printed alias to its entry. An unknown code raises DEVICE_UNKNOWN."""
        if code in self._by_id: return Resolution(entry=self._by_id[code], via="DEVICE_ID")
        hit = self._codes.get(code)
        _need(hit is not None, "DEVICE_UNKNOWN", f"no device or code {code!r} in the catalog", printed_code=code)
        return Resolution(entry=hit[0], via=hit[1], alias_status=hit[2])

    def asset_path(self, device_id):
        """Path of the device's symbol file, after checking it against the recorded sha256 and size."""
        a = self.get(device_id).asset
        ref = file_ref(a.uri)
        _need(ref == {"sha256": a.sha256, "size": a.size}, "ASSET_HASH_MISMATCH",
              f"asset for {device_id} differs from the catalog", device_id=device_id, uri=a.uri)
        return asset_file_path(a.uri)

    def verify_assets(self):
        """Every asset exists and matches its recorded sha256 and size. Returns the list of problems."""
        problems = []
        for e in self.catalog.entries:
            try:
                if file_ref(e.asset.uri) != {"sha256": e.asset.sha256, "size": e.asset.size}:
                    problems.append((e.device_id, "ASSET_HASH_MISMATCH"))
            except DeviceCatalogError as ex: problems.append((e.device_id, ex.code))
        return problems


def load_catalog(path=None, verify_assets=True):
    """Load and check the catalog. Fails closed: wrong schema_version, wrong catalog hash or a changed asset raises."""
    doc = _read_doc(path or DEVICE_CATALOG_PATH)
    _need(doc.get("schema_version") == SCHEMA_VERSION, "CATALOG_SCHEMA_VERSION",
          f"catalog schema_version {doc.get('schema_version')!r}, expected {SCHEMA_VERSION!r}")
    try: cat = Catalog.model_validate(doc)
    except ValueError as e: raise DeviceCatalogError("CATALOG_INVALID", f"device catalog invalid: {e}")
    _need(cat.catalog_hash == compute_catalog_hash(doc), "CATALOG_HASH_MISMATCH",
          "catalog_hash does not match the entries; run scripts/seal_device_catalog.py after a deliberate change")
    out = DeviceCatalog(cat)
    if verify_assets:
        problems = out.verify_assets()
        _need(not problems, "ASSET_INVALID", f"{len(problems)} asset problems", problems=problems)
    return out


def seal(path=None):
    """Record every asset's sha256 and size and the catalog hash in the catalog file. Returns the hash."""
    path = path or DEVICE_CATALOG_PATH
    doc = _read_doc(path)
    for e in doc["entries"]: e["asset"].update(file_ref(e["asset"]["uri"]))
    doc["catalog_hash"] = compute_catalog_hash(doc)
    with open(path, "w", encoding="utf-8") as f: json.dump(doc, f, indent=1, ensure_ascii=False)
    return doc["catalog_hash"]
