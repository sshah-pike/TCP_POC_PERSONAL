"""WorkLocation: one KML geometry, kept with a reason if it cannot be used (slice S1).

Coordinates are [latitude, longitude] pairs rounded to 7 decimals. POINT coords are one pair, LINESTRING a list of
pairs, POLYGON a list of rings (outer ring first, then holes). `geometry` is None for an unusable feature, which
keeps its record and its `reject_reasons`. Ids and hashes use geometry only: never names, order or the file hash.
"""
import dataclasses
from dataclasses import dataclass, field
from typing import Optional

from tcp_planner.contracts import canonical_json, sha256_hex

SCHEMA_VERSION = "1"

POINT, LINESTRING, POLYGON = "POINT", "LINESTRING", "POLYGON"
WORK, REFERENCE_ONLY = "WORK", "REFERENCE_ONLY"

INVALID_GEOMETRY = "INVALID_GEOMETRY"
EMPTY = "EMPTY"
UNSUPPORTED_TYPE = "UNSUPPORTED_TYPE"
DUPLICATE_OF = "DUPLICATE_OF:"  # prefix; the kept location id follows


@dataclass(frozen=True)
class Source:
    file: Optional[str]
    input_hash: str
    placemark_index: int
    geometry_index: int  # position among the geometries of one Placemark (MultiGeometry is flattened)
    name: Optional[str]  # display label only


@dataclass(frozen=True)
class WorkLocation:
    location_id: str
    ordinal: int  # document order, for display only; ids do not depend on it
    source: Source
    geometry: Optional[dict]  # {"type", "coords"} or None when unusable
    geometry_hash: str
    role: str = WORK
    display_label: Optional[str] = None
    reject_reasons: list = field(default_factory=list)
    schema_version: str = SCHEMA_VERSION

    @property
    def usable(self):
        return not self.reject_reasons

    def to_dict(self):
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d):
        if d.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"unsupported WorkLocation schema_version {d.get('schema_version')!r}")
        return cls(location_id=d["location_id"], ordinal=d["ordinal"], source=Source(**d["source"]),
                   geometry=d["geometry"], geometry_hash=d["geometry_hash"], role=d["role"],
                   display_label=d["display_label"], reject_reasons=list(d["reject_reasons"]),
                   schema_version=d["schema_version"])


def geometry_hash_of(geometry):
    return "sha256:" + sha256_hex(canonical_json({"type": geometry["type"], "coords": geometry["coords"]}))


def unusable_hash(tag, raw_text):
    """Hash for a feature with no usable geometry: its KML tag and whitespace-normalised coordinate text."""
    return "sha256:" + sha256_hex(canonical_json({"unusable": tag, "raw": " ".join((raw_text or "").split())}))


def base_location_id(geometry_hash):
    return "LOC-" + sha256_hex(geometry_hash)[:12]
