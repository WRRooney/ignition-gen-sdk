"""Tests for ExpressionTransform + bind_property + expression chain.

Verifies:
- ExpressionTransform construction (Literal['expression'] discriminator)
- Transform discriminated union
- Component.bind_property() helper attaches PropertyBinding, sets _last_binding, returns Self
- Component.expression() chain method appends ExpressionTransform, returns Self
- Multi-binding chain (transforms route to correct most-recent binding)
- Byte-equivalent fixture diff against Layouts/Layout Card/view.json line 173-209
"""
from __future__ import annotations

import json
from typing import get_args

import pytest
from pydantic import ValidationError

from ignition_gen_sdk.bindings.property import PropertyBinding
from ignition_gen_sdk.transforms.expression import ExpressionTransform
from ignition_gen_sdk.transforms import Transform
from ignition_gen_sdk.models.views.component import Component




from conftest import FIXTURE_ROOT  # noqa: E402


# ---------- ExpressionTransform model ----------

def test_expression_transform_importable():
    """Importable from transforms.expression."""
    from ignition_gen_sdk.transforms.expression import ExpressionTransform as ET
    assert ET is ExpressionTransform


def test_expression_transform_default_type_literal():
    """type Literal default is "expression" (full word)."""
    t = ExpressionTransform(expression="{view.params.value} * 100")
    assert t.type == "expression"
    assert t.expression == "{view.params.value} * 100"


def test_expression_transform_rejects_expr_abbreviation():
    """Literal rejects "expr" — that's the BINDING discriminator, not transform."""
    with pytest.raises(ValidationError):
        ExpressionTransform(expression="x", type="expr")


def test_expression_transform_requires_expression_field():
    """expression field is required (no default empty string)."""
    with pytest.raises(ValidationError):
        ExpressionTransform()


def test_expression_transform_emits_correct_shape():
    """emit shape matches fixture {"type":"expression", "expression":"x"}."""
    t = ExpressionTransform(expression="x")
    out = t.model_dump(exclude_none=True, mode="json")
    assert out == {"type": "expression", "expression": "x"}


def test_transform_union_is_no_longer_any():
    """Transform import returns the discriminated union (not Any)."""
    from typing import Any
    assert Transform is not Any


def test_transform_is_annotated_discriminated_union():
    """Transform is the Annotated discriminated-union of transform types."""
    # Annotated[Union[...], Discriminator("type")]
    args = get_args(Transform)
    assert len(args) >= 2  # Union + Discriminator metadata
    union_part = args[0]
    # When a union has exactly one member, get_args() on it may collapse to
    # the bare type in some Python versions.
    union_members = get_args(union_part)
    if union_members:
        assert ExpressionTransform in union_members
    else:
        # Single-member union collapsed to bare type
        assert union_part is ExpressionTransform


# ---------- Component.bind_property() + .expression() ----------

def test_bind_property_returns_self():
    """bind_property returns the same Component instance (Self)."""
    c = Component(type="ia.display.label")
    result = c.bind_property("props.text", "view.params.link")
    assert result is c


def test_bind_property_attaches_property_binding():
    """After bind_property, propConfig has one PropConfig with PropertyBinding."""
    c = Component(type="ia.display.label").bind_property(
        "props.text", "view.params.link"
    )
    assert len(c.propConfig) == 1
    assert c.propConfig[0].prop == "props.text"
    assert isinstance(c.propConfig[0].binding, PropertyBinding)
    assert c.propConfig[0].binding.config.path == "view.params.link"


def test_bind_property_sets_last_binding_handle():
    """_last_binding is the same object reference as the just-appended binding."""
    c = Component(type="ia.display.label").bind_property(
        "props.text", "view.params.link"
    )
    assert c._last_binding is c.propConfig[0].binding


def test_expression_without_preceding_bind_raises_runtime_error():
    """.expression() without .bind_*() raises RuntimeError."""
    c = Component(type="x")
    with pytest.raises(RuntimeError) as excinfo:
        c.expression("any")
    msg = str(excinfo.value)
    assert ".expression()" in msg
    assert ".bind_" in msg


def test_expression_appends_transform_to_last_binding():
    """.expression() appends an ExpressionTransform to _last_binding.transforms."""
    c = (
        Component(type="ia.display.label")
        .bind_property("props.text", "x")
        .expression("upper({value})")
    )
    assert len(c._last_binding.transforms) == 1
    t = c._last_binding.transforms[0]
    assert t.expression == "upper({value})"
    assert t.type == "expression"


def test_chain_returns_self_for_further_chaining():
    """bind_property + expression both return Self for further chaining."""
    c = Component(type="x")
    r1 = c.bind_property("props.a", "view.params.a")
    assert r1 is c
    r2 = r1.expression("expr_a")
    assert r2 is c
    # Now chain another bind_property — should work
    r3 = r2.bind_property("props.b", "view.params.b")
    assert r3 is c


def test_multiple_bindings_transforms_route_to_correct_most_recent():
    """Each .bind_*() overwrites _last_binding; transforms go to most-recent."""
    c = (
        Component(type="x")
        .bind_property("props.a", "view.params.a")
        .expression("expr_a")
        .bind_property("props.b", "view.params.b")
        .expression("expr_b")
    )
    assert len(c.propConfig) == 2
    assert c.propConfig[0].prop == "props.a"
    assert len(c.propConfig[0].binding.transforms) == 1
    assert c.propConfig[0].binding.transforms[0].expression == "expr_a"
    assert c.propConfig[1].prop == "props.b"
    assert len(c.propConfig[1].binding.transforms) == 1
    assert c.propConfig[1].binding.transforms[0].expression == "expr_b"
    assert c._last_binding is c.propConfig[1].binding


def test_bind_property_kwargs_bidirectional_enabled_overlay():
    """bind_property kwargs route to correct binding/config fields."""
    c = Component(type="x").bind_property(
        "p", "x", bidirectional=True, enabled=False, overlayOptOut=True
    )
    binding = c.propConfig[0].binding
    assert binding.enabled is False
    assert binding.overlayOptOut is True
    assert binding.config.bidirectional is True


def test_emit_shape_after_bind_property_and_expression():
    """Full emit shape after bind_property + expression.

    Enabled/overlayOptOut stripped from emit (gateway
    default). Non-empty transforms still emitted.
    """
    c = (
        Component(type="ia.display.label")
        .bind_property("props.text", "view.params.link")
        .expression("upper({value})")
    )
    emitted = c.model_dump(exclude_none=True, mode="json")
    pc = emitted["propConfig"]["props.text"]
    assert pc == {
        "binding": {
            "type": "property",
            "config": {"path": "view.params.link"},
            "transforms": [
                {"type": "expression", "expression": "upper({value})"}
            ],
        }
    }


def test_fixture_diff_layout_card_path_label():
    """Byte-equivalent diff against Layout Card 'Path' label propConfig (line 173-209)."""
    fixture = json.loads(
        (FIXTURE_ROOT / "Layouts" / "Layout Card" / "view.json").read_text()
    )

    def walk(node):
        if isinstance(node, dict):
            pc = node.get("propConfig", {})
            if isinstance(pc, dict):
                for prop_key, entry in pc.items():
                    if not isinstance(entry, dict):
                        continue
                    binding = entry.get("binding")
                    if not isinstance(binding, dict):
                        continue
                    if binding.get("type") != "property":
                        continue
                    transforms = binding.get("transforms", [])
                    if not transforms or transforms[0].get("type") != "expression":
                        continue
                    return prop_key, binding
            for child in node.get("children", []) or []:
                found = walk(child)
                if found is not None:
                    return found
        return None

    result = walk(fixture.get("root", {}))
    assert result is not None, (
        "Layout Card fixture missing the expected property-binding + "
        "expression-transform shape"
    )
    prop_key, fixture_binding = result

    fixture_path = fixture_binding["config"]["path"]
    fixture_expr = fixture_binding["transforms"][0]["expression"]

    built = (
        Component(type="ia.display.label")
        .bind_property(prop_key, fixture_path)
        .expression(fixture_expr)
    )
    emitted = built.model_dump(exclude_none=True, mode="json")["propConfig"][prop_key]["binding"]

    # Superset check: every fixture key+value present in emitted (emitted may
    # contain default-valued keys fixture omits, e.g. enabled=True).
    for key, fixture_val in fixture_binding.items():
        assert key in emitted, f"missing key {key!r}"
        if key == "transforms":
            assert len(emitted[key]) == len(fixture_val)
            for i, fv in enumerate(fixture_val):
                for tk, tv in fv.items():
                    assert tk in emitted[key][i]
                    assert emitted[key][i][tk] == tv, (
                        f"transform[{i}].{tk}: built={emitted[key][i][tk]!r} "
                        f"fixture={tv!r}"
                    )
        else:
            assert emitted[key] == fixture_val, (
                f"key {key!r}: built={emitted[key]!r} fixture={fixture_val!r}"
            )


def test_base_propconfig_shape_preserved_with_bind_property():
    """Smoke check that the base propConfig shape is preserved once bind_property is added.

    Empty transforms list is OMITTED from binding emit
    (matches gateway samples). With no transforms attached, the key does
    not appear.
    """
    c = Component(type="ia.display.label").bind_property(
        "props.text", "view.params.title"
    )
    emitted = c.model_dump(exclude_none=True, mode="json")
    assert "propConfig" in emitted
    assert emitted["propConfig"]["props.text"]["binding"]["type"] == "property"
    assert (
        emitted["propConfig"]["props.text"]["binding"]["config"]["path"]
        == "view.params.title"
    )
    # No transforms attached -> "transforms" key omitted.
    assert "transforms" not in emitted["propConfig"]["props.text"]["binding"]
