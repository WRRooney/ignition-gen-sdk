"""Tests for ExpressionBinding + ExpressionStructureBinding.

Verifies:
- ExpressionBinding (Literal["expr"]) + ExpressionBindingConfig (required expression)
- ExpressionStructureBinding (Literal["expr-struct"]) + ExpressionStructureBindingConfig
  (struct: dict[str, Any] default-factory; waitOnAll: bool = True)
- Binding discriminated union expanded from 2 to 4 members
- Component.bind_expression() + Component.bind_expression_structure() chain helpers
- Fixture diffs against samplequickstart:
    * Framework/Widgets/Gauge/view.json line 90-98 (props.animate, "type": "expr")
    * Ignition 101/Feature Views/Perspective Features/Bindings/view.json line 533-544
      (props.arc, "type": "expr-struct")
- Discriminator distinction regression test: binding "expr" vs transform "expression"
  vs binding "expr-struct" — three distinct Literal values, three different classes.
"""
from __future__ import annotations

import json
from typing import get_args

import pytest
from pydantic import TypeAdapter, ValidationError

from ignition_gen_sdk.bindings import Binding
from ignition_gen_sdk.bindings.expression import ExpressionBinding, ExpressionBindingConfig
from ignition_gen_sdk.bindings.expression_structure import (
    ExpressionStructureBinding,
    ExpressionStructureBindingConfig,
)
from ignition_gen_sdk.bindings.property import PropertyBinding
from ignition_gen_sdk.bindings.tag import TagBinding
from ignition_gen_sdk.transforms import Transform
from ignition_gen_sdk.transforms.expression import ExpressionTransform
from ignition_gen_sdk.transforms.format import FormatTransform
from ignition_gen_sdk.models.views.component import Component




from conftest import FIXTURE_ROOT  # noqa: E402


# ============================================================
# ExpressionBinding + ExpressionStructureBinding models
# ============================================================


# ----- ExpressionBindingConfig + ExpressionBinding -----


def test_expression_binding_config_constructs():
    """ExpressionBindingConfig with required expression field constructs."""
    cfg = ExpressionBindingConfig(expression="toBoolean({view.params.animate})")
    assert cfg.expression == "toBoolean({view.params.animate})"


def test_expression_binding_config_requires_expression():
    """ExpressionBindingConfig() raises ValidationError (expression required, no default)."""
    with pytest.raises(ValidationError):
        ExpressionBindingConfig()  # type: ignore[call-arg]


def test_expression_binding_type_discriminator_default():
    """ExpressionBinding default type discriminator is "expr" (abbreviated)."""
    eb = ExpressionBinding(config=ExpressionBindingConfig(expression="x"))
    assert eb.type == "expr"


def test_expression_binding_rejects_full_word_discriminator():
    """ExpressionBinding(type="expression") rejected — Literal["expr"] only."""
    with pytest.raises(ValidationError):
        ExpressionBinding(
            type="expression",  # full word is for the TRANSFORM, not the binding
            config=ExpressionBindingConfig(expression="x"),
        )


# ----- ExpressionStructureBindingConfig + ExpressionStructureBinding -----


def test_expression_structure_binding_config_constructs_with_defaults():
    """ExpressionStructureBindingConfig() — struct=={}, waitOnAll==True."""
    cfg = ExpressionStructureBindingConfig()
    assert cfg.struct == {}
    assert cfg.waitOnAll is True


def test_expression_structure_binding_config_accepts_struct():
    """ExpressionStructureBindingConfig with full struct dict."""
    cfg = ExpressionStructureBindingConfig(
        struct={
            "color": '"#CCCCFF"',
            "width": "{../Slider.props.value}",
        }
    )
    assert cfg.struct == {
        "color": '"#CCCCFF"',
        "width": "{../Slider.props.value}",
    }
    assert cfg.waitOnAll is True


def test_expression_structure_binding_type_discriminator_default():
    """ExpressionStructureBinding default type is "expr-struct" (with hyphen)."""
    esb = ExpressionStructureBinding(config=ExpressionStructureBindingConfig())
    assert esb.type == "expr-struct"


def test_expression_structure_binding_rejects_other_discriminators():
    """ExpressionStructureBinding(type="expr") rejected — Literal["expr-struct"]."""
    with pytest.raises(ValidationError):
        ExpressionStructureBinding(
            type="expr",
            config=ExpressionStructureBindingConfig(),
        )


# ----- Discriminator distinction (the critical lock) -----


def test_discriminator_distinction_three_distinct_values():
    """ExpressionBinding "expr" vs ExpressionTransform "expression" vs
    ExpressionStructureBinding "expr-struct" — three distinct Literal defaults, three classes."""
    assert ExpressionBinding.model_fields["type"].default == "expr"
    assert ExpressionTransform.model_fields["type"].default == "expression"
    assert ExpressionStructureBinding.model_fields["type"].default == "expr-struct"
    # And the classes themselves are distinct
    assert ExpressionBinding is not ExpressionTransform
    assert ExpressionBinding is not ExpressionStructureBinding
    assert ExpressionTransform is not ExpressionStructureBinding


def test_binding_union_has_four_members():
    """Binding union has AT LEAST 4 members (Property + Tag + Expression +
    ExprStruct).

    Hard-coding the exact count is a regression every time a new binding
    type is added. The invariant is "these four are members"; the size
    grows as Query/TagHistory/Http land.
    """
    members = get_args(get_args(Binding)[0])
    assert len(members) >= 4
    assert PropertyBinding in members
    assert TagBinding in members
    assert ExpressionBinding in members
    assert ExpressionStructureBinding in members


def test_binding_union_round_trip_dispatches_to_expression_binding():
    """TypeAdapter(Binding).validate_python({"type":"expr",...}) -> ExpressionBinding.

    Critical: dispatches to ExpressionBinding (binding union) — not ExpressionTransform
    (transform union; that's a separate union).
    """
    adapter = TypeAdapter(Binding)
    eb = adapter.validate_python(
        {"type": "expr", "config": {"expression": "x"}}
    )
    assert isinstance(eb, ExpressionBinding)
    esb = adapter.validate_python(
        {"type": "expr-struct", "config": {"struct": {}, "waitOnAll": True}}
    )
    assert isinstance(esb, ExpressionStructureBinding)


def test_expression_binding_full_emit_shape():
    """ExpressionBinding emit shape.

    Gateway samples (Bindings/view.json:90-98) emit
    only {config, type}; enabled/overlayOptOut/empty transforms are
    stripped to match.
    """
    eb = ExpressionBinding(
        config=ExpressionBindingConfig(expression="toBoolean({view.params.animate})")
    )
    out = eb.model_dump(exclude_none=True, mode="json")
    assert out == {
        "type": "expr",
        "config": {"expression": "toBoolean({view.params.animate})"},
    }


def test_expression_structure_binding_full_emit_shape():
    """ExpressionStructureBinding emit shape.

    Enabled/overlayOptOut/empty transforms stripped.
    Fixture (Bindings/view.json:533-544) emits only {config, type}.
    """
    esb = ExpressionStructureBinding(
        config=ExpressionStructureBindingConfig(
            struct={"color": '"#CCCCFF"', "width": "{x}"},
        )
    )
    out = esb.model_dump(exclude_none=True, mode="json")
    assert out["type"] == "expr-struct"
    assert out["config"] == {
        "struct": {"color": '"#CCCCFF"', "width": "{x}"},
        "waitOnAll": True,
    }
    # These keys must NOT appear in emit (gateway default values).
    assert "enabled" not in out
    assert "overlayOptOut" not in out
    assert "transforms" not in out


# ============================================================
# Component.bind_expression() + bind_expression_structure() helpers
# ============================================================


def test_bind_expression_returns_self():
    """bind_expression returns the Component (chainable)."""
    c = Component(type="ia.display.label")
    result = c.bind_expression("props.animate", "toBoolean({x})")
    assert result is c
    assert len(c.propConfig) == 1
    assert c.propConfig[0].binding.type == "expr"


def test_bind_expression_with_flags():
    """bind_expression with enabled=False, overlayOptOut=True propagates to emit.

    Uses a dynamic expression ("toBoolean({x})") rather than a static
    literal, since static strings with no `{` or `(` now raise
    StaticBindingError and would fail construction before the flags could
    be exercised.
    """
    c = Component(type="ia.display.label").bind_expression(
        "props.animate", "toBoolean({x})", enabled=False, overlayOptOut=True,
    )
    emit = c.propConfig[0].binding.model_dump(exclude_none=True, mode="json")
    assert emit["enabled"] is False
    assert emit["overlayOptOut"] is True
    assert emit["type"] == "expr"


def test_bind_expression_chains_format_transform():
    """bind_expression -> .format(...) attaches FormatTransform to that binding's transforms."""
    c = (
        Component(type="ia.display.label")
        .bind_expression("props.value", "100 * {x}")
        .format("0.00")
    )
    transforms = c.propConfig[0].binding.transforms
    assert len(transforms) == 1
    assert isinstance(transforms[0], FormatTransform)
    assert transforms[0].formatValue == "0.00"


def test_bind_expression_structure_returns_self():
    """bind_expression_structure returns the Component; propConfig has one entry."""
    c = Component(type="ia.display.label")
    result = c.bind_expression_structure(
        "props.arc",
        struct={"color": '"#CCCCFF"', "width": "{../Slider.props.value}"},
    )
    assert result is c
    assert len(c.propConfig) == 1
    assert c.propConfig[0].binding.type == "expr-struct"


def test_bind_expression_structure_with_waitonall_false():
    """bind_expression_structure with waitOnAll=False propagates on emit."""
    c = Component(type="x").bind_expression_structure(
        "props.arc",
        struct={"color": '"#FF0000"'},
        waitOnAll=False,
    )
    emit = c.propConfig[0].binding.model_dump(exclude_none=True, mode="json")
    assert emit["config"]["waitOnAll"] is False


def test_bind_expression_structure_empty_struct_default():
    """bind_expression_structure("p") with no struct kwarg -> struct={}."""
    c = Component(type="x").bind_expression_structure("props.arc")
    assert c.propConfig[0].binding.config.struct == {}
    assert c.propConfig[0].binding.config.waitOnAll is True


# ----- Fixture diffs -----


def _load_view(view_relpath: str) -> dict:
    p = FIXTURE_ROOT / view_relpath
    with p.open("r") as fp:
        return json.load(fp)


def _walk_find_propconfig_by_type(node, target_type, accum=None):
    """Walk a view tree; collect (prop_path, binding_dict) for bindings whose
    `binding.type == target_type`."""
    if accum is None:
        accum = []
    if isinstance(node, dict):
        pc = node.get("propConfig")
        if isinstance(pc, dict):
            for prop, body in pc.items():
                binding = (body or {}).get("binding")
                if isinstance(binding, dict) and binding.get("type") == target_type:
                    accum.append((prop, binding))
        for v in node.values():
            _walk_find_propconfig_by_type(v, target_type, accum)
    elif isinstance(node, list):
        for v in node:
            _walk_find_propconfig_by_type(v, target_type, accum)
    return accum


def _is_superset(superset: dict, subset: dict, path: str = "") -> None:
    """Assert every key+value in `subset` is present in `superset` with same value.
    Nested dicts compared recursively."""
    for k, v in subset.items():
        ctx = f"{path}/{k}"
        assert k in superset, f"missing key {ctx} in superset: {superset}"
        if isinstance(v, dict):
            assert isinstance(superset[k], dict), f"{ctx}: expected dict, got {type(superset[k])}"
            _is_superset(superset[k], v, ctx)
        else:
            assert superset[k] == v, f"{ctx}: {superset[k]!r} != {v!r}"


def test_fixture_diff_expression_binding_gauge_animate():
    """Fixture-diff against Framework/Widgets/Gauge/view.json line 90-98.

    The props.animate binding has shape:
        {"config": {"expression": "toBoolean({view.params.animate})"}, "type": "expr"}
    Rebuild it via Component(type="x").bind_expression(prop_path, expression).
    Emitted shape must SUPERSET match the fixture (extra fields like enabled,
    overlayOptOut, transforms are allowed on the rebuild side).
    """
    view = _load_view("Framework/Widgets/Gauge/view.json")
    found = _walk_find_propconfig_by_type(view, "expr")
    assert found, "no expr binding found in Gauge/view.json"

    # Target the props.animate entry specifically (line 90-98 of fixture).
    target = next(((p, b) for (p, b) in found if p == "props.animate"), None)
    assert target is not None, f"props.animate expr binding not in {found}"
    prop_path, fixture_binding = target
    fixture_expr = fixture_binding["config"]["expression"]

    rebuilt = Component(type="ia.display.gauge").bind_expression(prop_path, fixture_expr)
    emitted = rebuilt.model_dump(exclude_none=True, mode="json")["propConfig"][prop_path][
        "binding"
    ]
    _is_superset(emitted, fixture_binding)


def test_fixture_diff_expression_structure_binding_bindings_view():
    """Fixture-diff against Bindings/view.json line 533-544.

    The props.arc binding has shape:
        {"config": {"struct": {"color": "\"#CCCCFF\"", "cornerRadius": 0,
                               "width": "{../Slider.props.value}"},
                    "waitOnAll": true}, "type": "expr-struct"}
    Rebuild via Component.bind_expression_structure(prop, struct=..., waitOnAll=...)
    and SUPERSET match.
    """
    view = _load_view(
        "Ignition 101/Feature Views/Perspective Features/Bindings/view.json"
    )
    found = _walk_find_propconfig_by_type(view, "expr-struct")
    assert found, "no expr-struct binding found in Bindings/view.json"

    target = next(((p, b) for (p, b) in found if p == "props.arc"), None)
    assert target is not None, f"props.arc expr-struct binding not in {found}"
    prop_path, fixture_binding = target
    fixture_struct = fixture_binding["config"]["struct"]
    fixture_wait = fixture_binding["config"]["waitOnAll"]

    rebuilt = Component(type="ia.display.gauge").bind_expression_structure(
        prop_path, struct=fixture_struct, waitOnAll=fixture_wait,
    )
    emitted = rebuilt.model_dump(exclude_none=True, mode="json")["propConfig"][prop_path][
        "binding"
    ]
    _is_superset(emitted, fixture_binding)


# ----- Discriminator distinction regression -----


def test_binding_type_expr_distinct_from_transform_type_expression():
    """Discriminator distinction (binding 'expr' vs transform 'expression').

    REGRESSION TEST: the key correction is that
    the BINDING discriminator is "expr" (abbreviated) while the TRANSFORM
    discriminator is "expression" (full word). They live in DIFFERENT unions
    (Binding vs Transform). Each is rejected by the other's union.
    """
    binding_adapter = TypeAdapter(Binding)
    transform_adapter = TypeAdapter(Transform)

    # Binding-shaped expr dispatches to ExpressionBinding
    eb = binding_adapter.validate_python({"type": "expr", "config": {"expression": "x"}})
    assert isinstance(eb, ExpressionBinding)

    # Transform-shaped expression dispatches to ExpressionTransform
    et = transform_adapter.validate_python({"type": "expression", "expression": "x"})
    assert isinstance(et, ExpressionTransform)

    # Binding-shaped with TRANSFORM discriminator value FAILS (no member with type="expression")
    with pytest.raises(ValidationError):
        binding_adapter.validate_python(
            {"type": "expression", "config": {"expression": "x"}}
        )

    # Transform-shaped with BINDING discriminator value FAILS (no member with type="expr")
    with pytest.raises(ValidationError):
        transform_adapter.validate_python({"type": "expr", "expression": "x"})


def test_regression_smoke_property_and_tag_bindings():
    """Regression smoke: Property + Tag binding chains still functional.

    Property + Tag binding still construct; .expression() / .map() / .format() / .script()
    chains still attach to the right binding's transforms list.
    """
    from ignition_gen_sdk.bindings.enums import TagBindingMode

    c = (
        Component(type="ia.display.label")
        .bind_property("props.a", "view.params.a")
        .expression("upper({value})")
        .bind_tag("props.b", "[default]X", mode=TagBindingMode.DIRECT)
        .map({"a": "A"})
        .format("0.0")
        .script("return value")
    )
    # Property binding has 1 transform
    assert len(c.propConfig[0].binding.transforms) == 1
    assert c.propConfig[0].binding.type == "property"
    # Tag binding has 3 transforms
    assert len(c.propConfig[1].binding.transforms) == 3
    assert c.propConfig[1].binding.type == "tag"
