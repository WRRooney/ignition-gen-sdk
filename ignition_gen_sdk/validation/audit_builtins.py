"""Audit a gateway's project scripts and views against the Ignition 8.3 function sets.

Scans every project-library script (code.py), every view-embedded script
(onStartup / event handlers in view.json), and every view expression binding,
and reports any system.* call or expression function that does NOT exist in
8.3 (per _ia_8_3_builtins.py, produced by `ign builtins refresh`).

SCOPE: the crawl covers IA-core system.* + expression functions only. Module
namespaces (e.g. system.cirruslink.*) are real but not in the IA-core docs, so
pass --allow <subpackage> for each installed module namespace to avoid false
positives.

Run:  ign builtins audit [--project NAME ...] [--allow cirruslink]
Exit: 0 if clean, 1 if any unknown API found (CI-friendly).
"""
from __future__ import annotations

import glob
import json
import re
from pathlib import Path

from ignition_gen_sdk.validation._ia_8_3_builtins import (
    SYSTEM_FUNCTIONS_8_3,
    SYSTEM_SUBPACKAGES_8_3,
    EXPRESSION_FUNCTIONS_8_3,
)

_QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")
_SYS = re.compile(r"\bsystem\.([A-Za-z_]\w*)\.([A-Za-z_]\w*)")
_EXPRCALL = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_EXPR_LOWER = {e.lower() for e in EXPRESSION_FUNCTIONS_8_3}



def _bad_system(code: str, allow: frozenset[str] = frozenset()) -> set[str]:
    c = re.sub(r"#[^\n]*", "", _QUOTED.sub("", code))
    out = set()
    for pkg, leaf in _SYS.findall(c):
        if pkg in allow:
            continue
        full = "system.%s.%s" % (pkg, leaf)
        if pkg not in SYSTEM_SUBPACKAGES_8_3 or full not in SYSTEM_FUNCTIONS_8_3:
            out.add(full)
    return out


def _bad_expr(expr: str) -> set[str]:
    s = re.sub(r"\{[^}]*\}", "", _QUOTED.sub("", expr))
    return {fn for fn in _EXPRCALL.findall(s) if fn.lower() not in _EXPR_LOWER}


def audit(data_dir: Path, projects: list[str] | None = None, allow: frozenset[str] = frozenset()) -> dict:
    """Scan projects under ``data_dir/projects`` (all of them when ``projects`` is None)."""
    sys_hits: dict[str, set[str]] = {}
    expr_hits: dict[str, set[str]] = {}

    def add(d, key, where):
        d.setdefault(key, set()).add(where)

    roots = [data_dir / "projects" / p for p in projects] if projects else sorted(
        d for d in (data_dir / "projects").glob("*") if d.is_dir())
    for proj in roots:
        for sf in glob.glob(str(proj / "ignition/script-python/**/code.py"), recursive=True):
            where = proj.name + ":" + sf.split("/script-python/")[-1]
            for c in _bad_system(Path(sf).read_text(encoding="utf-8"), allow):
                add(sys_hits, c, where)

    for proj in roots:
        root = proj / "com.inductiveautomation.perspective/views"
        for vf in glob.glob(str(root / "**/view.json"), recursive=True):
            name = proj.name + ":" + vf.split("/views/")[-1].replace("/view.json", "")
            view = json.loads(Path(vf).read_text(encoding="utf-8"))

            def walk(o):
                if isinstance(o, dict):
                    s = o.get("script")
                    if isinstance(s, str):
                        for c in _bad_system(s, allow):
                            add(sys_hits, c, name + " (script)")
                    if o.get("type") == "expr" and isinstance(o.get("config"), dict):
                        e = o["config"].get("expression")
                        if isinstance(e, str):
                            for fn in _bad_expr(e):
                                add(expr_hits, fn, name)
                    for v in o.values():
                        walk(v)
                elif isinstance(o, list):
                    for x in o:
                        walk(x)

            walk(view)
    return {"system": sys_hits, "expression": expr_hits}


def main(data_dir: Path, projects: list[str] | None = None, allow: frozenset[str] = frozenset()) -> int:
    r = audit(data_dir, projects, allow)
    print("=== Unknown system.* calls (not in IA 8.3) ===")
    for k in sorted(r["system"]):
        print("  %-44s %s" % (k, sorted(r["system"][k])))
    print("=== Unknown expression functions (not in IA 8.3) ===")
    for k in sorted(r["expression"]):
        print("  %-22s %s" % (k, sorted(r["expression"][k])))
    n = len(r["system"]) + len(r["expression"])
    print("\n%d distinct unknown API(s)." % n)
    return 1 if n else 0

