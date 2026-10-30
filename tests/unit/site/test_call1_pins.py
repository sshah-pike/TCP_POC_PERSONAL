"""Pins on the call 1 prompt and schema (S6). A change to either is deliberate: update the hash in the same commit, and
remember that every recorded AI fixture goes stale with it (the request fingerprint includes both)."""
from tcp_planner.ai import call1
from tcp_planner.contracts import canonical_json, sha256_hex

# prompt = SYSTEM + INSTRUCTIONS template; changed once after STOP 2: the edge sentence no longer says "facing north"
PROMPT_SHA256 = "58a344b4f526c55c965b35f80d9c8d78d222932fdbda2e80b1f606ce2550ad6f"
SCHEMA_SHA256 = "39d25f9a2c671005ed7a11a09659e01ee863dc7f6dce96a1399af9f2e3f43e02"      # unchanged since the spike schema


def test_prompt_template_is_pinned():
    assert sha256_hex("\x00".join([call1.SYSTEM, call1.INSTRUCTIONS])) == PROMPT_SHA256


def test_schema_is_pinned():
    assert sha256_hex(canonical_json(call1.wire_schema())) == SCHEMA_SHA256


def test_edge_sentence_does_not_depend_on_the_direction_of_the_road():
    assert "facing north" not in call1.INSTRUCTIONS and "left and right" not in call1.INSTRUCTIONS
    assert "road_edge_left and road_edge_right: the two pavement edges, either order." in call1.INSTRUCTIONS


def test_the_field_names_of_the_edge_marks_are_kept():
    assert {"road_edge_left", "road_edge_right"} <= set(call1.MARK_FEATURES)
