"""Repository interfaces. Business services depend only on these; JSON files implement them today and a database
implementation can replace json_store.py later without changing business rules.

Records are immutable: create() never replaces an existing record. Lifecycle changes are append-only events.
"""
import abc


class ImmutableExists(Exception):
    """A record with this id already exists (never overwritten)."""


class LegacyStreamReadOnly(Exception):
    """An event stream written before S2 (no envelope) can be read but not appended to."""


class IntegrityError(Exception):
    """A stored record does not match its content hash."""


class RecordStore(abc.ABC):
    @abc.abstractmethod
    def create(self, collection, record_id, record): ...      # -> stored record (with content_sha256)

    @abc.abstractmethod
    def get(self, collection, record_id): ...                 # -> record or None (hash verified)

    @abc.abstractmethod
    def list(self, collection): ...                           # -> [record]

    @abc.abstractmethod
    def append_event(self, collection, record_id, event, durable=False): ...

    @abc.abstractmethod
    def events(self, collection, record_id): ...              # -> [event]

    @abc.abstractmethod
    def put_blob(self, collection, record_id, name, data): ... # -> {"uri", "sha256", "size_bytes"}

    @abc.abstractmethod
    def blob_path(self, collection, record_id, name): ...

    @abc.abstractmethod
    def compare_and_set_head(self, key, expected, new): ...    # -> bool


class _Repo:
    collection = None

    def __init__(self, store):
        self.store = store

    def create(self, record_id, record): return self.store.create(self.collection, record_id, record)
    def get(self, record_id): return self.store.get(self.collection, record_id)
    def list(self): return self.store.list(self.collection)
    def append_event(self, record_id, event, durable=False): return self.store.append_event(self.collection, record_id, event, durable)
    def events(self, record_id): return self.store.events(self.collection, record_id)


class ConversationRepository(_Repo): collection = "conversations"
class ChangeSetRepository(_Repo): collection = "changesets"
class PlanVersionRepository(_Repo): collection = "versions"
class SiteEvidenceRepository(_Repo): collection = "site-evidence"
class SMEReviewRepository(_Repo): collection = "sme-reviews"
class ArtifactRepository(_Repo): collection = "artifacts"
class InterpretationRepository(_Repo): collection = "interpretations"
class ResumeAttemptRepository(_Repo): collection = "resume-attempts"
