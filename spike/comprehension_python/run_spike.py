"""Run the spike reader on one codebase and write the outputs (read-only on the codebase).

Use: PYTHONPATH=src;spike python -m comprehension_python.run_spike --root <codebase> --label <name>
     --own-packages <a,b,...> --out <dir>

SPIKE CODE - DO NOT MERGE.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
import time
from collections import Counter
from pathlib import Path

from . import project as project_mod
from . import resolve as resolve_mod
from .claims import to_json


def canonical_digest(claims) -> str:
    """Digest of every claim, leaving out only the field that records the interpreter (S1)."""
    rows = []
    for c in claims:
        data = to_json(c)
        data["extras"] = {k: v for k, v in data["extras"].items() if k != "interpreter"}
        rows.append(data)
    blob = json.dumps(rows, sort_keys=True, ensure_ascii=True).encode()
    return hashlib.sha256(blob).hexdigest()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--own-packages", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    root = Path(args.root)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    py = f"{sys.version_info[0]}.{sys.version_info[1]}"
    t_all = time.perf_counter()
    read = project_mod.read_project(root)
    t0 = time.perf_counter()
    res = resolve_mod.resolve(read, [p for p in args.own_packages.split(",") if p])
    read["timings"]["resolve_s"] = time.perf_counter() - t0
    read["timings"]["total_s"] = time.perf_counter() - t_all
    claims = read["claims"]
    full = [to_json(c) for c in claims]
    full_path = out / f"claims-{args.label}-py{py}.json"
    full_path.write_text(json.dumps(full, sort_keys=True), encoding="utf-8")

    readers = Counter(c.reader for c in claims)
    found = {
        "python_files": len(claims),
        "modules_named": sum(1 for c in claims if c.namespace),
        "packages": sum(1 for c in claims if c.extras.get("is_package") and c.namespace),
        "classes": sum(len(c.units) for c in claims),
        "module_level_functions": sum(len(c.extras.get("functions", {})) for c in claims),
        "local_classes_skipped": sum(c.extras.get("local_classes_skipped", 0) for c in claims),
        "test_files": sum(1 for c in claims if "test" == __import__("comprehension_python.py_reader", fromlist=["x"]).classify(c.relative_path)),
        "settings_modules": sum(1 for c in claims if c.extras.get("is_settings")),
        "root_urlconfs": res["roots"],
        "url_modules": res["url_modules"],
        "routes_composed": len(res["composed_routes"]),
        "routes_local_only": len(res["local_routes"]),
        "include_outcomes": res["include_outcomes"],
        "views": res["views"],
        "models": res["models"],
        "entry_points": res["entry_points"],
        "unsupported_shapes": res["unsupported_shapes"],
        "imports": dict(res["import_states"]),
        "import_rules_resolved": dict(res["import_rules"]),
        "problems": res["problems"],
    }
    s1 = {"readers": dict(readers), "fully_read_share": round((readers["python-ast"] + readers["python-ast-repaired"]) / len(claims), 4),
          "dialect": read["dialect"], "dialect_rule": read["dialect_rule"], "marker_counts": read["marker_counts"],
          "packaging": {k: read["evidence"][k] for k in ("dialect", "python_requires", "python_classifiers")},
          "repairs": dict(Counter(k for c in claims for p in c.problems if p.reason_code == "python2_repaired" for k in p.detail.split(","))),
          "token_outline_files": [c.relative_path for c in claims if c.reader == "python-tokens"],
          "unreadable_files": [c.relative_path for c in claims if c.reader == "unreadable"],
          "canonical_digest_without_interpreter": canonical_digest(claims)}
    s2 = {k: v for k, v in res["s2"].items() if k != "inside_resolved_rows"}
    rng = random.Random(495)  # noqa: S311 - a repeatable sample for hand checks, not a secret
    rows = res["s2"]["inside_resolved_rows"]
    s2_sample = rng.sample(rows, min(20, len(rows)))
    url_mods = sorted(m for m, n in res["url_module_entry_counts"].items() if n)
    s3_pick = rng.sample(url_mods, min(5, len(url_mods)))
    s3 = {"five_modules": {m: res["url_module_entry_counts"][m] for m in s3_pick},
          "local_only_reasons": dict(Counter(res["local_reasons"].values())),
          "composed_sample": rng.sample(res["composed_routes"], min(10, len(res["composed_routes"])))}
    by_name = res["by_name"]
    s6 = {"by_name_edges": len(by_name), "files": len({b["path"] for b in by_name}),
          "sample": rng.sample(by_name, min(20, len(by_name)))}
    s5 = {"timings_s": {k: round(v, 3) for k, v in read["timings"].items()},
          "full_claims_bytes": full_path.stat().st_size, "interpreter": py}
    summary = {"label": args.label, "interpreter": py, "S1": s1, "S2": s2, "S3": s3, "S5": s5, "S6": s6, "found": found}
    (out / f"summary-{args.label}-py{py}.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    (out / f"s2-sample-{args.label}-py{py}.json").write_text(json.dumps(s2_sample, indent=1), encoding="utf-8")
    (out / f"routes-{args.label}-py{py}.json").write_text(json.dumps(
        {"composed": res["composed_routes"], "local_only": res["local_routes"]}, indent=1), encoding="utf-8")
    print(json.dumps({"label": args.label, "py": py, "readers": dict(readers), "total_s": round(read["timings"]["total_s"], 2),
                      "s2_share": s2["share"], "digest": s1["canonical_digest_without_interpreter"][:16]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
