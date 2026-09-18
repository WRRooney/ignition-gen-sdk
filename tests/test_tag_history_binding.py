"""Tests for TagHistoryBinding (most complex single binding).

Verifies:
- TagHistoryAggregation enum (13 values; MIN_MAX="MinMax" verified from fixture).
- TagHistoryTag + DurationRange + AbsoluteRange + ReturnSize sub-models.
- DateRange Pydantic v2 callable-discriminator union (no `type` field on either variant).
- TagHistoryBindingConfig with field_validator on `tags` (str | list[str] | list[dict] |
  expression-string passthrough).
- TagHistoryBinding (Literal["tag-history"] — with hyphen).
- Binding discriminated union expanded 5 -> 6 members.
- Component.bind_tag_history() with ergonomic kwargs mapping to gateway field names
  (paths -> tags, range -> dateRange, aggregation_mode -> aggregate).
- Range parsing: "1m" -> DurationRange(mostRecent="1", mostRecentUnits="MIN");
  (start_dt, end_dt) tuple -> AbsoluteRange; pre-built DurationRange/AbsoluteRange
  passes through.
- Two fixture-diff checks:
    * Relative range + single tag + polling (Bindings/view.json line 870-907).
    * Absolute range + multi-tag-expression + aggregate=MinMax (Application/
      Historical Data/view.json line 605-628).
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import get_args

import pytest
from pydantic import TypeAdapter, ValidationError

from ignition_gen_sdk.bindings import Binding
from ignition_gen_sdk.bindings.enums import TagHistoryAggregation
from ignition_gen_sdk.bindings.expression import ExpressionBinding
from ignition_gen_sdk.bindings.expression_structure import ExpressionStructureBinding
from ignition_gen_sdk.bindings.property import PropertyBinding
from ignition_gen_sdk.bindings.query import QueryBinding
from ignition_gen_sdk.bindings.tag import TagBinding
from ignition_gen_sdk.bindings.tag_history import (
    AbsoluteRange,
    DateRange,
    DurationRange,
    ReturnSize,
    TagHistoryBinding,
    TagHistoryBindingConfig,
    TagHistoryTag,
)
from ignition_gen_sdk.models.views.component import Component



from conftest import FIXTURE_ROOT  # noqa: E402


# ============================================================
# Enum + sub-models + TagHistoryBinding
# ============================================================


# ----- TagHistoryAggregation enum -----


def test_tag_history_aggregation_min_max_value():
    """TagHistoryAggregation.MIN_MAX.value == 'MinMax' (the verified value).

    Only fixture-verified value (from Components/Component Views/Charts/Time Series
    Chart/view.json — `aggregate: "MinMax"`).
    """
    assert TagHistoryAggregation.MIN_MAX.value == "MinMax"


def test_tag_history_aggregation_has_all_13_values():
    """TagHistoryAggregation enum has all 13 values."""
    expected_names = {
        "AVG", "MIN", "MAX", "SUM", "LAST_VALUE", "SIMPLE_AVG",
        "VARIANCE", "STD_DEV", "MIN_MAX", "RANGE", "COUNT",
        "DURATION_ON", "DURATION_OFF",
    }
    actual_names = {m.name for m in TagHistoryAggregation}
    assert actual_names == expected_names, f"got {actual_names}"
    assert len(list(TagHistoryAggregation)) == 13


# ----- DurationRange -----


def test_duration_range_constructs():
    """DurationRange(mostRecent='1', mostRecentUnits='MIN') constructs and emits."""
    dr = DurationRange(mostRecent="1", mostRecentUnits="MIN")
    assert dr.mostRecent == "1"
    assert dr.mostRecentUnits == "MIN"
    assert dr.model_dump() == {"mostRecent": "1", "mostRecentUnits": "MIN"}


def test_duration_range_requires_both_fields():
    """DurationRange() raises — both fields required."""
    with pytest.raises(ValidationError):
        DurationRange()  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        DurationRange(mostRecent="1")  # type: ignore[call-arg]


def test_duration_range_units_literal():
    """DurationRange(mostRecentUnits='BOGUS') raises (Literal restriction)."""
    with pytest.raises(ValidationError):
        DurationRange(mostRecent="1", mostRecentUnits="BOGUS")  # type: ignore[arg-type]


# ----- AbsoluteRange -----


def test_absolute_range_string_variant():
    """AbsoluteRange(startDate='{expr}', endDate='{expr}') accepts strings."""
    ar = AbsoluteRange(
        startDate="{view.custom.startDate}",
        endDate="{view.custom.endDate}",
    )
    assert ar.startDate == "{view.custom.startDate}"
    assert ar.endDate == "{view.custom.endDate}"


def test_absolute_range_datetime_variant():
    """AbsoluteRange(startDate=datetime, endDate=datetime) accepts datetimes; emit
    serializes via mode='json' to ISO."""
    ar = AbsoluteRange(startDate=datetime(2024, 1, 1), endDate=datetime(2024, 1, 2))
    dumped = ar.model_dump(mode="json")
    assert "startDate" in dumped
    assert "endDate" in dumped
    assert isinstance(dumped["startDate"], str)


# ----- DateRange callable discriminator -----


def test_date_range_discriminator_dispatches():
    """DateRange callable-discriminator picks DurationRange (mostRecent key) vs
    AbsoluteRange (startDate/endDate keys); rejects neither."""
    adapter = TypeAdapter(DateRange)
    dr = adapter.validate_python({"mostRecent": "1", "mostRecentUnits": "MIN"})
    assert isinstance(dr, DurationRange)

    ar = adapter.validate_python({"startDate": "x", "endDate": "y"})
    assert isinstance(ar, AbsoluteRange)

    with pytest.raises(ValidationError):
        adapter.validate_python({"bogus": "x"})


# ----- ReturnSize -----


def test_return_size_raw():
    """ReturnSize(type='RAW') constructs; numRows is None."""
    rs = ReturnSize(type="RAW")
    assert rs.type == "RAW"
    assert rs.numRows is None


def test_return_size_fixed_with_num_rows():
    """ReturnSize(type='FIXED', numRows='300') constructs; numRows is the STRING."""
    rs = ReturnSize(type="FIXED", numRows="300")
    assert rs.type == "FIXED"
    assert rs.numRows == "300"
    assert isinstance(rs.numRows, str)


def test_return_size_type_literal():
    """ReturnSize(type='BOGUS') raises — Literal['RAW', 'FIXED'] only."""
    with pytest.raises(ValidationError):
        ReturnSize(type="BOGUS")  # type: ignore[arg-type]


# ----- TagHistoryTag -----


def test_tag_history_tag_constructs():
    """TagHistoryTag(path='[X]Y') constructs."""
    t = TagHistoryTag(path="[Sample_Tags]Realistic/Realistic0")
    assert t.path == "[Sample_Tags]Realistic/Realistic0"


# ----- TagHistoryBindingConfig tags coercion -----


def test_tags_coerce_single_string():
    """tags='[X]A' coerced to [TagHistoryTag(path='[X]A')]."""
    cfg = TagHistoryBindingConfig(tags="[Sample_Tags]Realistic/Realistic0")
    assert isinstance(cfg.tags, list)
    assert len(cfg.tags) == 1
    assert cfg.tags[0].path == "[Sample_Tags]Realistic/Realistic0"


def test_tags_coerce_list_of_strings():
    """tags=['[X]A', '[X]B'] coerced to list[TagHistoryTag]."""
    cfg = TagHistoryBindingConfig(tags=["[X]A", "[X]B"])
    assert isinstance(cfg.tags, list)
    assert len(cfg.tags) == 2
    assert cfg.tags[0].path == "[X]A"
    assert cfg.tags[1].path == "[X]B"


def test_tags_list_of_dicts_passthrough():
    """tags=[{'path':'[X]A'}, {'path':'[X]B'}] becomes list[TagHistoryTag]."""
    cfg = TagHistoryBindingConfig(tags=[{"path": "[X]A"}, {"path": "[X]B"}])
    assert isinstance(cfg.tags, list)
    assert cfg.tags[0].path == "[X]A"


def test_tags_expression_string_passthrough():
    """tags='{view.custom.tagPaths}' (expression string starting with { and
    ending with }) PASSES THROUGH as str — NOT wrapped in a list. Gateway accepts
    binding-expression-string on the tags field per the gateway shape."""
    cfg = TagHistoryBindingConfig(tags="{view.custom.tagPaths}")
    assert cfg.tags == "{view.custom.tagPaths}"
    assert isinstance(cfg.tags, str)


# ----- TagHistoryBindingConfig minimal -----


def test_tag_history_binding_config_minimal():
    """TagHistoryBindingConfig(tags='[X]A') — all optionals None."""
    cfg = TagHistoryBindingConfig(tags="[X]A")
    assert cfg.dateRange is None
    assert cfg.aggregate is None
    assert cfg.returnSize is None
    assert cfg.returnFormat is None
    assert cfg.valueFormat is None
    assert cfg.polling is None
    assert cfg.ignoreBadQuality is None
    assert cfg.preventInterpolation is None
    assert cfg.avoidScanClassValidation is None


# ----- TagHistoryBinding discriminator -----


def test_tag_history_binding_type_default():
    """TagHistoryBinding default type is 'tag-history' (with hyphen)."""
    b = TagHistoryBinding(config=TagHistoryBindingConfig(tags="[X]A"))
    assert b.type == "tag-history"


# ----- Binding union 6 members -----


def test_binding_union_has_six_members():
    """Binding union has 6 members. >= N + membership idiom."""
    members = get_args(get_args(Binding)[0])
    assert len(members) >= 6
    assert PropertyBinding in members
    assert TagBinding in members
    assert ExpressionBinding in members
    assert ExpressionStructureBinding in members
    assert QueryBinding in members
    assert TagHistoryBinding in members


def test_binding_union_dispatches_tag_history():
    """TypeAdapter(Binding).validate_python({'type': 'tag-history', ...})
    returns TagHistoryBinding."""
    adapter = TypeAdapter(Binding)
    thb = adapter.validate_python(
        {"type": "tag-history", "config": {"tags": "[X]A"}}
    )
    assert isinstance(thb, TagHistoryBinding)


# ============================================================
# Component.bind_tag_history() + fixture diffs
# ============================================================


def test_bind_tag_history_minimal():
    """Component(type='x').bind_tag_history('props.data', paths='[X]A').
    Builds binding; type=='tag-history'; tags is list of one TagHistoryTag."""
    c = Component(type="x").bind_tag_history("props.data", paths="[X]A")
    pc = c.propConfig[0]
    assert pc.binding.type == "tag-history"
    assert isinstance(pc.binding.config.tags, list)
    assert pc.binding.config.tags[0].path == "[X]A"


def test_bind_tag_history_multi_tag_list():
    """paths=['[X]A', '[X]B'] -> multi-tag list."""
    c = Component(type="x").bind_tag_history("p", paths=["[X]A", "[X]B"])
    tags = c.propConfig[0].binding.config.tags
    assert isinstance(tags, list)
    assert len(tags) == 2


def test_bind_tag_history_expression_string_passthrough():
    """paths='{view.custom.tagPaths}' -> tags is STRING (not list)."""
    c = Component(type="x").bind_tag_history("p", paths="{view.custom.tagPaths}")
    assert c.propConfig[0].binding.config.tags == "{view.custom.tagPaths}"
    assert isinstance(c.propConfig[0].binding.config.tags, str)


def test_bind_tag_history_range_duration_string_1m():
    """range='1m' -> DurationRange(mostRecent='1', mostRecentUnits='MIN')."""
    c = Component(type="x").bind_tag_history("p", paths="[X]A", range="1m")
    dr = c.propConfig[0].binding.config.dateRange
    assert isinstance(dr, DurationRange)
    assert dr.mostRecent == "1"
    assert dr.mostRecentUnits == "MIN"


def test_bind_tag_history_range_parsing_all_suffixes():
    """every supported suffix parses correctly.

    ms=MS, s=SEC, m=MIN, h=HOUR, d=DAY, w=WEEK, M (UPPER)=MONTH, y=YEAR.
    """
    expected = {
        "1ms": ("1", "MS"),
        "30s": ("30", "SEC"),
        "5m": ("5", "MIN"),
        "1h": ("1", "HOUR"),
        "1d": ("1", "DAY"),
        "1w": ("1", "WEEK"),
        "1M": ("1", "MONTH"),
        "1y": ("1", "YEAR"),
    }
    for s, (num, unit) in expected.items():
        c = Component(type="x").bind_tag_history("p", paths="[X]A", range=s)
        dr = c.propConfig[0].binding.config.dateRange
        assert isinstance(dr, DurationRange), f"range={s!r} did not parse to DurationRange"
        assert dr.mostRecent == num, f"range={s!r}: mostRecent {dr.mostRecent!r} != {num!r}"
        assert dr.mostRecentUnits == unit, f"range={s!r}: units {dr.mostRecentUnits!r} != {unit!r}"


def test_bind_tag_history_range_invalid_suffix_raises():
    """range='5q' raises ValueError — unknown suffix."""
    c = Component(type="x")
    with pytest.raises(ValueError):
        c.bind_tag_history("p", paths="[X]A", range="5q")


def test_coerce_tags_loud_fail_on_malformed():
    """Non-str / non-list inputs raise ValueError with example
    (rather than fall through to a generic Pydantic union mismatch).
    """
    for bad in ({"path": "x"}, 42, object()):
        with pytest.raises((ValueError, ValidationError)):
            TagHistoryBindingConfig(tags=bad)


def test_bind_tag_history_range_degenerate_inputs_raise():
    """Degenerate inputs ('ms', 'sm', 's', 'h', '', non-digit prefix)
    must raise — previously they silently produced empty mostRecent.
    """
    c = Component(type="x")
    for bad in ("ms", "sm", "s", "h", "", "abch"):
        with pytest.raises(ValueError):
            c.bind_tag_history("p", paths="[X]A", range=bad)


def test_bind_tag_history_range_datetime_tuple():
    """range=(start, end) tuple of datetimes parses to AbsoluteRange."""
    start = datetime(2024, 1, 1)
    end = datetime(2024, 1, 2)
    c = Component(type="x").bind_tag_history("p", paths="[X]A", range=(start, end))
    ar = c.propConfig[0].binding.config.dateRange
    assert isinstance(ar, AbsoluteRange)


def test_bind_tag_history_range_prebuilt_absolute_range():
    """range=AbsoluteRange(...) — pre-built object passes through verbatim."""
    pre = AbsoluteRange(
        startDate="{view.custom.startDate}",
        endDate="{view.custom.endDate}",
    )
    c = Component(type="x").bind_tag_history("p", paths="[X]A", range=pre)
    ar = c.propConfig[0].binding.config.dateRange
    assert isinstance(ar, AbsoluteRange)
    assert ar.startDate == "{view.custom.startDate}"


def test_bind_tag_history_aggregation_mode_enum():
    """aggregation_mode=TagHistoryAggregation.MIN_MAX -> aggregate emits as 'MinMax'.

    use_enum_values=True on IgnitionBaseModel: enum stored as its .value string
    on the model instance so emission is automatic.
    """
    c = Component(type="x").bind_tag_history(
        "p", paths="[X]A", aggregation_mode=TagHistoryAggregation.MIN_MAX
    )
    # use_enum_values=True: stored as string
    assert c.propConfig[0].binding.config.aggregate == "MinMax"


def test_bind_tag_history_return_size_from_kwarg_pair_fixed():
    """return_size_type='FIXED', return_size_num_rows='300' -> ReturnSize."""
    c = Component(type="x").bind_tag_history(
        "p",
        paths="[X]A",
        return_size_type="FIXED",
        return_size_num_rows="300",
    )
    rs = c.propConfig[0].binding.config.returnSize
    assert isinstance(rs, ReturnSize)
    assert rs.type == "FIXED"
    assert rs.numRows == "300"


def test_bind_tag_history_return_size_from_kwarg_pair_raw():
    """return_size_type='RAW' (no numRows) -> ReturnSize(type='RAW', numRows=None)."""
    c = Component(type="x").bind_tag_history(
        "p", paths="[X]A", return_size_type="RAW"
    )
    rs = c.propConfig[0].binding.config.returnSize
    assert rs.type == "RAW"
    assert rs.numRows is None


def test_bind_tag_history_polling_kwargs():
    """polling_enabled + polling_rate kwargs build PollingConfig."""
    c = Component(type="x").bind_tag_history(
        "p", paths="[X]A", polling_enabled=True, polling_rate="1"
    )
    polling = c.propConfig[0].binding.config.polling
    assert polling is not None
    assert polling.enabled is True
    assert polling.rate == "1"


def test_bind_tag_history_all_kwargs_map_to_fields():
    """all ergonomic kwargs map to model fields."""
    c = Component(type="x").bind_tag_history(
        "p",
        paths="[X]A",
        return_format="Wide",
        value_format="DATASET",
        ignore_bad_quality=False,
        prevent_interpolation=False,
        avoid_scan_class_validation=True,
    )
    cfg = c.propConfig[0].binding.config
    assert cfg.returnFormat == "Wide"
    assert cfg.valueFormat == "DATASET"
    assert cfg.ignoreBadQuality is False
    assert cfg.preventInterpolation is False
    assert cfg.avoidScanClassValidation is True


# ----- Fixture diffs -----


def _load_view(view_relpath: str) -> dict:
    if FIXTURE_ROOT is None:
        pytest.skip("IGNITION_SAMPLE_VIEWS not set; fixture-diff test skipped.")
    p = FIXTURE_ROOT / view_relpath
    with p.open("r") as fp:
        return json.load(fp)


def _walk_find_propconfig_by_type(node, target_type, accum=None):
    """Walk a view tree; collect (prop_path, binding_dict) for matching bindings."""
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
    """Assert every key+value in `subset` is present in `superset` with same value."""
    for k, v in subset.items():
        ctx = f"{path}/{k}"
        assert k in superset, f"missing key {ctx} in superset: {superset}"
        if isinstance(v, dict):
            assert isinstance(superset[k], dict), f"{ctx}: expected dict, got {type(superset[k])}"
            _is_superset(superset[k], v, ctx)
        elif isinstance(v, list):
            assert isinstance(superset[k], list), f"{ctx}: expected list, got {type(superset[k])}"
            assert len(superset[k]) == len(v), f"{ctx}: list length mismatch"
            for i, (sup_item, sub_item) in enumerate(zip(superset[k], v)):
                if isinstance(sub_item, dict):
                    _is_superset(sup_item, sub_item, f"{ctx}[{i}]")
                else:
                    assert sup_item == sub_item, f"{ctx}[{i}]: {sup_item!r} != {sub_item!r}"
        else:
            assert superset[k] == v, f"{ctx}: {superset[k]!r} != {v!r}"


def test_fixture_diff_relative_range_single_tag_polling():
    """Fixture-diff against Bindings/view.json tag-history (line 870-907).

    Fixture binding shape:
      {"config": {"avoidScanClassValidation": true,
                  "dateRange": {"mostRecent": "1", "mostRecentUnits": "MIN"},
                  "ignoreBadQuality": false,
                  "polling": {"enabled": true, "rate": "1"},
                  "preventInterpolation": false,
                  "returnFormat": "Wide",
                  "returnSize": {"type": "RAW"},
                  "tags": [{"path": "[Sample_Tags]Realistic/Realistic0"}],
                  "valueFormat": "DATASET"},
       "type": "tag-history"}
    """
    view = _load_view(
        "Ignition 101/Feature Views/Perspective Features/Bindings/view.json"
    )
    found = _walk_find_propconfig_by_type(view, "tag-history")
    assert found, "no tag-history binding found in Bindings/view.json"

    # Choose the relative-range one (has mostRecent in dateRange) without aggregate
    target = None
    for prop, b in found:
        cfg = b.get("config", {})
        if "mostRecent" in cfg.get("dateRange", {}) and "aggregate" not in cfg:
            target = (prop, b)
            break
    assert target is not None, "no relative-range non-aggregate tag-history found"
    prop_path, fixture_binding = target
    fixture_cfg = fixture_binding["config"]

    rebuilt = Component(type="ia.chart.timeseries").bind_tag_history(
        prop_path,
        paths=fixture_cfg["tags"][0]["path"],
        range=DurationRange(
            mostRecent=fixture_cfg["dateRange"]["mostRecent"],
            mostRecentUnits=fixture_cfg["dateRange"]["mostRecentUnits"],
        ),
        polling_enabled=fixture_cfg["polling"]["enabled"],
        polling_rate=fixture_cfg["polling"]["rate"],
        return_format=fixture_cfg["returnFormat"],
        return_size_type=fixture_cfg["returnSize"]["type"],
        value_format=fixture_cfg["valueFormat"],
        ignore_bad_quality=fixture_cfg["ignoreBadQuality"],
        prevent_interpolation=fixture_cfg["preventInterpolation"],
        avoid_scan_class_validation=fixture_cfg["avoidScanClassValidation"],
    )
    emitted = rebuilt.model_dump(exclude_none=True, mode="json")["propConfig"][
        prop_path
    ]["binding"]
    _is_superset(emitted, fixture_binding)


def test_fixture_diff_absolute_range_expression_tags_aggregate():
    """Fixture-diff against Application/Historical Data/view.json.

    Fixture shape (line 605-628):
      {"config": {"aggregate": "MinMax",
                  "avoidScanClassValidation": true,
                  "dateRange": {"endDate": "{...}", "startDate": "{...}"},
                  "enableValueCache": true,
                  "ignoreBadQuality": false,
                  "preventInterpolation": false,
                  "returnFormat": "Wide",
                  "returnSize": {"numRows": "100", "type": "FIXED"},
                  "tags": "{parent.custom.selectedTags}",
                  "valueFormat": "DATASET"},
       "type": "tag-history"}
    """
    view = _load_view(
        "Ignition 101/Feature Views/Application/Historical Data/view.json"
    )
    found = _walk_find_propconfig_by_type(view, "tag-history")
    assert found, "no tag-history binding in Historical Data/view.json"

    # Choose the absolute-range + tags-as-string + MinMax one
    target = None
    for prop, b in found:
        cfg = b.get("config", {})
        if (
            "startDate" in cfg.get("dateRange", {})
            and isinstance(cfg.get("tags"), str)
            and cfg.get("aggregate") == "MinMax"
        ):
            target = (prop, b)
            break
    assert target is not None, "no absolute+expression-tags+MinMax tag-history found"
    prop_path, fixture_binding = target
    fixture_cfg = fixture_binding["config"]

    # tags is the expression-string (passthrough)
    assert isinstance(fixture_cfg["tags"], str)
    assert fixture_cfg["tags"].startswith("{")

    rebuilt = Component(type="ia.chart.timeseries").bind_tag_history(
        prop_path,
        paths=fixture_cfg["tags"],
        range=AbsoluteRange(
            startDate=fixture_cfg["dateRange"]["startDate"],
            endDate=fixture_cfg["dateRange"]["endDate"],
        ),
        aggregation_mode=TagHistoryAggregation.MIN_MAX,
        return_format=fixture_cfg["returnFormat"],
        return_size_type=fixture_cfg["returnSize"]["type"],
        return_size_num_rows=fixture_cfg["returnSize"]["numRows"],
        value_format=fixture_cfg["valueFormat"],
        ignore_bad_quality=fixture_cfg["ignoreBadQuality"],
        prevent_interpolation=fixture_cfg["preventInterpolation"],
        avoid_scan_class_validation=fixture_cfg["avoidScanClassValidation"],
        enable_value_cache=fixture_cfg["enableValueCache"],
    )
    emitted = rebuilt.model_dump(exclude_none=True, mode="json")["propConfig"][
        prop_path
    ]["binding"]
    _is_superset(emitted, fixture_binding)

    # Lock: tags is a STRING (not list) in the emitted JSON
    assert isinstance(emitted["config"]["tags"], str)
    assert emitted["config"]["tags"] == fixture_cfg["tags"]


# ----- Cross-binding regression smoke -----


def test_regression_smoke_all_six_bindings():
    """regression — all 6 binding types chainable + transforms still work."""
    from ignition_gen_sdk.bindings.enums import TagBindingMode

    c = (
        Component(type="ia.display.label")
        .bind_property("props.a", "view.params.a")
        .expression("upper({value})")
        .bind_tag("props.b", "[default]X", mode=TagBindingMode.DIRECT)
        .map({"a": "A"}).format("0.0").script("return value")
        .bind_expression("props.c", "toBoolean({x})")
        .bind_expression_structure("props.d", struct={"k": "v"})
        .bind_query("props.e", queryPath="x", polling_enabled=True, polling_rate="5")
        .bind_tag_history("props.f", paths="[X]A", range="1h")
    )
    types = [pc.binding.type for pc in c.propConfig]
    assert types == [
        "property", "tag", "expr", "expr-struct", "query", "tag-history"
    ]
