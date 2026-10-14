"""Cross-file step for the spike: import resolution, inheritance and models, views, Django URL
composition, the S2 oracle and the S6 by-name string references (design sections 4 and 8).

SPIKE CODE - DO NOT MERGE.
"""
from __future__ import annotations

import sys
from collections import Counter, defaultdict

PY2_STDLIB = frozenset({
    "urllib2", "urlparse", "cPickle", "StringIO", "cStringIO", "httplib", "HTMLParser", "Queue",
    "ConfigParser", "SocketServer", "Cookie", "cookielib", "htmlentitydefs", "commands", "sets", "md5", "sha",
    "new", "exceptions", "__builtin__", "thread", "dummy_thread", "copy_reg", "repr", "Tkinter", "xmlrpclib",
    "SimpleXMLRPCServer", "anydbm", "dbhash", "whichdb", "robotparser", "UserDict", "UserList", "UserString",
    "mimetools", "rfc822", "popen2", "urllib", "string", "types",
})
STDLIB = frozenset(getattr(sys, "stdlib_module_names", ())) | PY2_STDLIB
DJANGO_MODEL = {"django.db.models.Model", "django.db.models.base.Model"}


class Project:
    def __init__(self, claims, own_packages):
        self.claims = claims
        self.by_path = {c.relative_path: c for c in claims}
        self.index: dict[str, list[str]] = defaultdict(list)
        for c in claims:
            for name in [c.namespace, *c.extras.get("module_aliases", [])]:
                if name:
                    self.index[name].append(c.relative_path)
        self.top_level = {n.split(".")[0] for n in self.index}
        self.units = {u.qualified_name: u for c in claims for u in c.units}
        self.own_packages = set(own_packages)

    # ------------------------------------------------------------------ modules
    def module(self, name: str) -> list[str]:
        return self.index.get(name, [])

    def module_or_suffix(self, name: str) -> tuple[str | None, str]:
        """Exact module, else a unique in-scan module ending in '.name' (marked ambiguous).
        Settings and include strings are written relative to the project folder that manage.py
        puts on sys.path, which the package chain does not know."""
        if self.module(name):
            return name, "exact"
        hits = [k for k in self.index if k.endswith("." + name)]
        if len(hits) == 1:
            return hits[0], "suffix_ambiguous"
        return None, "suffix_many" if hits else "none"

    def package_of(self, c) -> str | None:
        if not c.namespace:
            return None
        return c.namespace if c.extras.get("is_package") else (c.namespace.rsplit(".", 1)[0] if "." in c.namespace else "")

    def _sibling(self, c, first: str) -> bool:
        directory = c.relative_path.rsplit("/", 1)[0] if "/" in c.relative_path else ""
        prefix = f"{directory}/" if directory else ""
        return f"{prefix}{first}.py" in self.by_path or f"{prefix}{first}/__init__.py" in self.by_path

    def py2_relative_applies(self, c, first: str) -> bool:
        return (c.extras.get("dialect") == "python2" and not c.extras.get("absolute_import")
                and self.package_of(c) is not None and self._sibling(c, first))

    def absolute_base(self, c, mod: str) -> tuple[str | None, str]:
        """Turn a module reference written in file c into an absolute dotted name, and say which rule did it."""
        if mod.startswith("."):
            level = len(mod) - len(mod.lstrip("."))
            pkg = self.package_of(c)
            if pkg is None:
                return None, "relative_without_package"
            parts = pkg.split(".") if pkg else []
            if level - 1 > len(parts):
                return None, "relative_beyond_top"
            base = parts[: len(parts) - (level - 1)]
            rest = mod[level:]
            return ".".join(base + ([rest] if rest else [])), "relative"
        first = mod.split(".")[0]
        if first and self.py2_relative_applies(c, first):
            pkg = self.package_of(c)
            return (f"{pkg}.{mod}" if pkg else mod), "py2_sibling"
        return mod, "absolute"

    def external_state(self, name: str) -> str:
        first = name.split(".")[0]
        if first in STDLIB:
            return "external_stdlib"
        if first in self.top_level:
            return "unresolved_internal"
        if any(k.endswith("." + name) for k in self.index):
            return "ambiguous_suffix"
        return "external"

    def resolve_import(self, c, edge) -> dict:
        kind, target = edge.target_kind, edge.target
        if kind == "py_from_import":
            mod, _, name = target.partition("|")
            base, rule = self.absolute_base(c, mod)
            if base is None:
                return {"state": "unresolved_internal", "rule": rule}
            if name != "*" and base and self.module(f"{base}.{name}"):
                return {"state": "resolved", "rule": rule, "module": f"{base}.{name}"}
            if base and self.module(base):
                return {"state": "resolved", "rule": rule, "module": base, "member": name}
            return {"state": self.external_state(base) if rule == "absolute" else "unresolved_internal", "rule": rule,
                    "module": base}
        name = target.split(":")[0]
        base, rule = self.absolute_base(c, name)
        if base and self.module(base):
            return {"state": "resolved", "rule": rule, "module": base}
        if kind == "py_dynamic_literal" and base and "." in base and self.module(base.rsplit(".", 1)[0]):
            return {"state": "resolved", "rule": rule, "module": base.rsplit(".", 1)[0], "member": base.rsplit(".", 1)[1]}
        return {"state": self.external_state(base) if rule == "absolute" else "unresolved_internal", "rule": rule,
                "module": base}

    # ------------------------------------------------------------------ names (bases, views)
    def canonical(self, c, target: str, kind: str) -> tuple[str, str]:
        """A dotted name used in file c -> (absolute dotted name, rule)."""
        if kind == "py_local":
            return target, "local"
        if "|" in target:
            mod, _, rest = target.partition("|")
            base, rule = self.absolute_base(c, mod)
            return (f"{base}.{rest}" if base else rest), rule
        base, rule = self.absolute_base(c, target)
        return base or target, rule

    def find_symbol(self, dotted: str) -> dict:
        """Longest module prefix in the scan, then a class unit or a module-level function in it."""
        parts = dotted.split(".")
        for cut in range(len(parts), 0, -1):
            mod = ".".join(parts[:cut])
            paths = self.module(mod)
            if paths:
                rest = parts[cut:]
                if not rest:
                    return {"state": "module", "module": mod}
                if dotted in self.units:
                    return {"state": "class", "module": mod, "name": ".".join(rest)}
                fc = self.by_path[paths[0]]
                if len(rest) == 1 and rest[0] in fc.extras.get("functions", {}):
                    return {"state": "function", "module": mod, "name": rest[0]}
                return {"state": "module_only", "module": mod, "name": ".".join(rest)}
        first = parts[0]
        if first in STDLIB or first not in self.top_level:
            return {"state": "external"}
        return {"state": "unresolved_internal"}


def resolve(project_read: dict, own_packages: list[str]) -> dict:
    claims = project_read["claims"]
    P = Project(claims, own_packages)
    imports = []
    for c in claims:
        for e in c.edges:
            if e.relation == "import":
                r = P.resolve_import(c, e)
                r.update(path=c.relative_path, line=e.line, target=e.target, kind=e.target_kind)
                imports.append(r)

    # S2 oracle: decided from the package list and the directory listing, never from the resolver
    def oracle_inside(c, e) -> bool:
        mod = e.target.partition("|")[0] if e.target_kind == "py_from_import" else e.target.split(":")[0]
        if mod.startswith("."):
            return True
        first = mod.split(".")[0]
        if first in P.own_packages:
            return True
        return (c.extras.get("dialect") == "python2" and not c.extras.get("absolute_import")
                and "." in (c.namespace or "") and P._sibling(c, first))

    s2_rows = []
    for c in claims:
        for e in c.edges:
            if e.relation == "import" and e.target_kind in ("py_import", "py_from_import"):
                r = P.resolve_import(c, e)
                s2_rows.append((oracle_inside(c, e), r["state"], c.relative_path, e.line, e.target, r))
    inside = [row for row in s2_rows if row[0]]
    inside_resolved = [row for row in inside if row[1] == "resolved"]
    resolver_inside_oracle_outside = [row for row in s2_rows if not row[0] and row[1] == "resolved"]

    # inheritance and models
    bases = defaultdict(list)
    for c in claims:
        for e in c.edges:
            if e.relation == "inherit":
                dotted, rule = P.canonical(c, e.target, e.target_kind)
                bases[e.from_qualified_name].append(dotted)
    model_memo: dict[str, str] = {}

    def model_kind(q, seen=()):
        if q in model_memo:
            return model_memo[q]
        result = "no"
        for b in bases.get(q, []):
            if b in DJANGO_MODEL:
                result = "direct"
                break
            if b in P.units and b not in seen:
                k = model_kind(b, seen + (q,))
                if k in ("direct", "via_scan"):
                    result = "via_scan"
                    break
                if k == "via_external_base" and result == "no":
                    result = "via_external_base"
            elif b.rsplit(".", 1)[-1].endswith("Model") and result == "no" and b not in P.units:
                result = "via_external_base"
        model_memo[q] = result
        return result

    models = Counter(model_kind(q) for q in P.units)

    # URL lists, composition and views
    url_modules = {c.namespace: c for c in claims if c.extras.get("url_lists") and c.namespace}
    roots = sorted({c.extras["root_urlconf"] for c in claims if c.extras.get("root_urlconf")})
    composed, local_reasons, include_outcomes = [], {}, Counter()
    reached = set()

    def view_state(c, entry):
        tk = entry["target_kind"]
        if entry["target"] is None:
            return "dynamic"
        if tk == "view_string":
            return P.find_symbol(entry["target"])["state"]
        dotted, _ = P.canonical(c, entry["target"], tk.split(":")[-1])
        return P.find_symbol(dotted)["state"]

    def list_target(c, ref: str, ref_kind: str):
        """('module', 'var') for an included or concatenated URL list, or None."""
        if ref_kind == "local_list":
            mod, _, var = ref.partition(":")
            return mod, var
        dotted, _ = P.canonical(c, ref, ref_kind)
        if dotted in url_modules:
            return dotted, "urlpatterns"
        if "." in dotted and dotted.rsplit(".", 1)[0] in url_modules:
            mod, var = dotted.rsplit(".", 1)
            return mod, var
        return None

    def compose(mod, var, prefix, root, depth, chain):
        c = url_modules.get(mod)
        if c is None or depth > 12 or (mod, var) in chain:
            return
        reached.add(mod)
        for item in c.extras["url_lists"].get(var, []):
            if "ref" in item:
                tgt = list_target(c, item["ref"], item["ref_kind"]) if item["ref"] else None
                if tgt:
                    compose(tgt[0], tgt[1], prefix, root, depth + 1, chain + ((mod, var),))
                else:
                    include_outcomes["list_reference_not_resolved"] += 1
                continue
            if "pattern" not in item:
                continue
            joined = prefix.rstrip("$") + (item["pattern"][1:] if prefix and item["pattern"].startswith("^") else item["pattern"])
            if item.get("computed_pattern"):
                include_outcomes["computed_pattern"] += 1
            if item["kind"] == "route":
                composed.append({"root": root, "pattern": joined, "view": view_state(c, item),
                                 "source": f"{c.relative_path}:{item['line']}",
                                 "computed_prefix": "<computed>" in joined, "conditional": bool(item.get("conditional"))})
            else:
                if item["target"] is None:
                    include_outcomes["dynamic_include"] += 1
                    continue
                if item["target_kind"] == "module_string":
                    dotted, how = P.module_or_suffix(item["target"])
                    dotted = dotted or item["target"]
                    if how == "suffix_ambiguous":
                        include_outcomes["include_by_suffix_ambiguous"] += 1
                else:
                    dotted, _ = P.canonical(c, item["target"], item["target_kind"])
                if dotted in url_modules:
                    include_outcomes["static_include_followed"] += 1
                    compose(dotted, "urlpatterns", joined, root, depth + 1, chain + ((mod, var),))
                else:
                    tgt = list_target(c, item["target"], item["target_kind"]) if item["target_kind"] != "module_string" else None
                    if tgt:
                        include_outcomes["static_include_followed"] += 1
                        compose(tgt[0], tgt[1], joined, root, depth + 1, chain + ((mod, var),))
                    else:
                        include_outcomes["include_outside_scan_or_unresolved"] += 1

    root_links = {}
    for root in roots:
        mod, how = P.module_or_suffix(root)
        root_links[root] = how
        if mod in url_modules:
            compose(mod, "urlpatterns", "", root, 0, ())
    string_named = {s.split(":")[0] for c in claims for s, _ in c.extras.get("string_refs", [])}
    hooked = {c.namespace for c in claims if c.extras.get("url_dynamic_hooks")}
    local_routes = []
    for mod, c in sorted(url_modules.items()):
        routes = [i for lst in c.extras["url_lists"].values() for i in lst if i.get("kind") == "route"]
        if mod in reached or not routes:
            continue
        if mod in hooked:
            reason = "extended at run time by a signal"
        elif mod in string_named:
            reason = "named by a string (loaded at run time, e.g. a provides registry)"
        elif c.relative_path.endswith(("urls.py",)) or "/urls/" in c.relative_path:
            reason = "no static include chain from any ROOT_URLCONF found"
        else:
            reason = "URL list outside a urls module, never included"
        local_reasons[mod] = reason
        for i in routes:
            local_routes.append({"module": mod, "pattern": i["pattern"], "view": view_state(c, i), "reason": reason})
    per_module_counts = {mod: sum(1 for lst in c.extras["url_lists"].values() for i in lst if "pattern" in i)
                         for mod, c in url_modules.items()}

    # S6: by-name strings outside the recognised slots that name a module in the scan
    by_name = []
    for c in claims:
        for s, line in c.extras.get("string_refs", []):
            mod = s.split(":")[0]
            hit = P.module(mod) or ("." in mod and P.module(mod.rsplit(".", 1)[0]) and ":" not in s)
            if hit:
                by_name.append({"path": c.relative_path, "line": line, "value": s})

    entry_points = Counter(p.kind for c in claims for p in c.entry_points)
    shapes = Counter(p.detail.split(" ")[0] for c in claims for p in c.problems if p.reason_code == "unsupported_entry_point_shape")
    problems = Counter(p.reason_code for c in claims for p in c.problems)
    views = Counter(r["view"] for r in composed) + Counter(r["view"] for r in local_routes)
    return {
        "imports": imports,
        "import_states": Counter(r["state"] for r in imports),
        "import_rules": Counter(r["rule"] for r in imports if r["state"] == "resolved"),
        "s2": {"oracle_inside": len(inside), "oracle_inside_resolved": len(inside_resolved),
               "share": round(len(inside_resolved) / len(inside), 4) if inside else None,
               "oracle_inside_not_resolved": [r[2:5] + (r[5]["state"],) for r in inside if r[1] != "resolved"][:60],
               "resolver_inside_oracle_outside": [r[2:5] for r in resolver_inside_oracle_outside][:60],
               "resolver_inside_oracle_outside_count": len(resolver_inside_oracle_outside),
               "inside_resolved_rows": [r[2:5] + (r[5].get("module"), r[5].get("rule")) for r in inside_resolved]},
        "models": dict(models),
        "roots": roots,
        "root_links": root_links,
        "url_modules": len(url_modules),
        "url_module_entry_counts": per_module_counts,
        "composed_routes": composed,
        "local_routes": local_routes,
        "local_reasons": local_reasons,
        "include_outcomes": dict(include_outcomes),
        "views": dict(views),
        "entry_points": dict(entry_points),
        "unsupported_shapes": dict(shapes),
        "problems": dict(problems),
        "by_name": by_name,
    }
