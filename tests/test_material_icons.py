"""Tests for the Material-icon whitelist guard.

An ia.display.icon whose `material/<name>` is not in the gateway's bundled icon
set renders nothing and crashes the component at runtime (React.cloneElement
null) while passing model/JSON validation — found by runtime render
(material/water on the Pump symbol). ViewBuilder.icon() now rejects it at author
time, sourced from the gateway sprite (material.svg).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from ignition_gen_sdk.validation import MATERIAL_ICONS, unknown_material_icon

# Corpus tests scan a real gateway data dir READ-ONLY; point IGNITION_CORPUS_DIR at one.
_DATA = Path(os.environ.get("IGNITION_CORPUS_DIR") or "/nonexistent")


# --- the data set ---


def test_material_icon_set_is_substantial_and_known_members() -> None:
    assert len(MATERIAL_ICONS) > 1000  # classic ~1300-icon set
    assert "plumbing" in MATERIAL_ICONS and "speed" in MATERIAL_ICONS
    assert "water" not in MATERIAL_ICONS and "water_drop" not in MATERIAL_ICONS


# --- helper ---


def test_unknown_material_icon_helper() -> None:
    assert unknown_material_icon("material/water") == "water"
    assert unknown_material_icon("material/water_drop") == "water_drop"
    assert unknown_material_icon("material/plumbing") is None
    assert unknown_material_icon("material/speed") is None
    # non-material lib, empty, None, binding-ref all pass (return None)
    assert unknown_material_icon("custom/foo") is None
    assert unknown_material_icon("") is None
    assert unknown_material_icon(None) is None
    assert unknown_material_icon("{view.custom.navIcon}") is None


# --- factory guard ---


def test_viewbuilder_icon_rejects_invalid_material_icon() -> None:
    from ignition_gen_sdk.builders.view import ViewBuilder

    vb = ViewBuilder()
    with pytest.raises(ValueError):
        vb.icon(path="material/water")


def test_viewbuilder_icon_accepts_valid_and_nonmaterial() -> None:
    from ignition_gen_sdk.builders.view import ViewBuilder

    ViewBuilder().icon(path="material/plumbing")  # valid material
    ViewBuilder().icon(path="material/speed")
    ViewBuilder().icon(path="")                    # no icon
    ViewBuilder().icon(path="custom/whatever")     # non-material lib passes


# --- project sweep: every view icon in the data dir is a valid Material icon ---


def test_all_framework_icon_paths_are_valid() -> None:
    roots = [
        _DATA / "projects/Demo/com.inductiveautomation.perspective/views",
    ]
    bad = []
    for root in roots:
        if not root.exists():
            continue
        for vf in root.rglob("view.json"):
            view = json.loads(vf.read_text(encoding="utf-8"))

            def walk(o):
                if isinstance(o, dict):
                    if o.get("type") == "ia.display.icon":
                        p = (o.get("props") or {}).get("path")
                        miss = unknown_material_icon(p) if isinstance(p, str) else None
                        if miss is not None:
                            bad.append((str(vf.name), p))
                    for v in o.values():
                        walk(v)
                elif isinstance(o, list):
                    for x in o:
                        walk(x)

            walk(view)
    assert not bad, f"framework views use invalid Material icons: {bad}"
