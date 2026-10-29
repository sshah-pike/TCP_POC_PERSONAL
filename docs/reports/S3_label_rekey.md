# S3: re-key of the one ground-truth label (D-82)

Owner-approved one-off (S3 decisions Q10a and Q10b). The label `var/labels/771bbc3d0913044a.json` was keyed by the POC key
(`geometry_hash(work reference)[:16]`). Since S3 a label is keyed by the zone's lineage key,
`lineage_key(project_id, zone_geometry_hash)` (D-82).

| | |
| --- | --- |
| Label point | 41.4151206, -71.741541 (no work path) |
| Demo KML | `tests/fixtures/kml/demo) RI-91 Alton Bradford Rd - single point (demo, not a real pole).kml`: one Point, coordinates `-71.741541,41.4151206`. **Equal to the label point** (checked before anything was moved) |
| Project id (usable geometry only, Q2-B) | `PRJ-f46419bbc77c92b5` |
| Zone | `ZONE-c0690d642bc7` |
| Old key | `771bbc3d0913044a` |
| New key | `04bf2dc90e9c3cac` |
| Effect | uploading that KML as a project gives this zone and this key, so the label is found. Same fields, same status (DRAFT: nobody confirmed it), same source run |

What changed in the label: `site_id` and one new history entry (`rekey`). Nothing else: the nine fields, their evidence,
`status`, `drafted_by`, `work_reference` and `source_run_id` are identical (the script compared them).

What happened to the files: the new label is the state record `var/labels/04bf2dc90e9c3cac.state.json` (not tracked: `var/`
is ignored). The old file was moved, not deleted, to `backup/orphans/2026-10-29/var/labels/771bbc3d0913044a.json` and is
listed in that folder's `MANIFEST.json` (an approved one-off exception to "moves only in S15"). Restore:
`python scripts/restore_backup.py backup/orphans/2026-10-29 --apply --only "var/labels/771bbc3d0913044a.json"`.
The file had never been tracked, so a restore with `git mv` makes it tracked; run `git rm --cached` on it afterwards if that
is not wanted.

## Before (`771bbc3d0913044a.json`, as moved)

```json
{
  "confirm_reason": null,
  "confirmed_at": null,
  "confirmed_by": null,
  "drafted_at": "2026-10-16T17:31:25+00:00",
  "drafted_by": "Claude (assistant draft - not ground truth)",
  "fields": {
    "road.divided": {
      "evidence": [
        {
          "artifact": "map_1",
          "file": "map_1.png",
          "run": "20261016-213622-483ff4",
          "sha256": "ed8d6efe0d64f91435eee5122b6ebbd812c1555b5f6fe897e1104d00e45926e1"
        },
        {
          "artifact": "map_view_2",
          "file": "map_view_2.png",
          "run": "20261016-221800-2b4518",
          "sha256": "1c36bfdb37470eaf2ea8d8d59b3f23b2e0ea1f8ef0b58cf2b350951c6d022fe0"
        },
        {
          "artifact": "map_view_3",
          "file": "map_view_3.png",
          "run": "20261016-221800-2b4518",
          "sha256": "7668f4aed72814e73f5177894c645c3740f4a2fc82583ae744b87445080158a3"
        }
      ],
      "note": "no median or barrier anywhere in the corridor",
      "tolerance": null,
      "value": false
    },
    "road.lane_count": {
      "evidence": [
        {
          "artifact": "map_view_1",
          "file": "map_view_1.png",
          "run": "20261016-221800-2b4518",
          "sha256": "959768acb820394177caddc81758ec4af20d3660c34a508337ff19645cf6ebe0"
        },
        {
          "artifact": "map_view_2",
          "file": "map_view_2.png",
          "run": "20261016-221800-2b4518",
          "sha256": "1c36bfdb37470eaf2ea8d8d59b3f23b2e0ea1f8ef0b58cf2b350951c6d022fe0"
        },
        {
          "artifact": "map_view_3",
          "file": "map_view_3.png",
          "run": "20261016-221800-2b4518",
          "sha256": "7668f4aed72814e73f5177894c645c3740f4a2fc82583ae744b87445080158a3"
        }
      ],
      "note": "one lane each way; double yellow centre line, white edge lines visible in close-ups",
      "tolerance": null,
      "value": 2
    },
    "road.traveled_way_width_m": {
      "evidence": [
        {
          "artifact": "map_view_1",
          "file": "map_view_1.png",
          "run": "20261016-221800-2b4518",
          "sha256": "959768acb820394177caddc81758ec4af20d3660c34a508337ff19645cf6ebe0"
        }
      ],
      "note": "edge line to edge line, measured 8.4-15.7 m along a perpendicular brightness profile through the work reference in the zoom-19 close-up (0.112 m/px); reviewer should verify",
      "tolerance": 1.0,
      "value": 7.3
    },
    "road.two_way": {
      "evidence": [
        {
          "artifact": "map_view_1",
          "file": "map_view_1.png",
          "run": "20261016-221800-2b4518",
          "sha256": "959768acb820394177caddc81758ec4af20d3660c34a508337ff19645cf6ebe0"
        },
        {
          "artifact": "map_view_2",
          "file": "map_view_2.png",
          "run": "20261016-221800-2b4518",
          "sha256": "1c36bfdb37470eaf2ea8d8d59b3f23b2e0ea1f8ef0b58cf2b350951c6d022fe0"
        },
        {
          "artifact": "map_view_3",
          "file": "map_view_3.png",
          "run": "20261016-221800-2b4518",
          "sha256": "7668f4aed72814e73f5177894c645c3740f4a2fc82583ae744b87445080158a3"
        }
      ],
      "note": "double yellow centre line along the corridor",
      "tolerance": null,
      "value": true
    },
    "site.complex_intersection_conflict": {
      "evidence": [
        {
          "artifact": "map_1",
          "file": "map_1.png",
          "run": "20261016-213622-483ff4",
          "sha256": "ed8d6efe0d64f91435eee5122b6ebbd812c1555b5f6fe897e1104d00e45926e1"
        },
        {
          "artifact": "map_view_2",
          "file": "map_view_2.png",
          "run": "20261016-221800-2b4518",
          "sha256": "1c36bfdb37470eaf2ea8d8d59b3f23b2e0ea1f8ef0b58cf2b350951c6d022fe0"
        },
        {
          "artifact": "map_view_3",
          "file": "map_view_3.png",
          "run": "20261016-221800-2b4518",
          "sha256": "7668f4aed72814e73f5177894c645c3740f4a2fc82583ae744b87445080158a3"
        }
      ],
      "note": "UNCERTAIN - access points within the corridor (parking-lot entrance, house driveways, paved lanes ~180 m NE) appear private; OSM maps them as service ways. Needs local knowledge to confirm none is a public road.",
      "tolerance": null,
      "value": false
    },
    "work.affects_pedestrian_route": {
      "evidence": [
        {
          "artifact": "map_view_1",
          "file": "map_view_1.png",
          "run": "20261016-221800-2b4518",
          "sha256": "959768acb820394177caddc81758ec4af20d3660c34a508337ff19645cf6ebe0"
        },
        {
          "artifact": "map_view_2",
          "file": "map_view_2.png",
          "run": "20261016-221800-2b4518",
          "sha256": "1c36bfdb37470eaf2ea8d8d59b3f23b2e0ea1f8ef0b58cf2b350951c6d022fe0"
        },
        {
          "artifact": "map_view_3",
          "file": "map_view_3.png",
          "run": "20261016-221800-2b4518",
          "sha256": "7668f4aed72814e73f5177894c645c3740f4a2fc82583ae744b87445080158a3"
        },
        {
          "artifact": "map_1",
          "file": "map_1.png",
          "run": "20261016-213622-483ff4",
          "sha256": "ed8d6efe0d64f91435eee5122b6ebbd812c1555b5f6fe897e1104d00e45926e1"
        }
      ],
      "note": "no sidewalks on either side and no crosswalks visible in any view",
      "tolerance": null,
      "value": false
    },
    "work.encroaches_traveled_way": {
      "evidence": [
        {
          "artifact": "map_view_1",
          "file": "map_view_1.png",
          "run": "20261016-221800-2b4518",
          "sha256": "959768acb820394177caddc81758ec4af20d3660c34a508337ff19645cf6ebe0"
        }
      ],
      "note": "follows from the location above",
      "tolerance": null,
      "value": false
    },
    "work.location": {
      "evidence": [
        {
          "artifact": "map_view_1",
          "file": "map_view_1.png",
          "run": "20261016-221800-2b4518",
          "sha256": "959768acb820394177caddc81758ec4af20d3660c34a508337ff19645cf6ebe0"
        }
      ],
      "note": "grass yard ~8.4 m from the nearest edge line; paved shoulder ends ~5.7 m from the point",
      "tolerance": null,
      "value": "BEYOND_SHOULDER"
    },
    "work.side": {
      "evidence": [
        {
          "artifact": "map_view_1",
          "file": "map_view_1.png",
          "run": "20261016-221800-2b4518",
          "sha256": "959768acb820394177caddc81758ec4af20d3660c34a508337ff19645cf6ebe0"
        }
      ],
      "note": "work reference is north-west of the road; LEFT for travel at the 63 deg reference bearing",
      "tolerance": null,
      "value": "LEFT"
    }
  },
  "history": [
    {
      "action": "draft",
      "at": "2026-10-16T17:31:25+00:00",
      "by": "Claude (assistant draft - not ground truth)",
      "reason": "drafted from saved Azure evidence close-ups for evaluation; requires confirmation by a person"
    }
  ],
  "name": "RI-91 Alton Bradford Rd (demo point)",
  "site_id": "771bbc3d0913044a",
  "source_run_id": "20261016-213622-483ff4",
  "status": "DRAFT",
  "work_path": [],
  "work_reference": {
    "latitude": 41.4151206,
    "longitude": -71.741541
  }
}
```

## After (`04bf2dc90e9c3cac.state.json`, the `value` of the record)

```json
{
  "confirm_reason": null,
  "confirmed_at": null,
  "confirmed_by": null,
  "drafted_at": "2026-10-16T17:31:25+00:00",
  "drafted_by": "Claude (assistant draft - not ground truth)",
  "fields": {
    "road.divided": {
      "evidence": [
        {
          "artifact": "map_1",
          "file": "map_1.png",
          "run": "20261016-213622-483ff4",
          "sha256": "ed8d6efe0d64f91435eee5122b6ebbd812c1555b5f6fe897e1104d00e45926e1"
        },
        {
          "artifact": "map_view_2",
          "file": "map_view_2.png",
          "run": "20261016-221800-2b4518",
          "sha256": "1c36bfdb37470eaf2ea8d8d59b3f23b2e0ea1f8ef0b58cf2b350951c6d022fe0"
        },
        {
          "artifact": "map_view_3",
          "file": "map_view_3.png",
          "run": "20261016-221800-2b4518",
          "sha256": "7668f4aed72814e73f5177894c645c3740f4a2fc82583ae744b87445080158a3"
        }
      ],
      "note": "no median or barrier anywhere in the corridor",
      "tolerance": null,
      "value": false
    },
    "road.lane_count": {
      "evidence": [
        {
          "artifact": "map_view_1",
          "file": "map_view_1.png",
          "run": "20261016-221800-2b4518",
          "sha256": "959768acb820394177caddc81758ec4af20d3660c34a508337ff19645cf6ebe0"
        },
        {
          "artifact": "map_view_2",
          "file": "map_view_2.png",
          "run": "20261016-221800-2b4518",
          "sha256": "1c36bfdb37470eaf2ea8d8d59b3f23b2e0ea1f8ef0b58cf2b350951c6d022fe0"
        },
        {
          "artifact": "map_view_3",
          "file": "map_view_3.png",
          "run": "20261016-221800-2b4518",
          "sha256": "7668f4aed72814e73f5177894c645c3740f4a2fc82583ae744b87445080158a3"
        }
      ],
      "note": "one lane each way; double yellow centre line, white edge lines visible in close-ups",
      "tolerance": null,
      "value": 2
    },
    "road.traveled_way_width_m": {
      "evidence": [
        {
          "artifact": "map_view_1",
          "file": "map_view_1.png",
          "run": "20261016-221800-2b4518",
          "sha256": "959768acb820394177caddc81758ec4af20d3660c34a508337ff19645cf6ebe0"
        }
      ],
      "note": "edge line to edge line, measured 8.4-15.7 m along a perpendicular brightness profile through the work reference in the zoom-19 close-up (0.112 m/px); reviewer should verify",
      "tolerance": 1.0,
      "value": 7.3
    },
    "road.two_way": {
      "evidence": [
        {
          "artifact": "map_view_1",
          "file": "map_view_1.png",
          "run": "20261016-221800-2b4518",
          "sha256": "959768acb820394177caddc81758ec4af20d3660c34a508337ff19645cf6ebe0"
        },
        {
          "artifact": "map_view_2",
          "file": "map_view_2.png",
          "run": "20261016-221800-2b4518",
          "sha256": "1c36bfdb37470eaf2ea8d8d59b3f23b2e0ea1f8ef0b58cf2b350951c6d022fe0"
        },
        {
          "artifact": "map_view_3",
          "file": "map_view_3.png",
          "run": "20261016-221800-2b4518",
          "sha256": "7668f4aed72814e73f5177894c645c3740f4a2fc82583ae744b87445080158a3"
        }
      ],
      "note": "double yellow centre line along the corridor",
      "tolerance": null,
      "value": true
    },
    "site.complex_intersection_conflict": {
      "evidence": [
        {
          "artifact": "map_1",
          "file": "map_1.png",
          "run": "20261016-213622-483ff4",
          "sha256": "ed8d6efe0d64f91435eee5122b6ebbd812c1555b5f6fe897e1104d00e45926e1"
        },
        {
          "artifact": "map_view_2",
          "file": "map_view_2.png",
          "run": "20261016-221800-2b4518",
          "sha256": "1c36bfdb37470eaf2ea8d8d59b3f23b2e0ea1f8ef0b58cf2b350951c6d022fe0"
        },
        {
          "artifact": "map_view_3",
          "file": "map_view_3.png",
          "run": "20261016-221800-2b4518",
          "sha256": "7668f4aed72814e73f5177894c645c3740f4a2fc82583ae744b87445080158a3"
        }
      ],
      "note": "UNCERTAIN - access points within the corridor (parking-lot entrance, house driveways, paved lanes ~180 m NE) appear private; OSM maps them as service ways. Needs local knowledge to confirm none is a public road.",
      "tolerance": null,
      "value": false
    },
    "work.affects_pedestrian_route": {
      "evidence": [
        {
          "artifact": "map_view_1",
          "file": "map_view_1.png",
          "run": "20261016-221800-2b4518",
          "sha256": "959768acb820394177caddc81758ec4af20d3660c34a508337ff19645cf6ebe0"
        },
        {
          "artifact": "map_view_2",
          "file": "map_view_2.png",
          "run": "20261016-221800-2b4518",
          "sha256": "1c36bfdb37470eaf2ea8d8d59b3f23b2e0ea1f8ef0b58cf2b350951c6d022fe0"
        },
        {
          "artifact": "map_view_3",
          "file": "map_view_3.png",
          "run": "20261016-221800-2b4518",
          "sha256": "7668f4aed72814e73f5177894c645c3740f4a2fc82583ae744b87445080158a3"
        },
        {
          "artifact": "map_1",
          "file": "map_1.png",
          "run": "20261016-213622-483ff4",
          "sha256": "ed8d6efe0d64f91435eee5122b6ebbd812c1555b5f6fe897e1104d00e45926e1"
        }
      ],
      "note": "no sidewalks on either side and no crosswalks visible in any view",
      "tolerance": null,
      "value": false
    },
    "work.encroaches_traveled_way": {
      "evidence": [
        {
          "artifact": "map_view_1",
          "file": "map_view_1.png",
          "run": "20261016-221800-2b4518",
          "sha256": "959768acb820394177caddc81758ec4af20d3660c34a508337ff19645cf6ebe0"
        }
      ],
      "note": "follows from the location above",
      "tolerance": null,
      "value": false
    },
    "work.location": {
      "evidence": [
        {
          "artifact": "map_view_1",
          "file": "map_view_1.png",
          "run": "20261016-221800-2b4518",
          "sha256": "959768acb820394177caddc81758ec4af20d3660c34a508337ff19645cf6ebe0"
        }
      ],
      "note": "grass yard ~8.4 m from the nearest edge line; paved shoulder ends ~5.7 m from the point",
      "tolerance": null,
      "value": "BEYOND_SHOULDER"
    },
    "work.side": {
      "evidence": [
        {
          "artifact": "map_view_1",
          "file": "map_view_1.png",
          "run": "20261016-221800-2b4518",
          "sha256": "959768acb820394177caddc81758ec4af20d3660c34a508337ff19645cf6ebe0"
        }
      ],
      "note": "work reference is north-west of the road; LEFT for travel at the 63 deg reference bearing",
      "tolerance": null,
      "value": "LEFT"
    }
  },
  "history": [
    {
      "action": "draft",
      "at": "2026-10-16T17:31:25+00:00",
      "by": "Claude (assistant draft - not ground truth)",
      "reason": "drafted from saved Azure evidence close-ups for evaluation; requires confirmation by a person"
    },
    {
      "action": "rekey",
      "at": "2026-10-29T18:49:29+00:00",
      "by": "S3 migration (owner-approved)",
      "from_site_id": "771bbc3d0913044a",
      "project_id": "PRJ-f46419bbc77c92b5",
      "reason": "D-82: the SME lineage key is lineage_key(project_id, zone geometry hash); the POC key was the hash of the work reference. Same point, same fields, same status.",
      "to_site_id": "04bf2dc90e9c3cac",
      "zone_id": "ZONE-c0690d642bc7"
    }
  ],
  "name": "RI-91 Alton Bradford Rd (demo point)",
  "site_id": "04bf2dc90e9c3cac",
  "source_run_id": "20261016-213622-483ff4",
  "status": "DRAFT",
  "work_path": [],
  "work_reference": {
    "latitude": 41.4151206,
    "longitude": -71.741541
  }
}
```
