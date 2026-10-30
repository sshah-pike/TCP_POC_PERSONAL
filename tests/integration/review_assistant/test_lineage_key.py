"""S3: the SME lineage key is lineage_key(project_id, zone geometry hash) (D-82), read from the run's project link.
A run outside a project has no lineage key and the assistant answers NO_PROJECT_LINEAGE (Q9-A)."""
import json

from tcp_planner.evaluation import ground_truth_labels as labels
from tcp_planner.intake import kml_reader
from tcp_planner.intake.lineage import lineage_key, zone_geometry_hash
from tcp_planner.orchestration import offline_scenarios as offline
from tcp_planner.storage import run_records as records, run_store as store

from .conftest import call, login


def test_project_run_has_the_composite_lineage_key(aenv, runs):
    from tcp_planner.review.assistant.services import run_context
    rid = runs["supported"]
    proj = records.read(rid, "request")["request"]["project"]
    sc = offline.build("supported")
    loc = kml_reader.location_from_coordinates(sc["lat"], sc["lon"])
    expected = lineage_key(proj["project_id"], zone_geometry_hash([loc]))
    assert proj["lineage_key"] == expected
    ctx = run_context.load(rid)
    assert ctx["lineage_key"] == expected == labels.site_id_for(records.read(rid, "request")["request"])
    # the old key (hash of the work reference) is gone
    from tcp_planner.storage.evidence_store import geometry_hash
    assert expected != geometry_hash(ctx["project_geometry"])[:16]


def test_scenarios_are_separate_projects_with_separate_lineages(aenv, runs):
    keys = {sc: records.read(rid, "request")["request"]["project"]["lineage_key"] for sc, rid in runs.items()}
    assert len(set(keys.values())) == len(keys)      # same point, different offline project each


def test_run_outside_a_project_has_no_lineage_and_is_not_reviewable(aenv, runs):
    from tests.integration.web_api import inproc
    rid, rdir = store.create_run({"input_type": "offline", "offline_scenario": "supported", "offline_input": "coordinates",
                                  "advanced": {"no_dwt": True}}, set(offline.SCENARIOS))
    inproc.run(rdir)
    assert labels.site_id_for(records.read(rid, "request")["request"]) is None
    t = login()
    body = call("GET", f"runs/{rid}/eligibility", token=t)[2]
    assert not body["eligible"] and "NO_PROJECT_LINEAGE" in {r["code"] for r in body["reasons"]}
    st, _, err = call("POST", "conversations", {"run_id": rid}, token=t)
    assert st == 409 and err["error_code"] == "RUN_NOT_ELIGIBLE"
    assert "NO_PROJECT_LINEAGE" in {r["code"] for r in err["details"]["reasons"]}
    # a comparison whose source run has no lineage finds no label
    assert labels.site_id_for(None) is None and labels.site_id_for({}) is None


def test_a_resumed_zone_run_keeps_the_lineage(aenv, runs):
    from tcp_planner.orchestration import run_relations as relations
    from tests.integration.web_api import inproc
    parent = runs["supported"]
    child, cdir = relations.create_resume_run(parent, "rules")
    inproc.run(cdir)
    assert records.read(child, "request")["request"]["project"] == records.read(parent, "request")["request"]["project"]
