"""Fixture hook for the data source client (S6 commit 6): recorded responses keyed by the request fingerprint, in the same
write-once store as the other recorded kinds:  <site>/source/<fp>.json  {"status", "body_b64", "retrieved_at"}.

Replay never makes a live call; a missing fixture raises MissingFixtureError. Recording (the owner's run, TCP_LIVE=1) passes a
live transport to the SourceClient and the hook saves each 2xx response.
"""
from .fixtures import FixtureStore, fingerprint


class SourceFixtures:
    KIND = "source"

    def __init__(self, store):
        self.store = store if isinstance(store, FixtureStore) else FixtureStore(store)

    def has(self, fp):
        return self.store.has(self.KIND, fp)

    def load(self, record):
        doc, _ = self.store.load(self.KIND, record)
        return doc

    def save(self, record, doc):
        return self.store.save(self.KIND, record, doc)
