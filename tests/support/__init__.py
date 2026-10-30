"""Test support: fixture recorder and replayer for Azure Maps, OSM and AI calls (S0).

Replay is the default. A call that has no recorded fixture raises MissingFixtureError; it never reaches the network.
Recording needs live providers and is run only by the user: python -m tests.support.record live ... (TCP_LIVE=1).
"""
