"""Tests for Map/Format/Script transforms + chain helpers.

Verifies:
- MapTransform / MapMapping / NumericRange construction (Literal['map'] discriminator)
- FormatTransform / FormatDatetimeConfig construction (Literal['format'] discriminator)
- ScriptTransform construction (Literal['script'] discriminator; whitespace preserved)
- Transform discriminated union expanded from 1 to 4 members
- Component.map() pops 'fallback' key (does NOT mutate caller's dict)
- Component.format() / .script() chain helpers (Self return; orphan RuntimeError)
- Multi-transform chain ordering through a single binding
- Fixture diffs:
    * Map+fallback: Components/Nav/Containers/view.json
    * Format numeric: Ignition 101/Feature Views/Perspective Features/Transforms/view.json
    * Script (whitespace preservation): same Transforms/view.json
- Discriminated-union round-trip through TypeAdapter dispatches all 4 type values.
"""
from __future__ import annotations

import json
from typing import get_args

import pytest
from pydantic import TypeAdapter, ValidationError

from ignition_gen_sdk.transforms import Transform
from ignition_gen_sdk.transforms.expression import ExpressionTransform
from ignition_gen_sdk.transforms.map import MapTransform, MapMapping, NumericRange
from ignition_gen_sdk.transforms.format import FormatTransform, FormatDatetimeConfig
from ignition_gen_sdk.transforms.script import ScriptTransform
from ignition_gen_sdk.models.views.component import Component




from conftest import FIXTURE_ROOT  # noqa: E402


# ============================================================
# Transform models (Map / Format / Script)
# ============================================================

# ----- MapTransform / MapMapping / NumericRange -----

def test_numeric_range_default_emit():
    """NumericRange exclusive flags default False; min/max omitted when None."""
    nr = NumericRange(min=0, max=10)
    out = nr.model_dump(exclude_none=True)
    assert out == {"min": 0, "max": 10, "exclusiveMin": False, "exclusiveMax": False}


def test_map_mapping_basic_emit():
    """MapMapping emit shape {input,output} (no extras)."""
    m = MapMapping(input="x", output="y")
    out = m.model_dump(exclude_none=True)
    assert out == {"input": "x", "output": "y"}


def test_map_transform_constructs_with_defaults():
    """MapTransform constructs; type/inputType/outputType have correct defaults; fallback is None."""
    mt = MapTransform(mappings=[MapMapping(input="a", output="b")])
    assert mt.type == "map"
    assert mt.inputType == "scalar"
    assert mt.outputType == "scalar"
    assert mt.fallback is None


def test_map_transform_requires_mappings_field():
    """Mappings is REQUIRED (no default)."""
    with pytest.raises(ValidationError):
        MapTransform()  # type: ignore[call-arg]


def test_map_transform_emits_full_shape_with_fallback():
    """Full emit shape with fallback set."""
    mt = MapTransform(
        mappings=[MapMapping(input="x", output="y")],
        fallback="UNK",
    )
    out = mt.model_dump(exclude_none=True, mode="json")
    assert out == {
        "type": "map",
        "inputType": "scalar",
        "outputType": "scalar",
        "mappings": [{"input": "x", "output": "y"}],
        "fallback": "UNK",
    }


def test_map_transform_rejects_bogus_input_type():
    """Literal restricts inputType to {scalar, range, expression}."""
    with pytest.raises(ValidationError):
        MapTransform(
            mappings=[MapMapping(input="x", output="y")],
            inputType="bogus",  # type: ignore[arg-type]
        )


# ----- FormatTransform / FormatDatetimeConfig -----

def test_format_transform_numeric_default_and_emit():
    """FormatTransform with formatValue=str, default formatType=numeric."""
    ft = FormatTransform(formatValue="0.000")
    out = ft.model_dump(exclude_none=True, mode="json")
    assert out == {"type": "format", "formatType": "numeric", "formatValue": "0.000"}


def test_format_transform_accepts_datetime_literal():
    """FormatType Literal allows 'datetime'; formatValue may be a plain str, not only FormatDatetimeConfig."""
    ft = FormatTransform(formatValue="0.00", formatType="datetime")
    assert ft.formatType == "datetime"


def test_format_transform_requires_format_value():
    """FormatValue is REQUIRED (no default)."""
    with pytest.raises(ValidationError):
        FormatTransform()  # type: ignore[call-arg]


def test_format_datetime_config_defaults():
    """FormatDatetimeConfig defaults date/time to 'medium'."""
    c = FormatDatetimeConfig(date="medium", time="short")
    assert c.model_dump() == {"date": "medium", "time": "short"}


def test_format_transform_datetime_with_datetime_config():
    """FormatTransform with FormatDatetimeConfig formatValue emits nested dict."""
    ft = FormatTransform(
        formatType="datetime",
        formatValue=FormatDatetimeConfig(),
    )
    out = ft.model_dump(exclude_none=True, mode="json")
    assert out["formatValue"] == {"date": "medium", "time": "medium"}


# ----- ScriptTransform -----

def test_script_transform_constructs_and_emits():
    """ScriptTransform stores code as plain str and emits."""
    st = ScriptTransform(code="return value * 2")
    out = st.model_dump(exclude_none=True, mode="json")
    assert out == {"type": "script", "code": "return value * 2"}


def test_script_transform_requires_code_field():
    """Code is REQUIRED (no default)."""
    with pytest.raises(ValidationError):
        ScriptTransform()  # type: ignore[call-arg]


# ----- Transform discriminated union -----

def test_transform_union_has_four_members():
    """Transform discriminated union has 4 members."""
    args = get_args(Transform)
    assert len(args) >= 2  # Union + Discriminator metadata
    union_part = args[0]
    union_members = get_args(union_part)
    assert MapTransform in union_members
    assert FormatTransform in union_members
    assert ScriptTransform in union_members
    assert ExpressionTransform in union_members
    assert len(union_members) == 4


def test_transform_union_round_trips_map():
    """TypeAdapter(Transform) dispatches type='map' to MapTransform."""
    adapter = TypeAdapter(Transform)
    inst = adapter.validate_python({
        "type": "map",
        "inputType": "scalar",
        "outputType": "scalar",
        "mappings": [{"input": "x", "output": "y"}],
    })
    assert isinstance(inst, MapTransform)


def test_transform_union_round_trips_all_four():
    """TypeAdapter dispatches all 4 type discriminator values correctly."""
    adapter = TypeAdapter(Transform)
    map_inst = adapter.validate_python({
        "type": "map",
        "mappings": [{"input": "a", "output": "b"}],
    })
    fmt_inst = adapter.validate_python({"type": "format", "formatValue": "0.0"})
    scr_inst = adapter.validate_python({"type": "script", "code": "return 1"})
    expr_inst = adapter.validate_python({"type": "expression", "expression": "{value}"})
    assert isinstance(map_inst, MapTransform)
    assert isinstance(fmt_inst, FormatTransform)
    assert isinstance(scr_inst, ScriptTransform)
    assert isinstance(expr_inst, ExpressionTransform)


# ============================================================
# Component.map() / .format() / .script() chain methods
# ============================================================

# ----- .map() -----

def test_map_appends_transform_to_last_binding():
    """.map() appends MapTransform; type==map; 2 mappings; fallback None."""
    c = (
        Component(type="x")
        .bind_property("p", "src")
        .map({"true": "ON", "false": "OFF"})
    )
    transforms = c.propConfig[0].binding.transforms
    assert len(transforms) == 1
    assert isinstance(transforms[0], MapTransform)
    assert len(transforms[0].mappings) == 2
    assert transforms[0].fallback is None


def test_map_pops_fallback_key():
    """Fallback key popped from input dict; not present in mappings."""
    c = (
        Component(type="x")
        .bind_property("p", "src")
        .map({"a": "A", "fallback": "UNK"})
    )
    mt = c.propConfig[0].binding.transforms[0]
    assert mt.fallback == "UNK"
    assert len(mt.mappings) == 1
    # Verify 'fallback' did NOT leak into mappings
    inputs = [m.input for m in mt.mappings]
    assert "fallback" not in inputs
    assert inputs == ["a"]


def test_map_empty_dict_emits_empty_mappings_no_fallback():
    """Empty dict — empty mappings list; no fallback."""
    c = Component(type="x").bind_property("p", "src").map({})
    mt = c.propConfig[0].binding.transforms[0]
    assert mt.mappings == []
    assert mt.fallback is None


def test_map_does_not_mutate_caller_dict():
    """Defensive — caller's dict is unchanged after .map()."""
    caller_dict = {"a": "A", "fallback": "UNK"}
    snapshot = dict(caller_dict)
    Component(type="x").bind_property("p", "src").map(caller_dict)
    assert caller_dict == snapshot, "caller dict was mutated by .map() — copy-before-pop broken"


def test_map_without_preceding_bind_raises_runtime_error():
    """.map() without preceding .bind_*() raises RuntimeError."""
    c = Component(type="x")
    with pytest.raises(RuntimeError) as excinfo:
        c.map({"a": "b"})
    msg = str(excinfo.value)
    assert ".map()" in msg
    assert ".bind_" in msg


# ----- .format() -----

def test_format_appends_numeric_format_transform():
    """.format() appends FormatTransform with formatType='numeric'."""
    c = Component(type="x").bind_property("p", "src").format("0.00")
    ft = c.propConfig[0].binding.transforms[0]
    assert isinstance(ft, FormatTransform)
    assert ft.formatType == "numeric"
    assert ft.formatValue == "0.00"


def test_format_without_preceding_bind_raises_runtime_error():
    """.format() without preceding .bind_*() raises RuntimeError."""
    c = Component(type="x")
    with pytest.raises(RuntimeError) as excinfo:
        c.format("0.00")
    msg = str(excinfo.value)
    assert ".format()" in msg
    assert ".bind_" in msg


# ----- .script() -----

def test_script_appends_script_transform():
    """.script() appends ScriptTransform; code field preserved verbatim."""
    c = Component(type="x").bind_property("p", "src").script("return value")
    st = c.propConfig[0].binding.transforms[0]
    assert isinstance(st, ScriptTransform)
    assert st.code == "return value"


def test_script_without_preceding_bind_raises_runtime_error():
    """.script() without preceding .bind_*() raises RuntimeError."""
    c = Component(type="x")
    with pytest.raises(RuntimeError) as excinfo:
        c.script("return 1")
    msg = str(excinfo.value)
    assert ".script()" in msg
    assert ".bind_" in msg


# ----- multi-transform chain ordering -----

def test_multi_transform_chain_preserves_order():
    """Chain produces transforms list in order [map,format,script,expression]."""
    c = (
        Component(type="x")
        .bind_tag("p", "[default]X")
        .map({"a": "b"})
        .format("0.00")
        .script("return value")
        .expression("upper({value})")
    )
    transforms = c.propConfig[0].binding.transforms
    assert len(transforms) == 4
    assert isinstance(transforms[0], MapTransform)
    assert isinstance(transforms[1], FormatTransform)
    assert isinstance(transforms[2], ScriptTransform)
    assert isinstance(transforms[3], ExpressionTransform)

    # Emit order matches Python-list-append order 
    emitted = c.model_dump(exclude_none=True, mode="json")
    emit_transforms = emitted["propConfig"]["p"]["binding"]["transforms"]
    assert [t["type"] for t in emit_transforms] == [
        "map", "format", "script", "expression"
    ]


# ----- fixture diffs -----

def test_fixture_diff_map_with_fallback_nav_containers():
    """Byte-equivalent diff against Components/Nav/Containers/view.json map+fallback."""
    fixture_path = (
        FIXTURE_ROOT
        / "Components"
        / "Nav"
        / "Containers"
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
                    transforms = binding.get("transforms", [])
                    if not transforms:
                        continue
                    t0 = transforms[0]
                    if t0.get("type") != "map":
                        continue
                    if "fallback" not in t0:
                        continue
                    return prop_key, binding
            for child in node.get("children", []) or []:
                found = walk(child)
                if found is not None:
                    return found
        return None

    result = walk(fixture.get("root", {}))
    assert result is not None, "Nav/Containers fixture missing map-with-fallback transform"
    prop_key, fixture_binding = result

    fixture_path_val = fixture_binding["config"]["path"]
    fixture_t0 = fixture_binding["transforms"][0]
    # Convert fixture mappings list -> dict + fallback key per .map() contract
    mappings_dict = {entry["input"]: entry["output"] for entry in fixture_t0["mappings"]}
    mappings_dict["fallback"] = fixture_t0["fallback"]

    built = (
        Component(type="ia.display.label")
        .bind_property(prop_key, fixture_path_val)
        .map(mappings_dict)
    )
    emit = built.model_dump(exclude_none=True, mode="json")
    emit_t0 = emit["propConfig"][prop_key]["binding"]["transforms"][0]

    # Superset check: every fixture transform key+value present in built emit
    for k, v in fixture_t0.items():
        assert k in emit_t0, f"missing transform key {k!r}"
        assert emit_t0[k] == v, (
            f"transforms[0].{k}: built={emit_t0[k]!r} fixture={v!r}"
        )


def test_fixture_diff_format_numeric_transforms_view():
    """Byte-equivalent diff against Transforms/view.json format-numeric transform."""
    fixture_path = (
        FIXTURE_ROOT
        / "Ignition 101"
        / "Feature Views"
        / "Perspective Features"
        / "Transforms"
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
                    transforms = binding.get("transforms", [])
                    for idx, t in enumerate(transforms):
                        if t.get("type") == "format" and t.get("formatType") == "numeric":
                            return prop_key, binding, idx
            for child in node.get("children", []) or []:
                found = walk(child)
                if found is not None:
                    return found
        return None

    result = walk(fixture.get("root", {}))
    assert result is not None, "Transforms fixture missing format-numeric transform"
    prop_key, fixture_binding, idx = result
    fixture_t = fixture_binding["transforms"][idx]

    # Binding is a tag binding in this fixture — must use bind_tag.
    cfg = fixture_binding["config"]
    built = (
        Component(type="ia.display.label")
        .bind_tag(prop_key, cfg["tagPath"])
        .format(fixture_t["formatValue"])
    )
    emit = built.model_dump(exclude_none=True, mode="json")
    emit_t = emit["propConfig"][prop_key]["binding"]["transforms"][0]

    for k, v in fixture_t.items():
        assert k in emit_t, f"missing transform key {k!r}"
        assert emit_t[k] == v, (
            f"transforms[{idx}].{k}: built={emit_t[k]!r} fixture={v!r}"
        )


def test_fixture_diff_script_with_whitespace_transforms_view():
    """Script transform preserves whitespace including \\t and \\n."""
    fixture_path = (
        FIXTURE_ROOT
        / "Ignition 101"
        / "Feature Views"
        / "Perspective Features"
        / "Transforms"
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
                    transforms = binding.get("transforms", [])
                    for idx, t in enumerate(transforms):
                        if t.get("type") == "script":
                            return prop_key, binding, idx
            for child in node.get("children", []) or []:
                found = walk(child)
                if found is not None:
                    return found
        return None

    result = walk(fixture.get("root", {}))
    assert result is not None, "Transforms fixture missing script transform"
    prop_key, fixture_binding, idx = result
    fixture_t = fixture_binding["transforms"][idx]
    fixture_code = fixture_t["code"]
    # Sanity — fixture must have whitespace including a tab char
    assert "\t" in fixture_code, "script fixture sample lacks tab — bad fixture pick"

    cfg = fixture_binding["config"]
    built = (
        Component(type="ia.display.label")
        .bind_tag(prop_key, cfg["tagPath"])
        .script(fixture_code)
    )
    emit = built.model_dump(exclude_none=True, mode="json")
    emit_t = emit["propConfig"][prop_key]["binding"]["transforms"][0]

    # Whitespace MUST be preserved verbatim
    assert emit_t["code"] == fixture_code
    for k, v in fixture_t.items():
        assert k in emit_t, f"missing transform key {k!r}"
        assert emit_t[k] == v


# ----- regression smoke -----

def test_property_expression_tag_binding_regression_smoke():
    """Property/expression/tag binding chains still work after the transform additions."""
    # PropConfig path via bind_property
    c = Component(type="ia.display.label").bind_property("props.text", "view.params.title")
    assert c.propConfig[0].prop == "props.text"

    # .expression() chain still works
    c2 = (
        Component(type="x")
        .bind_property("props.text", "view.params.link")
        .expression("upper({value})")
    )
    assert c2.propConfig[0].binding.transforms[0].expression == "upper({value})"

    # .bind_tag() still works
    c3 = Component(type="x").bind_tag("props.text", "[default]X")
    assert c3.propConfig[0].binding.config.tagPath == "[default]X"
