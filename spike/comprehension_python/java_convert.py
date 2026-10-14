"""Java result <-> FileClaims, unchanged java.py behind a thin converter (design section 3, spike question S4).

SPIKE CODE - DO NOT MERGE.
"""
from __future__ import annotations

import json
from dataclasses import fields

from agenttalk.comprehension.adapters import java as java_adapter

from .claims import (AdapterIdentity, EdgeClaim, EntryPointClaim, FileClaims, ProblemClaim, UnitClaim,
                     from_json, to_json)

JAVA = AdapterIdentity(java_adapter.ADAPTER_NAME, java_adapter.ADAPTER_VERSION, java_adapter.RULE_VERSION)

# Java's five yes/no unit facts become traits, and the bare-String main becomes an entry-point trait.
UNIT_TRAITS = (("is_interface", "interface"), ("is_abstract", "abstract"), ("is_enum", "enum"),
               ("is_non_static_member", "inner"), ("is_local", "local"))
ENTRY_TRAIT = ("uses_unqualified_string_param", "main_bare_string")
EXTRA_KEYS = ("declared_module_paths", "descriptor_name_conflicts", "web_servlet_declared_names",
              "web_filter_declared_names")

# The converter must name every field the Java types have, so a new Java field fails loudly here.
_EXPECTED = {
    java_adapter.JavaFileResult: {"units", "edges", "entry_points", "problems", "package", *EXTRA_KEYS},
    java_adapter.JavaUnitClaim: {"relative_path", "qualified_name", "simple_name", "line", "classification",
                                 *(f for f, _ in UNIT_TRAITS)},
    java_adapter.JavaEdgeClaim: {f.name for f in fields(EdgeClaim)},
    java_adapter.JavaEntryPointClaim: {"qualified_name", "kind", "name", "line", "evidence_class", ENTRY_TRAIT[0]},
    java_adapter.JavaAdapterProblem: {f.name for f in fields(ProblemClaim)},
}
for _cls, _names in _EXPECTED.items():
    _actual = {f.name for f in fields(_cls)}
    if _actual != _names:
        raise RuntimeError(f"converter out of date for {_cls.__name__}: {sorted(_actual ^ _names)}")


def _language(relative_path: str) -> str:
    return "java" if relative_path.lower().endswith(".java") else "xml"


def to_file_claims(relative_path: str, result: java_adapter.JavaFileResult) -> FileClaims:
    return FileClaims(
        adapter=JAVA,
        language=_language(relative_path),
        relative_path=relative_path,
        namespace=result.package,
        reader="java-regex",
        units=[UnitClaim(u.relative_path, u.qualified_name, u.simple_name, u.line, u.classification,
                         tuple(t for f, t in UNIT_TRAITS if getattr(u, f))) for u in result.units],
        edges=[EdgeClaim(e.from_qualified_name, e.relation, e.target, e.target_kind, e.evidence_class,
                         e.line, e.phase, e.optional) for e in result.edges],
        entry_points=[EntryPointClaim(p.qualified_name, p.kind, p.name, p.line, p.evidence_class,
                                      (ENTRY_TRAIT[1],) if p.uses_unqualified_string_param else ())
                      for p in result.entry_points],
        problems=[ProblemClaim(p.reason_code, p.detail, p.qualified_name) for p in result.problems],
        extras={
            "declared_module_paths": list(result.declared_module_paths),
            "descriptor_name_conflicts": [[a, list(c)] for a, c in result.descriptor_name_conflicts],
            "web_servlet_declared_names": dict(result.web_servlet_declared_names),
            "web_filter_declared_names": dict(result.web_filter_declared_names),
        },
    )


def from_file_claims(claims: FileClaims) -> java_adapter.JavaFileResult:
    x = claims.extras
    return java_adapter.JavaFileResult(
        units=[java_adapter.JavaUnitClaim(
            relative_path=u.relative_path, qualified_name=u.qualified_name, simple_name=u.simple_name,
            line=u.line, classification=u.classification,
            **{f: t in u.traits for f, t in UNIT_TRAITS}) for u in claims.units],
        edges=[java_adapter.JavaEdgeClaim(
            from_qualified_name=e.from_qualified_name, relation=e.relation, target=e.target,
            target_kind=e.target_kind, evidence_class=e.evidence_class, line=e.line, phase=e.phase,
            optional=e.optional) for e in claims.edges],
        entry_points=[java_adapter.JavaEntryPointClaim(
            qualified_name=p.qualified_name, kind=p.kind, name=p.name, line=p.line,
            evidence_class=p.evidence_class, uses_unqualified_string_param=ENTRY_TRAIT[1] in p.traits)
            for p in claims.entry_points],
        problems=[java_adapter.JavaAdapterProblem(p.reason_code, p.detail, p.qualified_name) for p in claims.problems],
        declared_module_paths=list(x["declared_module_paths"]),
        descriptor_name_conflicts=[(a, list(c)) for a, c in x["descriptor_name_conflicts"]],
        web_servlet_declared_names=dict(x["web_servlet_declared_names"]),
        web_filter_declared_names=dict(x["web_filter_declared_names"]),
        package=claims.namespace,
    )


def round_trip_problem(relative_path: str, result: java_adapter.JavaFileResult) -> str | None:
    """None when Java -> FileClaims -> JSON -> FileClaims -> Java gives back exactly the original."""
    claims = to_file_claims(relative_path, result)
    wire = json.loads(json.dumps(to_json(claims)))
    back = from_file_claims(from_json(wire))
    if back != result:
        return "dataclass inequality"
    if java_adapter.file_result_to_json(back) != java_adapter.file_result_to_json(result):
        return "java wire format differs"
    return None
