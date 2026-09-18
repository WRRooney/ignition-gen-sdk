"""Tests for QueryBinding + PollingConfig + Component.bind_query().

Verifies:
- PollingConfig(IgnitionBaseModel) with enabled: bool = False, rate: str = "".
- @field_validator("rate", mode="before") coerces int/float -> str.
- QueryBindingConfig with REQUIRED queryPath (NOT path),
  Optional polling/parameters/returnFormat/cacheAndShare.
- QueryBinding (Literal["query"]).
- Binding discriminated union has 5 members (Property + Tag + Expression + ExprStruct + Query).
- Component.bind_query() helper accepts polling_enabled / polling_rate / parameters /
  returnFormat / cacheAndShare kwargs; builds PollingConfig only when at least one
  polling kwarg is supplied; otherwise polling stays None.
- Fixture diff against Bindings/view.json line 657-665:
    {"config": {"polling": {"enabled": true, "rate": "5"},
                "queryPath": "Ignition 101/Named Query Binding"},
     "type": "query"}
- polling.rate emits as a STRING in JSON regardless of int/float/str input
  (the @field_validator coercion).
"""
from __future__ import annotations

import json
from typing import get_args

import pytest
from pydantic import TypeAdapter, ValidationError

from ignition_gen_sdk.bindings import Binding
from ignition_gen_sdk.bindings.expression import ExpressionBinding
from ignition_gen_sdk.bindings.expression_structure import ExpressionStructureBinding
from ignition_gen_sdk.bindings.property import PropertyBinding
from ignition_gen_sdk.bindings.query import (
    PollingConfig,
    QueryBinding,
    QueryBindingConfig,
)
from ignition_gen_sdk.bindings.tag import TagBinding
from ignition_gen_sdk.transforms.format import FormatTransform
from ignition_gen_sdk.models.views.component import Component



from conftest import FIXTURE_ROOT  # noqa: E402


# ============================================================
# PollingConfig + QueryBindingConfig + QueryBinding models
# ============================================================


# ----- PollingConfig -----


def test_polling_config_defaults():
    """PollingConfig() constructs with enabled=False, rate="" defaults."""
    pc = PollingConfig()
    assert pc.enabled is False
    assert pc.rate == ""


def test_polling_config_explicit_string_rate():
    """PollingConfig(enabled=True, rate="5") constructs verbatim."""
    pc = PollingConfig(enabled=True, rate="5")
    assert pc.enabled is True
    assert pc.rate == "5"


def test_polling_config_coerces_int_rate_to_string():
    """PollingConfig(rate=5) — int -> "5" via @field_validator.

    The validator MUST always coerce numeric input to str so users can write
    `.bind_query(polling_rate=5)` ergonomically and still get the gateway's
    string-typed emit shape.
    """
    pc = PollingConfig(rate=5)
    assert pc.rate == "5"
    assert isinstance(pc.rate, str)


def test_polling_config_coerces_float_rate_to_string():
    """PollingConfig(rate=1.5) — float -> "1.5" via @field_validator."""
    pc = PollingConfig(rate=1.5)
    assert pc.rate == "1.5"
    assert isinstance(pc.rate, str)


def test_polling_config_rate_none_becomes_empty_string():
    """PollingConfig(rate=None) -> rate="" (defensive None handling)."""
    pc = PollingConfig(rate=None)
    assert pc.rate == ""


def test_polling_config_rejects_non_numeric_non_string_rate():
    """PollingConfig(rate=[1]) raises (list is not str|int|float)."""
    with pytest.raises(ValidationError):
        PollingConfig(rate=[1])  # type: ignore[arg-type]


def test_polling_config_emits_full_shape():
    """PollingConfig(enabled=False, rate="").model_dump() emits both
    keys as non-None primitives (False, "" are NOT None — exclude_none keeps them)."""
    pc = PollingConfig(enabled=False, rate="")
    assert pc.model_dump() == {"enabled": False, "rate": ""}


# ----- QueryBindingConfig -----


def test_query_binding_config_minimal_constructs():
    """QueryBindingConfig(queryPath=...) — minimal valid construction.
    All Optional fields default to None.
    """
    cfg = QueryBindingConfig(queryPath="Ignition 101/Named Query Binding")
    assert cfg.queryPath == "Ignition 101/Named Query Binding"
    assert cfg.polling is None
    assert cfg.parameters is None
    assert cfg.returnFormat is None
    assert cfg.cacheAndShare is None


def test_query_binding_config_requires_query_path():
    """QueryBindingConfig() raises ValidationError — queryPath required."""
    with pytest.raises(ValidationError):
        QueryBindingConfig()  # type: ignore[call-arg]


def test_query_binding_config_accepts_polling_subobject():
    """QueryBindingConfig(queryPath=x, polling=PollingConfig(...))."""
    cfg = QueryBindingConfig(
        queryPath="x", polling=PollingConfig(enabled=True, rate="5")
    )
    assert cfg.polling is not None
    assert cfg.polling.enabled is True
    assert cfg.polling.rate == "5"


def test_query_binding_config_return_format_literal_rejects_invalid():
    """QueryBindingConfig(returnFormat="invalid") rejected.

    Literal["auto", "json", "dataset", "scalar"] only.
    """
    with pytest.raises(ValidationError):
        QueryBindingConfig(queryPath="x", returnFormat="invalid")  # type: ignore[arg-type]


def test_query_binding_config_return_format_accepts_each_literal():
    """QueryBindingConfig accepts each Literal value for returnFormat."""
    for fmt in ("auto", "json", "dataset", "scalar"):
        cfg = QueryBindingConfig(queryPath="x", returnFormat=fmt)
        assert cfg.returnFormat == fmt


# ----- QueryBinding -----


def test_query_binding_type_discriminator_default():
    """QueryBinding default type is "query"."""
    qb = QueryBinding(config=QueryBindingConfig(queryPath="x"))
    assert qb.type == "query"


def test_query_binding_rejects_wrong_discriminator():
    """QueryBinding(type="property") rejected — Literal["query"] only."""
    with pytest.raises(ValidationError):
        QueryBinding(type="property", config=QueryBindingConfig(queryPath="x"))


def test_query_binding_config_excludes_none_optional_fields():
    """QueryBindingConfig(queryPath="x").model_dump(exclude_none=True)
    yields {"queryPath": "x"} only — all Optional fields excluded."""
    cfg = QueryBindingConfig(queryPath="x")
    assert cfg.model_dump(exclude_none=True) == {"queryPath": "x"}


# ----- Binding union expanded to 5 members -----


def test_binding_union_has_query_member():
    """Binding union has 5 members (Property + Tag + Expression
    + ExprStruct + Query). Uses a >= N + membership idiom so the count can
    grow without breaking this test."""
    members = get_args(get_args(Binding)[0])
    assert len(members) >= 5
    assert PropertyBinding in members
    assert TagBinding in members
    assert ExpressionBinding in members
    assert ExpressionStructureBinding in members
    assert QueryBinding in members


def test_binding_union_dispatches_query_via_type_adapter():
    """TypeAdapter(Binding).validate_python({"type":"query",...}) -> QueryBinding."""
    adapter = TypeAdapter(Binding)
    qb = adapter.validate_python(
        {"type": "query", "config": {"queryPath": "Ignition 101/Named Query Binding"}}
    )
    assert isinstance(qb, QueryBinding)
    assert qb.config.queryPath == "Ignition 101/Named Query Binding"


# ----- Credential guard inherited -----


def test_query_binding_config_rejects_credential_fields():
    """QueryBindingConfig(queryPath="x", ciphertext="...") raises ValueError.

    The IgnitionBaseModel credential guard (model_validator mode='before')
    must still fire on this nested model.
    """
    with pytest.raises(ValueError):
        QueryBindingConfig(queryPath="x", ciphertext="...")  # type: ignore[call-arg]


# ============================================================
# Component.bind_query() helper + fixture diff
# ============================================================


def test_bind_query_returns_self_minimal():
    """c.bind_query("p", queryPath=...) returns Component; polling is None."""
    c = Component(type="x")
    result = c.bind_query(
        "props.data", queryPath="Ignition 101/Named Query Binding"
    )
    assert result is c
    assert len(c.propConfig) == 1
    pc = c.propConfig[0]
    assert pc.binding.type == "query"
    assert pc.binding.config.queryPath == "Ignition 101/Named Query Binding"
    # No polling kwargs supplied -> polling stays None
    assert pc.binding.config.polling is None
    assert pc.binding.config.parameters is None
    assert pc.binding.config.returnFormat is None
    assert pc.binding.config.cacheAndShare is None


def test_bind_query_with_string_polling_rate():
    """c.bind_query(..., polling_enabled=True, polling_rate="5") -> PollingConfig."""
    c = Component(type="x").bind_query(
        "props.data",
        queryPath="x",
        polling_enabled=True,
        polling_rate="5",
    )
    polling = c.propConfig[0].binding.config.polling
    assert polling is not None
    assert polling.enabled is True
    assert polling.rate == "5"


def test_bind_query_with_int_polling_rate_coerces_to_string():
    """c.bind_query(..., polling_rate=5) — int input coerces to "5"."""
    c = Component(type="x").bind_query(
        "props.data", queryPath="x", polling_enabled=True, polling_rate=5
    )
    polling = c.propConfig[0].binding.config.polling
    assert polling is not None
    assert polling.rate == "5"
    assert isinstance(polling.rate, str)


def test_bind_query_no_polling_kwargs_leaves_polling_none():
    """c.bind_query("p", queryPath="x") with NO polling kwargs -> polling stays None.

    Critical: the helper must NOT construct a default PollingConfig — that would
    emit polling: {enabled: false, rate: ""} into every binding and pollute the
    fixture-parity check.
    """
    c = Component(type="x").bind_query("props.data", queryPath="x")
    assert c.propConfig[0].binding.config.polling is None


def test_bind_query_with_parameters():
    """c.bind_query(..., parameters={"k":"v"}) — parameters dict set."""
    c = Component(type="x").bind_query(
        "props.data", queryPath="x", parameters={"k": "v"}
    )
    assert c.propConfig[0].binding.config.parameters == {"k": "v"}


def test_bind_query_with_return_format_dataset():
    """c.bind_query(..., returnFormat="dataset") — Literal accepted."""
    c = Component(type="x").bind_query(
        "props.data", queryPath="x", returnFormat="dataset"
    )
    assert c.propConfig[0].binding.config.returnFormat == "dataset"


def test_bind_query_with_invalid_return_format_raises():
    """c.bind_query(..., returnFormat="bogus") raises ValidationError."""
    c = Component(type="x")
    with pytest.raises(ValidationError):
        c.bind_query("props.data", queryPath="x", returnFormat="bogus")  # type: ignore[arg-type]


def test_bind_query_chains_format_transform():
    """c.bind_query(...).format("0.00") -> FormatTransform attaches to
    this binding's transforms list."""
    c = (
        Component(type="x")
        .bind_query("props.data", queryPath="x")
        .format("0.00")
    )
    transforms = c.propConfig[0].binding.transforms
    assert len(transforms) == 1
    assert isinstance(transforms[0], FormatTransform)
    assert transforms[0].formatValue == "0.00"


def test_bind_query_with_cache_and_share():
    """c.bind_query(..., cacheAndShare=True) — bool propagates."""
    c = Component(type="x").bind_query(
        "props.data", queryPath="x", cacheAndShare=True
    )
    assert c.propConfig[0].binding.config.cacheAndShare is True


def test_bind_query_emits_polling_rate_as_string_via_int_kwarg():
    """bind_query(..., polling_rate=5) emits "rate": "5" (string) in JSON.

    Verifies the end-to-end coercion: int input -> string in emitted JSON.
    This is the rate-as-string lock — any future change that drops the
    @field_validator MUST fail this test.
    """
    c = Component(type="x").bind_query(
        "props.data",
        queryPath="x",
        polling_enabled=True,
        polling_rate=5,
    )
    emit = c.propConfig[0].binding.model_dump(exclude_none=True, mode="json")
    assert emit["config"]["polling"]["rate"] == "5"
    assert isinstance(emit["config"]["polling"]["rate"], str)


# ----- Fixture diff -----


def _load_view(view_relpath: str) -> dict:
    if FIXTURE_ROOT is None:
        pytest.skip("IGNITION_SAMPLE_VIEWS not set; fixture-diff test skipped.")
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


def test_fixture_diff_query_binding_bindings_view():
    """Fixture-diff against Bindings/view.json line 657-665.

    Fixture binding subtree:
        {"config": {"polling": {"enabled": true, "rate": "5"},
                    "queryPath": "Ignition 101/Named Query Binding"},
         "type": "query"}

    Rebuild via Component(type="x").bind_query(prop_path, queryPath=...,
    polling_enabled=fixture.enabled, polling_rate=fixture.rate). Emitted shape
    must SUPERSET match the fixture (extra fields like enabled, overlayOptOut,
    transforms are allowed on the rebuild side).

    ALSO verifies polling.rate is emitted as STRING "5" (not int 5), even
    though we could pass either; here we pass it through the fixture value.
    """
    view = _load_view(
        "Ignition 101/Feature Views/Perspective Features/Bindings/view.json"
    )
    found = _walk_find_propconfig_by_type(view, "query")
    assert found, "no query binding found in Bindings/view.json"

    target = next(((p, b) for (p, b) in found if p == "props.data"), None)
    assert target is not None, f"props.data query binding not in {found}"
    prop_path, fixture_binding = target

    fixture_qp = fixture_binding["config"]["queryPath"]
    fixture_polling = fixture_binding["config"]["polling"]
    assert isinstance(fixture_polling["rate"], str), (
        "fixture polling.rate must be a string per Ignition 8.3 wire shape "
        f"(got {type(fixture_polling['rate']).__name__})"
    )

    rebuilt = Component(type="ia.display.table").bind_query(
        prop_path,
        queryPath=fixture_qp,
        polling_enabled=fixture_polling["enabled"],
        polling_rate=fixture_polling["rate"],
    )
    emitted = rebuilt.model_dump(exclude_none=True, mode="json")["propConfig"][prop_path][
        "binding"
    ]
    _is_superset(emitted, fixture_binding)

    # Lock: polling.rate is a string in the emitted JSON
    assert isinstance(emitted["config"]["polling"]["rate"], str)
    assert emitted["config"]["polling"]["rate"] == "5"


# ----- Cross-binding regression smoke -----


def test_regression_smoke_all_binding_types():
    """regression — every prior binding type + transform chain still works.

    Query bindings must not break property/tag/expression/expr-struct
    bindings or any of the four transform chain helpers.
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
        .bind_expression("props.c", "toBoolean({x})")
        .bind_expression_structure("props.d", struct={"k": "v"})
        .bind_query("props.e", queryPath="x", polling_enabled=True, polling_rate="5")
    )
    types = [pc.binding.type for pc in c.propConfig]
    assert types == ["property", "tag", "expr", "expr-struct", "query"]
    # property got 1 transform; tag got 3
    assert len(c.propConfig[0].binding.transforms) == 1
    assert len(c.propConfig[1].binding.transforms) == 3
    # expr / expr-struct / query: 0 transforms each (no chain on them)
    assert len(c.propConfig[2].binding.transforms) == 0
    assert len(c.propConfig[3].binding.transforms) == 0
    assert len(c.propConfig[4].binding.transforms) == 0
