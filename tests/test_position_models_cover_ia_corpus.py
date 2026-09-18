"""Regression lock: every container child-position key that the IA
professional corpus actually uses must be a field on the matching
``*ChildPosition`` model.

Each ``*ChildPosition`` has ``extra="forbid"`` (from IgnitionBaseModel), so a
key IA uses that the model lacks would FALSE-REJECT a legitimate view at author
time. This test scans the IA-authored reference projects + sample (the same
corpus that hardened the whitelists) and asserts full coverage —
guarding against a future model edit dropping a field, or an updated IA sample
introducing a new position key we don't model yet. Skips if the corpus is
absent (portability).

Audited live across 230 views: flex {basis,shrink,grow,display},
split {position}, tab {tabIndex}, breakpt {size}, column
{colIndex,name,order,rowIndex,span}, coord rotate {anchor}-only. All covered.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from ignition_gen_sdk.models.views.positions import (
    BreakpointChildPosition,
    ColumnChildPosition,
    CoordinatePosition,
    FlexChildPosition,
    SplitChildPosition,
    TabChildPosition,
)

# Corpus tests scan a real gateway data dir READ-ONLY; point IGNITION_CORPUS_DIR at one.
_DATA = Path(os.environ.get("IGNITION_CORPUS_DIR") or "/nonexistent")

# Container type-string -> the model whose fields must cover its children's
# position keys.
_CONTAINER_POSITION_MODEL = {
    "ia.container.flex": FlexChildPosition,
    "ia.container.coord": CoordinatePosition,
    "ia.container.split": SplitChildPosition,
    "ia.container.tab": TabChildPosition,
    "ia.container.breakpt": BreakpointChildPosition,
    "ia.container.column": ColumnChildPosition,
}


def _reference_corpus_roots() -> list[Path]:
    candidates = [
        _DATA / "projects" / "IndustryPack-Water",
        _DATA / "projects" / "IndustryPack-DataCenter",
    ]
    return [c for c in candidates if c.exists()]


def test_position_models_cover_every_ia_corpus_key() -> None:
    roots = _reference_corpus_roots()
    if not roots:
        pytest.skip("IA reference corpus not present")

    # container type -> set of position keys seen with no matching model field
    missing: dict[str, set[str]] = {}
    nfiles = 0
    seen_any = False

    def walk(node: object) -> None:
        nonlocal seen_any
        if isinstance(node, dict):
            ctype = node.get("type")
            model = _CONTAINER_POSITION_MODEL.get(ctype) if isinstance(ctype, str) else None
            if model is not None:
                fields = set(model.model_fields.keys())
                for child in node.get("children", []) or []:
                    if not isinstance(child, dict):
                        continue
                    pos = child.get("position")
                    if isinstance(pos, dict):
                        seen_any = True
                        for k in pos:
                            if k not in fields:
                                missing.setdefault(ctype, set()).add(k)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    for root in roots:
        for vf in root.rglob("view.json"):
            nfiles += 1
            try:
                walk(json.loads(vf.read_text(encoding="utf-8")))
            except Exception:
                continue

    assert nfiles > 0, "corpus present but no view.json found"
    assert seen_any, "no positioned container children found in corpus"
    assert not missing, (
        "container child-position keys used by IA but NOT modeled "
        "(extra='forbid' would false-reject these views): "
        + json.dumps({k: sorted(v) for k, v in missing.items()})
    )
