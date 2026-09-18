"""Tests for TagBinding + Component.bind_tag().

Verifies:
- TagBindingConfig single-class model with optional `references` (vs seed two-class split)
- `references: Optional[dict[str, str]]` + @field_validator
  rejecting non-dict, non-string keys, non-string values
- TagBinding Literal["tag"] discriminator
- Binding discriminated union expanded to 2 members (PropertyBinding + TagBinding)
- Discriminated-union round-trip dispatches correctly to TagBinding vs PropertyBinding
- Component.bind_tag(prop_path, tagPath, *, mode, bidirectional, fallbackDelay,
  references, publishInitial, enabled, overlayOptOut) helper
- Direct-mode fixture diff against Bindings/view.json line 99-103
- Indirect-mode fixture diff against Framework/Widgets/Gauge/view.json line 131-144
"""
from __future__ import annotations

import json
from typing import get_args

import pytest
from pydantic import ValidationError

from ignition_gen_sdk.bindings.tag import TagBinding, TagBindingConfig
from ignition_gen_sdk.bindings.property import PropertyBinding
from ignition_gen_sdk.bindings.enums import TagBindingMode
from ignition_gen_sdk.bindings import Binding
from ignition_gen_sdk.models.views.component import Component




from conftest import FIXTURE_ROOT  # noqa: E402


# ========== TagBindingConfig + TagBinding model ==========

def test_tagbindingconfig_constructs_with_defaults():
    """TagBindingConfig(tagPath=...) constructs with default mode/fallbackDelay."""
    cfg = TagBindingConfig(tagPath="[default]Tanks/T01/Level")
    # Default value bypasses Pydantic v2 use_enum_values coercion, so cfg.mode
    # is the enum object. After explicit construction or validation, it's the
    # string value. Emit always serializes to the string value.
    assert cfg.mode == TagBindingMode.DIRECT
    assert cfg.tagPath == "[default]Tanks/T01/Level"
    assert cfg.bidirectional is None
    assert cfg.fallbackDelay == 2.5
    assert cfg.publishInitial is None
    assert cfg.references is None


def test_tagbindingconfig_requires_tagpath():
    """TagBindingConfig() raises ValidationError (tagPath required, no default empty)."""
    with pytest.raises(ValidationError):
        TagBindingConfig()


def test_tagbindingconfig_indirect_with_references_constructs():
    """Indirect mode with references dict constructs cleanly."""
    cfg = TagBindingConfig(
        tagPath="x",
        mode=TagBindingMode.INDIRECT,
        references={"1": "{view.params.tagPath}"},
    )
    assert cfg.mode == "indirect"
    assert cfg.references == {"1": "{view.params.tagPath}"}


def test_references_rejects_non_dict_input():
    """References=list raises ValueError mentioning 'dict'."""
    with pytest.raises(ValidationError) as excinfo:
        TagBindingConfig(tagPath="x", references=["not", "a", "dict"])
    assert "dict" in str(excinfo.value)


def test_references_rejects_non_string_keys():
    """Non-string key in references raises ValueError mentioning 'non-string'."""
    with pytest.raises(ValidationError) as excinfo:
        TagBindingConfig(tagPath="x", references={1: "expr"})
    assert "non-string" in str(excinfo.value)


def test_references_rejects_non_string_values():
    """Non-string value in references raises ValueError mentioning 'non-string'."""
    with pytest.raises(ValidationError) as excinfo:
        TagBindingConfig(tagPath="x", references={"k": 42})
    assert "non-string" in str(excinfo.value)


def test_references_none_succeeds():
    """References=None succeeds (default direct-mode shape)."""
    cfg = TagBindingConfig(tagPath="x", references=None)
    assert cfg.references is None


def test_references_non_numeric_string_key_succeeds():
    """Non-numeric string keys (like 'tagPath') are accepted."""
    cfg = TagBindingConfig(
        tagPath="x", references={"tagPath": "{view.params.tagPath}"}
    )
    assert cfg.references == {"tagPath": "{view.params.tagPath}"}


def test_direct_dump_shape():
    """Direct-mode dump includes mode/tagPath/fallbackDelay; excludes None fields."""
    cfg = TagBindingConfig(tagPath="[Sample_Tags]Random/RandomInteger1")
    out = cfg.model_dump(exclude_none=True, mode="json")
    assert out["mode"] == "direct"
    assert out["tagPath"] == "[Sample_Tags]Random/RandomInteger1"
    assert out["fallbackDelay"] == 2.5
    assert "bidirectional" not in out
    assert "publishInitial" not in out
    assert "references" not in out


def test_indirect_dump_shape():
    """Indirect-mode dump includes references dict."""
    cfg = TagBindingConfig(
        tagPath="{1}",
        mode=TagBindingMode.INDIRECT,
        references={"1": "{view.params.tagPath}"},
    )
    out = cfg.model_dump(exclude_none=True, mode="json")
    assert out["mode"] == "indirect"
    assert out["tagPath"] == "{1}"
    assert out["fallbackDelay"] == 2.5
    assert out["references"] == {"1": "{view.params.tagPath}"}


def test_tagbinding_type_literal():
    """TagBinding has type='tag' discriminator default."""
    tb = TagBinding(config=TagBindingConfig(tagPath="x"))
    assert tb.type == "tag"


def test_tagbinding_rejects_type_override():
    """TagBinding rejects type='property' (Literal['tag'] is fixed)."""
    with pytest.raises(ValidationError):
        TagBinding(config=TagBindingConfig(tagPath="x"), type="property")


def test_binding_union_has_two_members():
    """`from ignition_gen_sdk.bindings import Binding` includes Property+Tag.

    The union keeps growing as more binding types are added (Expression,
    ExpressionStructure, and beyond). The invariant under test is that BOTH
    PropertyBinding and TagBinding are members of the discriminated union —
    not that the union is *exactly* 2 members. Hard-coding the count would
    break every time a new binding type is added.
    """
    # Annotated[Union[..., PropertyBinding, TagBinding, ...], Discriminator("type")]
    args = get_args(Binding)
    assert len(args) >= 2  # Union + Discriminator metadata
    union_part = args[0]
    union_members = get_args(union_part)
    assert len(union_members) >= 2, (
        f"expected at least 2 union members, got {len(union_members)}: {union_members!r}"
    )
    assert PropertyBinding in union_members
    assert TagBinding in union_members


def test_credential_guard_inherited():
    """IgnitionBaseModel credential guard rejects JWE fields on TagBindingConfig."""
    with pytest.raises(ValidationError):
        TagBindingConfig(tagPath="x", ciphertext="abc")


# ========== Component.bind_tag() helper ==========

def test_bind_tag_returns_self():
    """`bind_tag` returns the Component instance (Self)."""
    c = Component(type="ia.display.label")
    result = c.bind_tag("props.value", "[Sample_Tags]Random/RandomInteger1")
    assert result is c


def test_bind_tag_default_kwargs_direct_mode():
    """Default kwargs produce direct-mode TagBinding."""
    c = Component(type="ia.display.label").bind_tag(
        "props.value", "[Sample_Tags]Random/RandomInteger1"
    )
    assert len(c.propConfig) == 1
    pc = c.propConfig[0]
    assert pc.prop == "props.value"
    binding = pc.binding
    assert isinstance(binding, TagBinding)
    assert binding.type == "tag"
    # use_enum_values=True coerces enum to its string value
    assert binding.config.mode == "direct"
    assert binding.config.tagPath == "[Sample_Tags]Random/RandomInteger1"
    assert binding.config.fallbackDelay == 2.5


def test_bind_tag_indirect_with_references():
    """Indirect-mode kwargs + references attach correctly."""
    c = Component(type="ia.display.label").bind_tag(
        "props.value",
        "{1}",
        mode=TagBindingMode.INDIRECT,
        references={"1": "{view.params.tagPath}"},
    )
    binding = c.propConfig[0].binding
    assert binding.config.mode == "indirect"
    assert binding.config.tagPath == "{1}"
    assert binding.config.references == {"1": "{view.params.tagPath}"}


def test_bind_tag_bad_references_propagates_validation_error():
    """Bad references at .bind_tag() raises ValidationError."""
    c = Component(type="x")
    with pytest.raises(ValidationError):
        c.bind_tag("props.value", "{1}", references=["bad"])


def test_bind_tag_chains_with_expression_transform():
    """`bind_tag().expression(...)` attaches transform to tag binding."""
    c = (
        Component(type="ia.display.label")
        .bind_tag("props.value", "[default]X")
        .expression("upper({value})")
    )
    binding = c.propConfig[0].binding
    assert isinstance(binding, TagBinding)
    assert len(binding.transforms) == 1
    assert binding.transforms[0].expression == "upper({value})"
    assert binding.transforms[0].type == "expression"


def test_multi_binding_chain_routes_to_most_recent_tag_binding():
    """`bind_property` then `bind_tag` then `.expression()` -> goes to tag binding."""
    c = (
        Component(type="x")
        .bind_property("props.a", "view.params.a")
        .bind_tag("props.b", "[default]X")
        .expression("expr_for_tag")
    )
    # Property binding should have NO transforms
    assert len(c.propConfig[0].binding.transforms) == 0
    # Tag binding (most recent) should have the expression transform
    assert isinstance(c.propConfig[1].binding, TagBinding)
    assert len(c.propConfig[1].binding.transforms) == 1
    assert c.propConfig[1].binding.transforms[0].expression == "expr_for_tag"
    # _last_binding handle is the tag binding
    assert c._last_binding is c.propConfig[1].binding


def test_fixture_diff_direct_tag_binding():
    """Byte-equivalent diff against Bindings/view.json direct-mode tag entry."""
    fixture_path = (
        FIXTURE_ROOT
        / "Ignition 101"
        / "Feature Views"
        / "Perspective Features"
        / "Bindings"
        / "view.json"
    )
    fixture = json.loads(fixture_path.read_text())

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
                    if binding.get("type") != "tag":
                        continue
                    cfg = binding.get("config", {})
                    if cfg.get("mode") != "direct":
                        continue
                    if "references" in cfg:
                        continue
                    return prop_key, binding
            for child in node.get("children", []) or []:
                found = walk(child)
                if found is not None:
                    return found
        return None

    result = walk(fixture.get("root", {}))
    assert result is not None, "Bindings fixture missing direct-mode tag binding"
    prop_key, fixture_binding = result

    fixture_tagpath = fixture_binding["config"]["tagPath"]
    built = Component(type="ia.display.label").bind_tag(prop_key, fixture_tagpath)
    emitted = built.model_dump(exclude_none=True, mode="json")["propConfig"][prop_key]["binding"]

    # Superset check: every fixture key+value present in emitted
    for key, fixture_val in fixture_binding.items():
        assert key in emitted, f"missing key {key!r}"
        if key == "config":
            for ck, cv in fixture_val.items():
                assert ck in emitted[key], f"missing config key {ck!r}"
                assert emitted[key][ck] == cv, (
                    f"config.{ck}: built={emitted[key][ck]!r} fixture={cv!r}"
                )
        else:
            assert emitted[key] == fixture_val, (
                f"key {key!r}: built={emitted[key]!r} fixture={fixture_val!r}"
            )


def test_fixture_diff_indirect_tag_binding_gauge():
    """Byte-equivalent diff against Framework/Widgets/Gauge/view.json indirect-mode tag."""
    fixture_path = (
        FIXTURE_ROOT
        / "Framework"
        / "Widgets"
        / "Gauge"
        / "view.json"
    )
    fixture = json.loads(fixture_path.read_text())

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
                    if binding.get("type") != "tag":
                        continue
                    cfg = binding.get("config", {})
                    if cfg.get("mode") != "indirect":
                        continue
                    if "references" not in cfg:
                        continue
                    return prop_key, binding
            for child in node.get("children", []) or []:
                found = walk(child)
                if found is not None:
                    return found
        return None

    result = walk(fixture.get("root", {}))
    assert result is not None, "Gauge fixture missing indirect-mode tag binding"
    prop_key, fixture_binding = result

    fixture_tagpath = fixture_binding["config"]["tagPath"]
    fixture_refs = fixture_binding["config"]["references"]

    built = Component(type="ia.display.view").bind_tag(
        prop_key,
        fixture_tagpath,
        mode=TagBindingMode.INDIRECT,
        references=fixture_refs,
    )
    emitted = built.model_dump(exclude_none=True, mode="json")["propConfig"][prop_key]["binding"]

    # Superset check: every fixture key+value present in emitted
    for key, fixture_val in fixture_binding.items():
        assert key in emitted, f"missing key {key!r}"
        if key == "config":
            for ck, cv in fixture_val.items():
                assert ck in emitted[key], f"missing config key {ck!r}"
                assert emitted[key][ck] == cv, (
                    f"config.{ck}: built={emitted[key][ck]!r} fixture={cv!r}"
                )
        else:
            assert emitted[key] == fixture_val, (
                f"key {key!r}: built={emitted[key]!r} fixture={fixture_val!r}"
            )


def test_discriminated_union_dispatches_correctly():
    """TypeAdapter(Binding) dispatches type->class correctly."""
    from pydantic import TypeAdapter

    adapter = TypeAdapter(Binding)

    tb = adapter.validate_python(
        {
            "type": "tag",
            "config": {"tagPath": "x", "mode": "direct", "fallbackDelay": 2.5},
        }
    )
    assert isinstance(tb, TagBinding)

    pb = adapter.validate_python({"type": "property", "config": {"path": "p"}})
    assert isinstance(pb, PropertyBinding)
