"""Tests for the generic Component model."""
from __future__ import annotations

import pytest

from ignition_gen_sdk.models.views.component import Component


def test_component_minimum_construction():
    c = Component(type="ia.display.label")
    out = c.emit()
    assert out["type"] == "ia.display.label"
    # Default Meta is included; props/children/etc are empty dicts/lists
    assert "meta" in out


def test_component_props_passthrough():
    c = Component(type="ia.display.label", props={"text": "hi"})
    assert c.emit()["props"] == {"text": "hi"}


def test_component_props_can_contain_tag_key_pitfall_6():
    """Credential guard inspects only TOP-LEVEL Pydantic fields, NOT nested dict keys.
    ``props={"tag": "Foo"}`` must construct cleanly (a known pitfall).
    """
    c = Component(type="ia.display.label", props={"tag": "Foo"})
    assert c.emit()["props"]["tag"] == "Foo"


def test_component_extra_field_forbidden():
    """extra='forbid' inherited from IgnitionBaseModel rejects unknown component-level fields."""
    import pydantic
    with pytest.raises(pydantic.ValidationError):
        Component(type="ia.display.label", garbage="x")  # type: ignore[call-arg]


def test_component_recursive_children():
    """Component.children is recursive list[Component] — model_rebuild applied."""
    parent = Component(type="ia.container.flex", children=[
        Component(type="ia.display.label"),
        Component(type="ia.display.label"),
    ])
    assert len(parent.children) == 2
    assert parent.children[0].type == "ia.display.label"


# ---- Regression: empty collections must be omitted ----

def test_component_emit_omits_empty_collections():
    """Leaf components must not emit empty children/custom/events/scripts.
    Every samplequickstart leaf component is shaped {meta, position, props,
    type} only. ign previously emitted children:[], custom:{}, events:{},
    scripts:{} unconditionally because those fields are non-Optional
    default-factory collections that exclude_none cannot strip.
    """
    out = Component(type="ia.display.label").emit()
    assert "children" not in out, f"emit still includes empty children: {out}"
    assert "custom" not in out, f"emit still includes empty custom: {out}"
    assert "events" not in out, f"emit still includes empty events: {out}"
    assert "scripts" not in out, f"emit still includes empty scripts: {out}"


def test_component_emit_keeps_nonempty_children():
    """Non-empty children list must still appear in emit (suppression
    is only for empty collections)."""
    parent = Component(type="ia.container.flex", children=[
        Component(type="ia.display.label"),
    ])
    out = parent.emit()
    assert "children" in out
    assert len(out["children"]) == 1
    assert out["children"][0]["type"] == "ia.display.label"


def test_component_emit_keeps_nonempty_custom():
    """Non-empty custom dict must still appear in emit."""
    c = Component(type="ia.display.label", custom={"foo": "bar"})
    out = c.emit()
    assert out.get("custom") == {"foo": "bar"}
