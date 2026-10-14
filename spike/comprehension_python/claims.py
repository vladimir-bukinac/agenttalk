"""Language-neutral claim types (design: docs/design/comprehension-python.md, section 3).

SPIKE CODE - DO NOT MERGE. Throwaway prototype for the two-day trial of the design.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class AdapterIdentity:
    name: str
    version: int
    rule_version: int


@dataclass(frozen=True)
class UnitClaim:
    relative_path: str
    qualified_name: str
    simple_name: str
    line: int
    classification: str
    traits: tuple[str, ...] = ()


@dataclass(frozen=True)
class EdgeClaim:
    from_qualified_name: str
    relation: str
    target: str
    target_kind: str
    evidence_class: str
    line: int | None
    phase: str
    optional: bool = False


@dataclass(frozen=True)
class EntryPointClaim:
    qualified_name: str
    kind: str
    name: str
    line: int | None
    evidence_class: str
    traits: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProblemClaim:
    reason_code: str
    detail: str
    qualified_name: str | None = None


@dataclass(frozen=True)
class FileClaims:
    adapter: AdapterIdentity
    language: str
    relative_path: str
    namespace: str | None
    reader: str
    units: list[UnitClaim] = field(default_factory=list)
    edges: list[EdgeClaim] = field(default_factory=list)
    entry_points: list[EntryPointClaim] = field(default_factory=list)
    problems: list[ProblemClaim] = field(default_factory=list)
    extras: dict = field(default_factory=dict)


def to_json(claims: FileClaims) -> dict:
    """The proposed worker wire format (schema version 2): plain JSON, no pickles."""
    data = asdict(claims)
    for key in ("units", "entry_points"):
        for row in data[key]:
            row["traits"] = list(row["traits"])
    return data


def from_json(data: dict) -> FileClaims:
    return FileClaims(
        adapter=AdapterIdentity(**data["adapter"]),
        language=data["language"],
        relative_path=data["relative_path"],
        namespace=data["namespace"],
        reader=data["reader"],
        units=[UnitClaim(**{**u, "traits": tuple(u["traits"])}) for u in data["units"]],
        edges=[EdgeClaim(**e) for e in data["edges"]],
        entry_points=[EntryPointClaim(**{**p, "traits": tuple(p["traits"])}) for p in data["entry_points"]],
        problems=[ProblemClaim(**p) for p in data["problems"]],
        extras=data["extras"],
    )
