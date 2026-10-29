"""Record models for rule pack v1 (composed, table-shaped; D-30, ADR-027). Shapes only: no regulatory values here.

A pack is `rule_pack/pack.json` (the manifest) plus part files. Each part holds flat arrays of records, one array per
future database table; records refer to each other by id, never by nesting. Variable conditions stay as validated
JSON columns (`Expr`). `schema_version` is carried by the manifest and by every part; a record inherits its part's.
"""
from enum import Enum
from typing import Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = "1"


def _check(cond, msg):
    if not cond: raise ValueError(msg)


class _Rec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Layer(str, Enum):
    FEDERAL = "FEDERAL"            # MUTCD; the only populated layer in v1
    JURISDICTION = "JURISDICTION"  # state or agency supplements (empty in v1)
    CLIENT = "CLIENT"              # client practice (empty in v1)
    DEVIATION = "DEVIATION"        # pre-approved deviations (empty in v1)


class Status(str, Enum):
    SOURCED = "SOURCED"                                # value present, cited
    SOURCE_REVIEW_REQUIRED = "SOURCE_REVIEW_REQUIRED"  # the source names the item but gives no usable value
    UNKNOWN = "UNKNOWN"                                # no source at all


class Strength(str, Enum):
    STANDARD = "STANDARD"
    GUIDANCE = "GUIDANCE"
    OPTION = "OPTION"
    SUPPORT = "SUPPORT"


class Evidence(str, Enum):
    QUOTE = "QUOTE"                                  # verbatim text on the cited page
    FIGURE_TRANSCRIPTION = "FIGURE_TRANSCRIPTION"    # read from a figure drawing that has no text layer


Unit = Literal["ft", "in", "mph", "count", "ratio"]
Scalar = Union[bool, int, float, str]


class ArtifactRef(_Rec):
    uri: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size: int
    media_type: str


# ---------- condition expressions (JSON column) ----------
class Cmp(_Rec):
    field: str
    op: Literal["EQ", "NE", "LT", "LE", "GT", "GE", "IN"]
    value: Union[Scalar, list[Scalar]]


class All(_Rec):
    all: list["Expr"] = Field(min_length=1)


class Any_(_Rec):
    any: list["Expr"] = Field(min_length=1)


class Not(_Rec):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)
    not_: "Expr" = Field(alias="not")


Expr = Union[Cmp, All, Any_, Not]
for _m in (All, Any_, Not): _m.model_rebuild()


def _children(e):
    if isinstance(e, Not): return [e.not_]
    return e.all if isinstance(e, All) else e.any if isinstance(e, Any_) else []


def expr_fields(e):
    """Every field name an expression reads."""
    return [e.field] if isinstance(e, Cmp) else [f for x in _children(e) for f in expr_fields(x)]


def expr_numbers(e):
    """Every numeric literal in an expression (bools excluded)."""
    if isinstance(e, Cmp):
        vals = e.value if isinstance(e.value, list) else [e.value]
        return [v for v in vals if isinstance(v, (int, float)) and not isinstance(v, bool)]
    return [n for x in _children(e) for n in expr_numbers(x)]


# ---------- manifest ----------
class PartRef(_Rec):
    path: str              # relative to the pack root, forward slashes
    layer: Layer
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Manifest(_Rec):
    schema_version: str
    pack_id: str
    version: str
    status: Literal["DRAFT"]   # nothing in the pack is approved by default; SME approval is a later slice
    source_edition_note: str
    ta_scope: list[str] = Field(min_length=1)   # the only TAs the pack may define; anything else is NO_TA_MATCH
    parts: list[PartRef] = Field(min_length=1)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


# ---------- tables ----------
class SourceDocument(_Rec):
    id: str
    title: str
    publisher: str
    edition: str
    revision: str
    authority_level: Layer
    artifact: ArtifactRef


class SourceRef(_Rec):
    id: str
    source_document_id: str
    section: str
    paragraph: Optional[str]
    table: Optional[str]
    figure: Optional[str]
    note: Optional[str]
    page_printed: str
    page_pdf: int
    strength: Strength
    evidence: Evidence
    quote: Optional[str]             # required for QUOTE: normalised verbatim text from the cited page
    transcription: Optional[str]     # required for FIGURE_TRANSCRIPTION: what the drawing shows, as read
    figure_render: Optional[ArtifactRef]

    @model_validator(mode="after")
    def _evidence(self):
        if self.evidence == Evidence.QUOTE:
            _check(self.quote and not self.transcription, "QUOTE evidence needs a quote and no transcription")
        else:
            _check(self.transcription and self.figure_render and self.figure,
                   "FIGURE_TRANSCRIPTION evidence needs a transcription, a figure and a figure render")
        return self


class _Valued(_Rec):
    """A record whose value may be unsourced. Unsourced means no value plus an SME question."""
    status: Status
    sme_question: Optional[str]
    interpretation: Optional[str]    # a reading of the source text; it counts as approved only on a SOURCED record

    @model_validator(mode="after")
    def _status(self):
        if self.status == Status.SOURCED: _check(not self.sme_question, "a SOURCED record carries no SME question")
        else: _check(self.sme_question, f"{self.status.value} needs an sme_question")
        return self


class TA(_Rec):
    id: str
    title: str
    figure: str
    source_ref_ids: list[str] = Field(min_length=1)


class EligibilityCondition(_Valued):
    id: str
    ta_id: str
    description: str
    expr: Optional[Expr]
    source_ref_ids: list[str] = Field(min_length=1)
    any_group: Optional[str] = None   # conditions sharing a group are OR'd (D-60: TA-33 road form is one OR'd rule)

    @model_validator(mode="after")
    def _expr(self):
        _check((self.expr is not None) == (self.status == Status.SOURCED), "only a SOURCED condition has an expr")
        return self


class Rule(_Valued):
    id: str
    layer: Layer
    ta_id: Optional[str]           # None: shared by every TA
    jurisdiction: Optional[str]
    topic: str
    strength: Optional[Strength]   # None only for UNKNOWN records (no source, so no strength)
    text: str                      # plain-language summary; the authority is the source quote
    condition: Optional[Expr]
    action: Optional[str]          # code the engine acts on when the condition holds, e.g. LANE_CLOSURE_NEEDED
    value: Optional[Union[int, float]]
    value_max: Optional[Union[int, float]]
    unit: Optional[Unit]
    qualifier: Optional[Literal["AT_LEAST", "AT_MOST", "APPROXIMATE", "EXACT"]]
    source_ref_ids: list[str]
    role: Literal["APPLY", "CITED_ONLY"] = "APPLY"   # CITED_ONLY: kept for the record, never applied (owner decision)
    overlaps: list[str] = []       # ids of records covering the same item, so nothing is applied twice

    @model_validator(mode="after")
    def _value(self):
        has = self.value is not None or self.value_max is not None
        _check(not (has and self.unit is None), "a numeric value needs a unit")
        if self.status != Status.SOURCED: _check(not has, f"{self.status.value} records carry no value")
        if self.status != Status.UNKNOWN:
            _check(self.source_ref_ids, "a rule needs a source_ref unless it is UNKNOWN")
            _check(self.strength is not None, "a sourced or source-review rule needs the strength of its source")
        return self


class FormulaCase(_Rec):
    when: Optional[Expr]           # None: the case always applies
    expression: str                # arithmetic over the formula's variables; evaluated by a whitelisted parser


class Formula(_Valued):
    id: str
    name: str
    strength: Strength
    qualifier: Literal["AT_LEAST", "AT_MOST", "APPROXIMATE", "EXACT"]
    role: Literal["COMPUTE", "CITED_ONLY"]   # CITED_ONLY: kept for the record, never used to compute (owner decision)
    variables: dict[str, str]      # symbol -> registry_field id, or the id of another formula whose result it uses
    result_unit: Unit
    cases: list[FormulaCase] = Field(min_length=1)
    source_ref_ids: list[str] = Field(min_length=1)


class TableDef(_Rec):
    id: str
    table: str
    title: str
    key_fields: dict[str, Optional[Unit]]     # name -> unit (None for categorical keys)
    value_fields: dict[str, Unit]
    source_ref_ids: list[str] = Field(min_length=1)


class TableRow(_Valued):
    id: str
    table_def_id: str
    key: dict[str, Scalar]
    values: dict[str, Optional[Union[int, float]]]
    source_ref_ids: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def _values(self):
        if self.status != Status.SOURCED:
            _check(all(v is None for v in self.values.values()), f"{self.status.value} rows carry no values")
        return self


class Device(_Rec):
    id: str
    code: str
    name: str
    catalog_id: Optional[str]      # id in assets/symbols/device_catalog.json (sizes and assets live there, S5)
    source_ref_ids: list[str] = Field(min_length=1)


class TaDeviceUse(_Rec):
    id: str
    ta_id: str
    device_id: str
    approach: str                  # e.g. "each approach", "approach with the closed lane"
    sequence: int                  # 1 = nearest the work, increasing upstream
    spacing_dimension: Optional[Literal["A", "B", "C"]]
    required: bool
    source_ref_ids: list[str] = Field(min_length=1)


class Deviation(_Rec):
    id: str
    rule_id: str
    authority: str
    conditions: Expr
    justification: str
    approver: str
    source_ref_ids: list[str] = Field(min_length=1)


class RegistryField(_Rec):
    id: str                        # the plan section 4B field name
    group: Literal["MANDATORY_START", "ASKED_IF_NEEDED", "OBSERVED_COMPUTED"]
    source_type: str
    value_type: Literal["enum", "number", "boolean", "string"]
    unit: Optional[Unit]
    enum_values: Optional[list[str]]
    plan_ref: str                  # where the plan defines the field

    @model_validator(mode="after")
    def _enum(self):
        _check((self.value_type == "enum") == bool(self.enum_values), "enum_values is required exactly for enum fields")
        return self


TABLES = {
    "source_document": SourceDocument, "source_ref": SourceRef, "ta": TA, "eligibility_condition": EligibilityCondition,
    "rule": Rule, "formula": Formula, "table_def": TableDef, "table_row": TableRow, "device": Device,
    "ta_device_use": TaDeviceUse, "deviation": Deviation, "registry_field": RegistryField,
}
# Fields that hold numbers which are document metadata or ordinals, not regulatory values.
METADATA_NUMBERS = {("source_document", "artifact.size"), ("source_ref", "page_pdf"), ("source_ref", "figure_render.size"),
                    ("ta_device_use", "sequence")}


class Part(_Rec):
    schema_version: str
    layer: Layer
    tables: dict[str, list[dict]]

    @field_validator("tables")
    @classmethod
    def _known(cls, v):
        unknown = sorted(set(v) - set(TABLES))
        _check(not unknown, f"unknown tables: {unknown}")
        return v
