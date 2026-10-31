"""Shared fixtures of the site-understanding tests."""
import json
import os

import pytest

from tcp_planner.site_model import site_config


@pytest.fixture
def overpass_provider(tmp_path, monkeypatch):
    """Config with osm.provider = overpass, for the tests written when Overpass was the only provider (the shipped default is osm_api).
    Every reader of config/site_understanding.json takes the temporary copy for the length of the test."""
    with open(site_config.PATH, encoding="utf-8") as f: cfg = json.load(f)
    cfg["osm"]["provider"]["value"] = "overpass"
    path = tmp_path / "site_understanding_overpass.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setattr(site_config, "PATH", str(path))
    return str(path)
