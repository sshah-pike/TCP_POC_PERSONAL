"""SME lineage key: composite of project and zone geometry hash (D-82).

Clean break from the POC key `geometry_hash(pg)[:16]` (no migration of POC-era runs). Since S3 the assistant, the
ground-truth labels and `site_id_for` use this key, read from the project link in a run's request record; a run
outside a project has no lineage key (the assistant answers NO_PROJECT_LINEAGE).
"""
from tcp_planner.contracts import canonical_json, sha256_hex


def zone_geometry_hash(locations):
    """Hash of a zone's geometry: the sorted geometry hashes of its locations, so member order never matters."""
    hashes = sorted(l.geometry_hash for l in locations)
    if not hashes: raise ValueError("a zone needs at least one location")
    return "sha256:" + sha256_hex(canonical_json(hashes))


def lineage_key(project_id, zone_geometry_hash):
    if not project_id or not zone_geometry_hash: raise ValueError("project_id and zone_geometry_hash are required")
    return sha256_hex(canonical_json({"project_id": project_id, "zone_geometry_hash": zone_geometry_hash}))[:16]
