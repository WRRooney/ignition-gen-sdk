"""Tests for PropertyBinding + propConfig refactor.

Verifies:
- PropertyBinding/PropertyBindingConfig model construction and validation
- PropConfig wrapper
- Component.propConfig refactor to list[PropConfig] with BeforeValidator
- @field_serializer emits INNER "binding" wrapper 
- Byte-equivalent fixture diff against Layouts/Layout Card/view.json line 41-51
"""
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from ignition_gen_sdk.bindings.property import PropertyBinding, PropertyBindingConfig
from ignition_gen_sdk.bindings.prop_config import PropConfig
from ignition_gen_sdk.bindings.enums import TagBindingMode, HttpMethod, TimeUnits
from ignition_gen_sdk.models.views.component import Component




from conftest import FIXTURE_ROOT  # noqa: E402


# ---------- PropertyBinding model tests ----------

def test_property_binding_minimal_construct():
    pb = PropertyBinding(config=PropertyBindingConfig(path="view.params.title"))
    assert pb.type == "property"
    assert pb.enabled is True
    assert pb.overlayOptOut is False
    assert pb.config.path == "view.params.title"
    assert pb.transforms == []


def test_property_binding_path_required():
    with pytest.raises(ValidationError):
        PropertyBindingConfig()  # type: ignore[call-arg]


def test_property_binding_wrong_type_rejected():
    # Literal["property"] discriminator rejects other values.
    with pytest.raises(ValidationError):
        PropertyBinding(
            config=PropertyBindingConfig(path="x"), type="tag"  # type: ignore[arg-type]
        )


def test_property_binding_bidirectional_optional():
    no_bi = PropertyBindingConfig(path="x").model_dump(exclude_none=True)
    assert no_bi == {"path": "x"}, no_bi
    with_bi = PropertyBindingConfig(path="x", bidirectional=True).model_dump(
        exclude_none=True
    )
    assert with_bi == {"path": "x", "bidirectional": True}, with_bi


def test_property_binding_emit_clean():
    """Gateway samples never emit enabled/overlayOptOut/
    empty transforms. The binding's @model_serializer strips them.
    Verified shape from samplequickstart Layouts/Layout Card/view.json:41-51."""
    pb = PropertyBinding(config=PropertyBindingConfig(path="view.params.title"))
    expected = {
        "type": "property",
        "config": {"path": "view.params.title"},
    }
    assert pb.model_dump(exclude_none=True, mode="json") == expected


def test_property_binding_emit_omits_default_keys():
    """Gateway samples never emit enabled/overlayOptOut/
    empty transforms on any binding. Pin the suppression across all 7
    binding types so future authors do not regress this back."""
    from ignition_gen_sdk.bindings.expression import (
        ExpressionBinding, ExpressionBindingConfig,
    )
    from ignition_gen_sdk.bindings.expression_structure import (
        ExpressionStructureBinding, ExpressionStructureBindingConfig,
    )
    from ignition_gen_sdk.bindings.http import (
        HttpBinding, HttpBindingConfig, HttpRequest,
    )
    from ignition_gen_sdk.bindings.query import (
        QueryBinding, QueryBindingConfig,
    )
    from ignition_gen_sdk.bindings.tag import TagBinding, TagBindingConfig
    from ignition_gen_sdk.bindings.tag_history import (
        TagHistoryBinding, TagHistoryBindingConfig,
    )

    bindings = [
        PropertyBinding(config=PropertyBindingConfig(path="x")),
        TagBinding(config=TagBindingConfig(tagPath="[default]A")),
        ExpressionBinding(config=ExpressionBindingConfig(expression="1+1")),
        ExpressionStructureBinding(
            config=ExpressionStructureBindingConfig(struct={})
        ),
        QueryBinding(config=QueryBindingConfig(queryPath="q1")),
        TagHistoryBinding(config=TagHistoryBindingConfig(tags="[default]A")),
        HttpBinding(config=HttpBindingConfig(request=HttpRequest(url='"u"'))),
    ]
    for b in bindings:
        out = b.model_dump(exclude_none=True, mode="json")
        assert "enabled" not in out, (
            f"{type(b).__name__} still emits enabled"
        )
        assert "overlayOptOut" not in out, (
            f"{type(b).__name__} still emits overlayOptOut"
        )
        assert "transforms" not in out, (
            f"{type(b).__name__} still emits empty transforms"
        )


def test_property_binding_emit_preserves_non_default_flags():
    """Only DEFAULT values are stripped. Explicit non-default
    enabled=False / overlayOptOut=True must still emit so the user's
    intent reaches the gateway."""
    b = PropertyBinding(
        config=PropertyBindingConfig(path="x"),
        enabled=False,
        overlayOptOut=True,
    )
    out = b.model_dump(exclude_none=True, mode="json")
    assert out.get("enabled") is False, out
    assert out.get("overlayOptOut") is True, out


def test_property_binding_emit_preserves_non_empty_transforms():
    """Only EMPTY transforms list is stripped. A populated list emits."""
    from ignition_gen_sdk.transforms.expression import ExpressionTransform
    b = PropertyBinding(
        config=PropertyBindingConfig(path="x"),
        transforms=[ExpressionTransform(expression="1+1")],
    )
    out = b.model_dump(exclude_none=True, mode="json")
    assert out.get("transforms") == [{"type": "expression", "expression": "1+1"}]


def test_property_binding_extra_forbidden():
    with pytest.raises(ValidationError):
        PropertyBinding(
            config=PropertyBindingConfig(path="x"),
            bogus_field=1,  # type: ignore[call-arg]
        )


def test_credential_guard_inherited():
    with pytest.raises(ValueError):
        # ciphertext is a JWE field — base model_validator must reject.
        PropertyBindingConfig(path="x", ciphertext="abc")  # type: ignore[call-arg]


def test_enums_emit_string_values():
    assert TagBindingMode.DIRECT.value == "direct"
    assert HttpMethod.GET.value == "GET"
    assert TimeUnits.MIN.value == "MIN"


# ---------- PropConfig wrapper tests ----------

def test_propconfig_wrapper():
    """Enabled/overlayOptOut/empty transforms stripped from binding emit."""
    pc = PropConfig(
        prop="props.text",
        binding=PropertyBinding(config=PropertyBindingConfig(path="view.params.title")),
    )
    expected = {
        "prop": "props.text",
        "binding": {
            "type": "property",
            "config": {"path": "view.params.title"},
        },
    }
    assert pc.model_dump(exclude_none=True, mode="json") == expected


# ---------- Component.propConfig refactor tests ----------

def test_component_propconfig_default_is_list():
    c = Component(type="ia.display.label")
    assert c.propConfig == []
    assert isinstance(c.propConfig, list)


def test_component_propconfig_accepts_list_form():
    c = Component(
        type="ia.display.label",
        propConfig=[
            PropConfig(
                prop="props.text",
                binding=PropertyBinding(
                    config=PropertyBindingConfig(path="view.params.title")
                ),
            )
        ],
    )
    assert isinstance(c.propConfig, list)
    assert len(c.propConfig) == 1
    assert isinstance(c.propConfig[0], PropConfig)
    assert c.propConfig[0].prop == "props.text"


def test_component_propconfig_accepts_dict_form_with_inner_binding():
    """BackwardsCompat: gateway-shape dict input is coerced via BeforeValidator."""
    c = Component(
        type="ia.display.label",
        propConfig={
            "props.text": {
                "binding": {
                    "type": "property",
                    "config": {"path": "view.params.title"},
                }
            }
        },
    )
    assert isinstance(c.propConfig, list)
    assert len(c.propConfig) == 1
    pc = c.propConfig[0]
    assert pc.prop == "props.text"
    assert pc.binding.type == "property"
    assert pc.binding.config.path == "view.params.title"


def test_component_propconfig_accepts_dict_form_flat_legacy():
    """BackwardsCompat: flat-binding dict input also coerced (no inner 'binding' key)."""
    c = Component(
        type="ia.display.label",
        propConfig={
            "props.text": {"type": "property", "config": {"path": "x"}},
        },
    )
    assert isinstance(c.propConfig, list)
    assert len(c.propConfig) == 1
    assert c.propConfig[0].prop == "props.text"
    assert c.propConfig[0].binding.config.path == "x"


def test_component_empty_propconfig_omitted_on_emit():
    c = Component(type="ia.display.label")
    out = c.model_dump(exclude_none=True, mode="json")
    assert "propConfig" not in out


def test_component_propconfig_emits_inner_binding_wrapper():
    """THE critical test — inner 'binding' wrapper key REQUIRED."""
    c = Component(
        type="ia.display.label",
        propConfig=[
            PropConfig(
                prop="props.text",
                binding=PropertyBinding(
                    config=PropertyBindingConfig(path="view.params.title")
                ),
            )
        ],
    )
    dumped = c.model_dump(exclude_none=True, mode="json")
    # Enabled/overlayOptOut/empty transforms stripped from binding emit.
    assert dumped["propConfig"] == {
        "props.text": {
            "binding": {
                "type": "property",
                "config": {"path": "view.params.title"},
            }
        }
    }
    # Specifically: top-level key under prop is "binding", NOT "type"/"config".
    entry = dumped["propConfig"]["props.text"]
    assert list(entry.keys()) == ["binding"]


def test_component_last_binding_is_private_attr():
    c = Component(type="ia.display.label")
    assert c._last_binding is None
    dumped = c.model_dump(exclude_none=True, mode="json")
    assert "_last_binding" not in dumped
    # Round-trip: model_validate of the dump must not require/carry _last_binding.
    c2 = Component.model_validate(dumped)
    assert c2._last_binding is None


# ---------- Fixture diff ----------

def test_fixture_diff_layout_card_props_text():
    """Byte-equivalent diff against Layouts/Layout Card/view.json line 41-51."""
    fixture_path = FIXTURE_ROOT / "Layouts" / "Layout Card" / "view.json"
    fixture = json.loads(fixture_path.read_text())

    def find_propconfig_with_binding(node):
        if isinstance(node, dict):
            pc = node.get("propConfig", {})
            if isinstance(pc, dict):
                for prop_key, entry in pc.items():
                    if (
                        isinstance(entry, dict)
                        and "binding" in entry
                        and entry["binding"].get("type") == "property"
                        and prop_key == "props.text"
                    ):
                        return entry  # the {"binding": {...}} dict
            for child in node.get("children", []) or []:
                found = find_propconfig_with_binding(child)
                if found is not None:
                    return found
        return None

    fixture_entry = find_propconfig_with_binding(fixture.get("root", {}))
    assert (
        fixture_entry is not None
    ), "Layout Card fixture is missing the expected props.text property binding"

    binding_config_path = fixture_entry["binding"]["config"]["path"]
    built = Component(
        type="ia.display.label",
        propConfig=[
            PropConfig(
                prop="props.text",
                binding=PropertyBinding(
                    config=PropertyBindingConfig(path=binding_config_path)
                ),
            )
        ],
    ).model_dump(exclude_none=True, mode="json")["propConfig"]["props.text"]

    fixture_binding = fixture_entry["binding"]
    built_binding = built["binding"]
    # Superset check: built may contain default-valued keys fixture omits
    # (enabled=True, overlayOptOut=False, transforms=[]). Verify EVERY
    # fixture key appears in built with same value.
    for key, fixture_val in fixture_binding.items():
        assert key in built_binding, f"missing key {key}"
        assert built_binding[key] == fixture_val, (
            f"key {key}: built={built_binding[key]!r} fixture={fixture_val!r}"
        )
