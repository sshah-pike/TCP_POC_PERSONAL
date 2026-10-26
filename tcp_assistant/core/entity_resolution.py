"""Deterministic TCP entity-reference resolution (no AI inference).

Order:
  1. EXACT                 case-sensitive exact match
  2. CASE_INSENSITIVE      Unicode NFKC + trim + uppercase, exact match on the normalized key
  3. ID_FORMAT_NORMALIZED  internal whitespace removed, ONLY for known device-ID shapes ("S 1" -> "S1", "pcms 2" -> "PCMS2")
  4. AMBIGUOUS / NOT_FOUND deterministic clarification by the caller - never semantic guessing
Arbitrary punctuation is never removed (avoids collisions such as "CONE-1" vs "CONE1"). If two canonical ids normalize
to the same key the reference is AMBIGUOUS and fails closed with the colliding ids as choices.
The canonical id stored in the plan is never changed; the original reference is returned for audit.
"""
import re
import unicodedata

DEVICE_ID_SPACED = re.compile(r"^([A-Z]{1,6})\s+([0-9]{1,4})$")   # known device-ID pattern with internal spaces only
EXACT, CASE_INSENSITIVE, ID_FORMAT, AMBIGUOUS, NOT_FOUND = (
    "EXACT", "CASE_INSENSITIVE", "ID_FORMAT_NORMALIZED", "AMBIGUOUS", "NOT_FOUND")


def normalize(ref):
    """Lookup key: NFKC, trimmed, uppercase (internal characters unchanged)."""
    return unicodedata.normalize("NFKC", str(ref or "")).strip().upper()


def normalize_id_format(key):
    m = DEVICE_ID_SPACED.match(key)
    return f"{m.group(1)}{m.group(2)}" if m else None


def resolve(ref, candidates):
    """ref: user/model reference; candidates: canonical ids. -> resolution dict (always includes the original)."""
    original = "" if ref is None else str(ref)
    key = normalize(original)
    out = {"original_reference": original, "normalized_reference": key, "resolved_entity_id": None,
           "resolution_method": NOT_FOUND, "candidates": []}
    cands = list(dict.fromkeys(candidates))
    if original in cands:
        out.update(resolved_entity_id=original, resolution_method=EXACT); return out
    if not key: return out
    by_key = {}
    for c in cands: by_key.setdefault(normalize(c), []).append(c)
    hits = by_key.get(key, [])
    method = CASE_INSENSITIVE
    if not hits:
        alt = normalize_id_format(key)
        if alt:
            hits = by_key.get(alt, []); method = ID_FORMAT; out["normalized_reference"] = alt
    if len(hits) == 1:
        out.update(resolved_entity_id=hits[0], resolution_method=method)
    elif len(hits) > 1:
        out.update(resolution_method=AMBIGUOUS, candidates=sorted(hits))
    return out


def looks_like_device_id(ref):
    """True for references shaped like a TCP object id (e.g. S3, s3, PCMS 1) - used only to offer 'Create new <ID>'."""
    key = normalize(ref)
    return bool(re.match(r"^[A-Z][A-Z0-9_-]{0,15}$", key) and re.search(r"[0-9]", key)) or bool(normalize_id_format(key))


def canonical_new_id(ref):
    key = normalize(ref)
    return normalize_id_format(key) or key
