"""Offline validation of a UDT-instance tags/import body.

`ign tag build`/`tag --file` validate a PLAIN Tag and reject a UDT-instance
import body (`typeId`/`parameters`); `tag import --dry-run` previewed only the
envelope shape. So a fresh user authoring instances (the framework's primary
task) had no way to catch a missing or TYPO'd `typeId` offline (the likeliest
mistake). These helpers walk an import body and:
  - flag any UdtInstance with a missing/blank `typeId` (structural; always),
  - resolve each `typeId` against the UDT definitions on disk for the target
    provider and flag unknowns (typo / wrong provider) when the defs are
    locatable.

Read-only; no gateway call. typeId resolution degrades to structural-only when
the gateway data root / UDT defs can't be located (e.g. credential-less env).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _walk_type_defs(entries: Any, path: str, out: set[str]) -> None:
    """Collect typeIds from a udts.json entry list, recursing Folders.

    A UdtType named N at relative folder `path` has typeId `path/N` (or just
    `N` at the provider root). Folders extend the path.
    """
    if not isinstance(entries, list):
        return
    for e in entries:
        if not isinstance(e, dict):
            continue
        name = e.get("name")
        tag_type = e.get("tagType")
        if not name:
            continue
        if tag_type == "UdtType":
            out.add(f"{path}/{name}" if path else name)
        elif tag_type == "Folder":
            child = f"{path}/{name}" if path else name
            _walk_type_defs(e.get("tags"), child, out)


def collect_udt_typeids(data_root: Path, provider: str) -> set[str]:
    """All UDT typeIds defined on disk for `provider`, across config layers.

    Globs `config/resources/<layer>/ignition/tag-type-definition/<provider>/`.
    Returns an empty set if the tree is absent (→ callers skip resolution).
    """
    typeids: set[str] = set()
    cfg = data_root / "config" / "resources"
    if not cfg.is_dir():
        return typeids
    for layer in cfg.iterdir():
        base = layer / "ignition" / "tag-type-definition" / provider
        if not base.is_dir():
            continue
        for udts in base.rglob("udts.json"):
            rel = udts.parent.relative_to(base)
            relstr = "" if str(rel) == "." else str(rel).replace("\\", "/")
            try:
                data = json.loads(udts.read_text(encoding="utf-8"))
            except Exception:
                continue
            entries = data.get("tags") if isinstance(data, dict) else data
            _walk_type_defs(entries, relstr, typeids)
    return typeids


def validate_instance_body(
    body: dict | list, valid_typeids: set[str]
) -> tuple[int, set[str], list[str]]:
    """Walk an import body; return (instance_count, typeIds_used, issues).

    `issues` lists human-readable problems: a UdtInstance with no/blank typeId
    (always checked), and — only when `valid_typeids` is non-empty — a typeId
    not present among the on-disk UDT defs.
    """
    issues: list[str] = []
    types_used: set[str] = set()
    count = 0
    resolve = bool(valid_typeids)

    def walk(node: Any, where: str) -> None:
        nonlocal count
        if isinstance(node, dict):
            name = node.get("name") or "?"
            here = f"{where}/{name}" if name != "?" else where
            if node.get("tagType") == "UdtInstance":
                count += 1
                tid = node.get("typeId")
                if not isinstance(tid, str) or not tid.strip():
                    issues.append(f"{here or name}: UdtInstance missing/blank typeId")
                else:
                    types_used.add(tid)
                    if resolve and tid not in valid_typeids:
                        issues.append(
                            f"{here}: typeId {tid!r} not found among the provider's "
                            f"on-disk UDT defs (typo, or wrong --provider?)"
                        )
            for child in node.get("tags") or []:
                walk(child, here)
        elif isinstance(node, list):
            for c in node:
                walk(c, where)

    root = body.get("tags") if isinstance(body, dict) else body
    walk(root, "")
    return count, types_used, issues
